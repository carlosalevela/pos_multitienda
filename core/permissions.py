# core/permissions.py

from rest_framework.permissions import IsAuthenticated
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


class EsCualquierRol(IsAuthenticated):
    """Cualquier usuario autenticado con rol válido."""
    def has_permission(self, request, view):
        return super().has_permission(request, view) and \
               request.user.rol in [
                   "superadmin", "admin", "supervisor", "cajero"]


def es_superadmin(request):
    return request.user.rol == "superadmin"


def get_empresa(request):
    """
    Retorna la empresa del usuario.
    Superadmin retorna None sin lanzar error.
    """
    user = request.user
    if user.rol == "superadmin":
        return None
    if not hasattr(user, "empresa") or user.empresa_id is None:
        raise PermissionDenied("El usuario no tiene una empresa asignada.")
    return user.empresa