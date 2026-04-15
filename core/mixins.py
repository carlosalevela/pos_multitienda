# core/mixins.py

class EmpresaScopedMixin:
    """
    Filtra cualquier ViewSet por la empresa del empleado autenticado.

    Uso básico (modelo tiene FK `empresa` directa):
        class MiViewSet(EmpresaScopedMixin, viewsets.ModelViewSet): ...

    Uso con relación indirecta (ej: Compra → tienda → empresa):
        class CompraViewSet(EmpresaScopedMixin, viewsets.ModelViewSet):
            empresa_field = "tienda__empresa"
    """

    empresa_field = "empresa"   # override por ViewSet si la FK es indirecta

    def get_empresa(self):
        return self.request.user.empresa

    def get_queryset(self):
        qs      = super().get_queryset()
        empresa = self.get_empresa()
        if empresa is None:
            return qs.none()           # empleado sin empresa → sin datos
        return qs.filter(**{self.empresa_field: empresa})

    def perform_create(self, serializer):
        empresa = self.get_empresa()
        if self.empresa_field == "empresa":
            serializer.save(empresa=empresa)   # inyecta empresa automáticamente
        else:
            serializer.save()                  # la FK empresa va por tienda