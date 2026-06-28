from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from core.permissions import es_superadmin, get_empresa
from tiendas.models import Tienda

from .models import ConfigTienda, ConfigImpresion, METODOS_PAGO_DEFAULT
from .serializers import ConfigTiendaSerializer, ConfigImpresionSerializer


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
            "iva_pct":             float(empresa.iva_pct) if empresa and hasattr(empresa, "iva_pct") else 0,
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
