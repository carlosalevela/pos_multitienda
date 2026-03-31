from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    LoginView, LogoutView, MiPerfilView,
    EmpleadoListCreateView, EmpleadoDetailView, CambiarPasswordView,
)

urlpatterns = [
    path("login/",              LoginView.as_view(),              name="login"),
    path("logout/",             LogoutView.as_view(),             name="logout"),
    path("token/refresh/",      TokenRefreshView.as_view(),       name="token_refresh"),
    path("perfil/",             MiPerfilView.as_view(),           name="mi_perfil"),
    path("cambiar-password/",   CambiarPasswordView.as_view(),    name="cambiar_password"),
    path("empleados/",          EmpleadoListCreateView.as_view(), name="empleados"),
    path("empleados/<int:pk>/", EmpleadoDetailView.as_view(),     name="empleado_detail"),
]