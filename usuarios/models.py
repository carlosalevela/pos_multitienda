from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin


class EmpleadoManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("El email es obligatorio")
        email = self.normalize_email(email)
        user  = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save()
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("rol", "superadmin")  # ← superadmin
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)


class Empleado(AbstractBaseUser, PermissionsMixin):
    ROL_CHOICES = [
        ("superadmin", "Super Administrador"),  # ← nuevo
        ("admin",      "Administrador"),
        ("supervisor", "Supervisor"),
        ("cajero",     "Cajero"),
    ]

    empresa = models.ForeignKey(
        "empresas.Empresa", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="empleados"
    )
    tienda = models.ForeignKey(
        "tiendas.Tienda", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="empleados"
    )
    nombre     = models.CharField(max_length=100)
    apellido   = models.CharField(max_length=100)
    cedula     = models.CharField(max_length=20, unique=True)
    email      = models.EmailField(unique=True)
    rol        = models.CharField(
        max_length=20, choices=ROL_CHOICES, default="cajero")
    activo     = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_staff   = models.BooleanField(default=False)

    USERNAME_FIELD  = "email"
    REQUIRED_FIELDS = ["nombre", "apellido", "cedula"]
    objects = EmpleadoManager()

    def __str__(self):
        return f"{self.nombre} {self.apellido} ({self.rol})"

    # ── Helpers de rol ───────────────────────────────────
    @property
    def es_superadmin(self):
        return self.rol == "superadmin"

    @property
    def es_admin(self):
        return self.rol in ["superadmin", "admin"]

    @property
    def es_supervisor(self):
        return self.rol in ["superadmin", "admin", "supervisor"]

    class Meta:
        db_table = "empleados"