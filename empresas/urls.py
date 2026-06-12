# empresas/urls.py

from django.urls import path
from .views import (
    EmpresaListCreateView,
    EmpresaDetailView,
    EmpresaConfigMayoreoView,  # ✅
)

urlpatterns = [
    path('',              EmpresaListCreateView.as_view()),
    path('<int:pk>/',     EmpresaDetailView.as_view()),
    path('<int:pk>/mayoreo/', EmpresaConfigMayoreoView.as_view()),  # ✅
]