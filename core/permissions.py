from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.exceptions import PermissionDenied


class EsSuperAdmin(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and \
               request.user.rol == "superadmin"


class EsAdmin(IsAuthenticated):
    """Superadmin + admin de empresa."""
    def has_permission(self, request, view):
        return super().has_permission(request, view) and \
               request.user.rol in ["superadmin", "admin"]


class EsAdminOSupervisor(IsAuthenticated):
    """Superadmin + admin + supervisor."""
    def has_permission(self, request, view):
        return super().has_permission(request, view) and \
               request.user.rol in ["superadmin", "admin", "supervisor"]


class EsAdminSupervisorOCajero(IsAuthenticated):
    """Superadmin + admin + supervisor + cajero."""
    def has_permission(self, request, view):
        return super().has_permission(request, view) and \
               request.user.rol in ["superadmin", "admin", "supervisor", "cajero"]


# Alias semántico — mismo conjunto de roles
EsCualquierRol = EsAdminSupervisorOCajero


def es_superadmin(request):
    return request.user.rol == "superadmin"


def get_empresa(request):
    """Retorna la empresa del usuario. Para superadmin retorna None."""
    user = request.user
    if user.rol == "superadmin":
        return None
    if not hasattr(user, "empresa") or user.empresa_id is None:
        raise PermissionDenied("El usuario no tiene una empresa asignada.")
    return user.empresa


def scope_qs(request, *querysets, campo_empresa="tienda__empresa", tienda_id=None):
    """Aplica filtro de empresa (y opcionalmente tienda) a uno o más querysets.

    Retorna el queryset filtrado (único) o una tupla (varios).
    """
    if es_superadmin(request):
        empresa_id = request.query_params.get("empresa")
        if empresa_id:
            querysets = tuple(
                qs.filter(**{f"{campo_empresa}_id": empresa_id})
                for qs in querysets
            )
    else:
        empresa   = get_empresa(request)
        querysets = tuple(
            qs.filter(**{campo_empresa: empresa})
            for qs in querysets
        )
    if tienda_id:
        querysets = tuple(qs.filter(tienda_id=tienda_id) for qs in querysets)
    return querysets[0] if len(querysets) == 1 else querysets