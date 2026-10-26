"""
python manage.py enviar_recordatorios_separados

Envía recordatorios de WhatsApp a clientes con separados próximos a vencer:
  - 7 días antes → recordatorio suave
  - 2 días antes → recordatorio urgente

Configurar en Railway como cron job:
  Comando:  python manage.py enviar_recordatorios_separados
  Horario:  0 14 * * *   (9 AM hora Colombia = 14:00 UTC)
"""

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from clientes.models import Separado
from configuracion.whatsapp_service import enviar_recordatorio_separado
from empresas.models import Empresa

logger = logging.getLogger(__name__)

UMBRALES = [7, 2]   # días antes del vencimiento en que se envía recordatorio


class Command(BaseCommand):
    help = "Envía recordatorios WhatsApp a clientes con separados próximos a vencer."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dias",
            nargs="+",
            type=int,
            default=UMBRALES,
            help="Días antes del vencimiento para enviar (default: 7 2)",
        )
        parser.add_argument(
            "--empresa-id",
            type=int,
            default=None,
            help="Limitar a una empresa específica (opcional)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Muestra qué se enviaría sin mandar nada.",
        )

    def handle(self, *args, **options):
        hoy      = timezone.localdate()
        umbrales = options["dias"]
        dry_run  = options["dry_run"]
        empresa_id_forzado = options["empresa_id"]

        self.stdout.write(
            f"[recordatorios] Fecha: {hoy}  |  Umbrales: {umbrales} días  "
            f"{'| DRY RUN' if dry_run else ''}"
        )

        # Empresas a procesar
        if empresa_id_forzado:
            empresas = Empresa.objects.filter(pk=empresa_id_forzado, activo=True)
        else:
            empresas = Empresa.objects.filter(activo=True)

        total_enviados = 0
        total_sin_tel  = 0
        total_errores  = 0

        for empresa in empresas:
            for dias in umbrales:
                fecha_objetivo = hoy + timedelta(days=dias)

                qs = Separado.objects.filter(
                    tienda__empresa=empresa,
                    estado="activo",
                    saldo_pendiente__gt=0,
                    fecha_limite=fecha_objetivo,   # exactamente ese día
                ).select_related("cliente", "tienda")

                if not qs.exists():
                    continue

                separados_data = []
                for sep in qs:
                    separados_data.append({
                        "separado_id":    sep.id,
                        "cliente_nombre": f"{sep.cliente.nombre} {sep.cliente.apellido}".strip(),
                        "tienda_nombre":  sep.tienda.nombre,
                        "fecha_limite":   sep.fecha_limite.strftime("%d/%m/%Y"),
                        "saldo_pendiente": f"{int(sep.saldo_pendiente):,}".replace(",", "."),
                        "telefono":       sep.cliente.telefono,
                    })

                self.stdout.write(
                    f"  Empresa '{empresa.nombre}' | vencen en {dias} días "
                    f"({fecha_objetivo}): {len(separados_data)} separado(s)"
                )

                if dry_run:
                    for s in separados_data:
                        self.stdout.write(
                            f"    → #{s['separado_id']} {s['cliente_nombre']} "
                            f"tel={s['telefono'] or 'SIN TEL'} "
                            f"saldo=${s['saldo_pendiente']}"
                        )
                    continue

                resultado = enviar_recordatorio_separado(
                    empresa_id=empresa.id,
                    tienda_id=None,
                    separados=separados_data,
                )
                total_enviados += resultado.get("enviados", 0)
                total_sin_tel  += len(resultado.get("sin_telefono", []))
                total_errores  += len(resultado.get("errores", []))

                if resultado.get("sin_telefono"):
                    for x in resultado["sin_telefono"]:
                        logger.warning("Sin teléfono: %s", x)
                if resultado.get("errores"):
                    for e in resultado["errores"]:
                        logger.error("Error WA: %s", e)

        self.stdout.write(
            f"\n[recordatorios] Enviados: {total_enviados} | "
            f"Sin teléfono: {total_sin_tel} | Errores: {total_errores}"
        )
