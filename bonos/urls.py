from django.urls import path
from .views import (
    BonoVenderView,
    BonoValidarView,
    BonoRedimirView,
    BonoListView,
    BonoDetailView,
)

urlpatterns = [
    path('',          BonoListView.as_view(),    name='bono-list'),
    path('vender/',   BonoVenderView.as_view(),  name='bono-vender'),
    path('validar/',  BonoValidarView.as_view(), name='bono-validar'),
    path('redimir/',  BonoRedimirView.as_view(), name='bono-redimir'),
    path('<str:codigo>/', BonoDetailView.as_view(), name='bono-detail'),
]
