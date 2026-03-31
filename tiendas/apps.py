from django.apps import AppConfig


class TiendasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tiendas"

    def ready(self):
        import tiendas.signals  # noqa