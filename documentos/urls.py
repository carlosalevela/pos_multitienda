from django.urls import path
from . import views

urlpatterns = [
    path('',              views.DocumentoListView.as_view(),    name='documento-list'),
    path('subir/',        views.DocumentoUploadView.as_view(),  name='documento-subir'),
    path('<int:pk>/pdf/', views.DocumentoDescargarView.as_view(), name='documento-pdf'),
]
