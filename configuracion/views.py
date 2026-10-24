from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.db import models
from django.db.models import Sum

from core.permissions import es_superadmin, get_empresa
from tiendas.models import Tienda

from .models import ConfigTienda, ConfigImpresion, CuentaBancaria, METODOS_PAGO_DEFAULT
from .serializers import (ConfigTiendaSerializer, ConfigImpresionSerializer,
                           CuentaBancariaSerializer)


def _get_tienda(request, tienda_id):
    """
    Resuelve la tienda verificando que pertenezca a la empresa del usuario.
    El cajero solo puede resolver su propia tienda.
    Retorna (tienda, error_response).
    """
    filtro = {"pk": tienda_id}
    if not es_superadmin(request):
        filtro["empresa"] = get_empresa(request)

    # Cajero solo puede leer la config de su propia tienda
    if request.user.rol == "cajero" and str(request.user.tienda_id) != str(tienda_id):
        return None, Response({"error": "Solo puedes consultar la config de tu tienda."}, status=403)

    try:
        return Tienda.objects.get(**filtro), None
    except Tienda.DoesNotExist:
        return None, Response({"error": "Tienda no encontrada."}, status=404)


def _puede_editar(request):
    return request.user.rol in ("superadmin", "admin", "supervisor")


# ── Configuración General de Tienda ───────────────────────────
class ConfigTiendaView(APIView):
    """
    GET   /api/config/tienda/<tienda_id>/  → Todos los roles (cajero: solo su tienda)
    PATCH /api/config/tienda/<tienda_id>/  → Admin y Supervisor únicamente
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, tienda_id):
        tienda, err = _get_tienda(request, tienda_id)
        if err:
            return err
        config, _ = ConfigTienda.objects.get_or_create(
            tienda=tienda,
            defaults={"metodos_pago": METODOS_PAGO_DEFAULT},
        )
        return Response(ConfigTiendaSerializer(config).data)

    def patch(self, request, tienda_id):
        if not _puede_editar(request):
            return Response({"error": "No tienes permiso para modificar la configuración."}, status=403)
        tienda, err = _get_tienda(request, tienda_id)
        if err:
            return err
        config, _ = ConfigTienda.objects.get_or_create(
            tienda=tienda,
            defaults={"metodos_pago": METODOS_PAGO_DEFAULT},
        )
        serializer = ConfigTiendaSerializer(config, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        serializer.save()
        return Response(serializer.data)


# ── Configuración de Impresión ────────────────────────────────
class ConfigImpresionView(APIView):
    """
    GET   /api/config/impresion/<tienda_id>/  → Todos los roles (cajero: solo su tienda)
    PATCH /api/config/impresion/<tienda_id>/  → Admin y Supervisor únicamente
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, tienda_id):
        tienda, err = _get_tienda(request, tienda_id)
        if err:
            return err
        config, _ = ConfigImpresion.objects.get_or_create(tienda=tienda)
        return Response(ConfigImpresionSerializer(config).data)

    def patch(self, request, tienda_id):
        if not _puede_editar(request):
            return Response({"error": "No tienes permiso para modificar la configuración."}, status=403)
        tienda, err = _get_tienda(request, tienda_id)
        if err:
            return err
        config, _ = ConfigImpresion.objects.get_or_create(tienda=tienda)
        serializer = ConfigImpresionSerializer(config, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        serializer.save()
        return Response(serializer.data)


# ── Defaults de empresa (para pre-rellenar formularios) ───────
class ConfigDefaultsView(APIView):
    """
    GET /api/config/defaults/
    Devuelve los valores por defecto de la empresa para pre-rellenar
    formularios de configuración al crear una nueva tienda.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        empresa = None if es_superadmin(request) else get_empresa(request)
        return Response({
            "moneda_simbolo":      "$",
            "moneda_codigo":       "USD",
            "iva_pct":             float(
                ConfigTienda.objects
                .filter(tienda__empresa=empresa)
                .values_list("iva_pct", flat=True)
                .first() or 0
            ) if empresa else 0,
            "metodos_pago":        METODOS_PAGO_DEFAULT,
            "habilitar_mayoreo":   empresa.maneja_mayoreo if empresa else False,
            "cantidad_mayoreo":    empresa.cantidad_mayoreo if empresa else 12,
            "abono_minimo_pct":    20,
            "dias_max_liquidar":   30,
            "politica_cancelacion":"retener",
            "dias_alerta_separados": 3,
            "tipo_papel":          "80mm",
            "copias":              1,
            "mostrar_logo":        True,
            "mostrar_nit":         True,
            "mensaje_pie":         "",
        })


# ── Cuentas Bancarias / Nequi / DaviPlata ────────────────────

class CuentaBancariaListView(APIView):
    """
    GET  /api/config/cuentas/<tienda_id>/  → lista activas de la tienda
    POST /api/config/cuentas/<tienda_id>/  → crear nueva (admin/supervisor)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, tienda_id):
        tienda, err = _get_tienda(request, tienda_id)
        if err:
            return err
        qs = CuentaBancaria.objects.filter(
            empresa=tienda.empresa,
            activo=True,
        ).filter(
            models.Q(tienda=tienda) | models.Q(tienda__isnull=True)
        )
        return Response(CuentaBancariaSerializer(qs, many=True).data)

    def post(self, request, tienda_id):
        if not _puede_editar(request):
            return Response({"error": "No tienes permiso."}, status=403)
        tienda, err = _get_tienda(request, tienda_id)
        if err:
            return err
        s = CuentaBancariaSerializer(data=request.data)
        if not s.is_valid():
            return Response(s.errors, status=400)
        s.save(empresa=tienda.empresa, tienda=tienda)
        return Response(s.data, status=201)


class CuentaBancariaDetailView(APIView):
    """
    PATCH  /api/config/cuentas/<tienda_id>/<cuenta_id>/  → editar
    DELETE /api/config/cuentas/<tienda_id>/<cuenta_id>/  → desactivar
    """
    permission_classes = [IsAuthenticated]

    def _get_cuenta(self, request, tienda_id, cuenta_id):
        tienda, err = _get_tienda(request, tienda_id)
        if err:
            return None, None, err
        try:
            cuenta = CuentaBancaria.objects.get(pk=cuenta_id, empresa=tienda.empresa)
        except CuentaBancaria.DoesNotExist:
            return None, None, Response({"error": "Cuenta no encontrada."}, status=404)
        return tienda, cuenta, None

    def patch(self, request, tienda_id, cuenta_id):
        if not _puede_editar(request):
            return Response({"error": "No tienes permiso."}, status=403)
        _, cuenta, err = self._get_cuenta(request, tienda_id, cuenta_id)
        if err:
            return err
        s = CuentaBancariaSerializer(cuenta, data=request.data, partial=True)
        if not s.is_valid():
            return Response(s.errors, status=400)
        s.save()
        return Response(s.data)

    def delete(self, request, tienda_id, cuenta_id):
        if not _puede_editar(request):
            return Response({"error": "No tienes permiso."}, status=403)
        _, cuenta, err = self._get_cuenta(request, tienda_id, cuenta_id)
        if err:
            return err
        cuenta.activo = False
        cuenta.save(update_fields=["activo"])
        return Response(status=204)


class ResumenCuentasView(APIView):
    """
    GET /api/config/cuentas/<tienda_id>/resumen/?sesion_id=X
    Retorna por cuenta: total de esa sesión + acumulado histórico (ventas completadas).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, tienda_id):
        from ventas.models import Venta

        tienda, err = _get_tienda(request, tienda_id)
        if err:
            return err

        sesion_id = request.query_params.get("sesion_id")

        cuentas = CuentaBancaria.objects.filter(
            empresa=tienda.empresa,
        ).filter(
            models.Q(tienda=tienda) | models.Q(tienda__isnull=True)
        )

        base_ventas = Venta.objects.filter(
            tienda=tienda, estado="completada",
            cuenta_destino__isnull=False,
        )

        sesion_totals = {}
        if sesion_id:
            for row in (base_ventas
                        .filter(sesion_caja_id=sesion_id)
                        .values("cuenta_destino_id")
                        .annotate(t=Sum("total"))):
                sesion_totals[row["cuenta_destino_id"]] = float(row["t"] or 0)

        acum_totals = {}
        for row in (base_ventas
                    .values("cuenta_destino_id")
                    .annotate(t=Sum("total"))):
            acum_totals[row["cuenta_destino_id"]] = float(row["t"] or 0)

        result = []
        for c in cuentas:
            sesion_t = sesion_totals.get(c.id, 0)
            acum_t   = acum_totals.get(c.id, 0)
            if sesion_t == 0 and acum_t == 0:
                continue
            result.append({
                "id":             c.id,
                "nombre":         c.nombre,
                "tipo":           c.tipo,
                "tipo_display":   c.get_tipo_display(),
                "numero":         c.numero,
                "sesion_total":   sesion_t,
                "total_acumulado": acum_t,
            })

        return Response(result)


# ── Versión de la app (auto-update) ──────────────────────────
class AppVersionView(APIView):
    permission_classes = [AllowAny]

    # Actualiza estos valores al publicar una nueva versión
    LATEST_VERSION = "1.3.0"
    DOWNLOAD_URL   = "https://github.com/carlosalevela/pos_multitienda_front/releases/download/v1.3.0/POS_Multitienda_Setup.exe"

    def get(self, request):
        return Response({
            "version":      self.LATEST_VERSION,
            "download_url": self.DOWNLOAD_URL,
            "obligatoria":  False,  # True fuerza la actualización
        })
