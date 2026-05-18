from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


def validar_mayor_de_edad(fecha_nacimiento):
    """
    Valida que el usuario tenga al menos 18 años al momento del registro.
    No se almacena la edad, solo se verifica en tiempo de ejecución.
    """
    hoy = timezone.now().date()
    edad = (
        hoy.year - fecha_nacimiento.year
        - ((hoy.month, hoy.day) < (fecha_nacimiento.month, fecha_nacimiento.day))
    )
    if edad < 18:
        raise ValidationError(
            _("El usuario debe tener al menos 18 años para registrarse.")
        )


class UsuarioManager(BaseUserManager):
    """
    Manager personalizado para el modelo Usuario.
    Maneja la creación de usuarios normales y superusuarios.
    """

    def create_user(self, email, nombre, apellido, nro_documento, fecha_nacimiento, password=None, **extra_fields):
        if not email:
            raise ValueError(_("El email es obligatorio."))
        if not nro_documento:
            raise ValueError(_("El número de documento es obligatorio."))

        email = self.normalize_email(email)

        # Validar mayoría de edad antes de crear
        validar_mayor_de_edad(fecha_nacimiento)

        usuario = self.model(
            email=email,
            nombre=nombre,
            apellido=apellido,
            nro_documento=nro_documento,
            fecha_nacimiento=fecha_nacimiento,
            **extra_fields,
        )
        # set_password hashea la contraseña usando PBKDF2 + SHA256 (Django default)
        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario

    def create_superuser(self, email, nombre, apellido, nro_documento, fecha_nacimiento, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError(_("El superusuario debe tener is_staff=True."))
        if extra_fields.get("is_superuser") is not True:
            raise ValueError(_("El superusuario debe tener is_superuser=True."))

        return self.create_user(
            email, nombre, apellido, nro_documento, fecha_nacimiento, password, **extra_fields
        )


class Usuario(AbstractBaseUser, PermissionsMixin):
    """
    Modelo de usuario personalizado.

    - Identificador: id autoincremental (PK por defecto de Django).
    - Login con email en lugar de username.
    - La contraseña es hasheada automáticamente por AbstractBaseUser.set_password().
    - La edad NO se almacena; se verifica solo al crear la cuenta.
    """

    id = models.AutoField(primary_key=True, verbose_name=_("ID"))

    nombre = models.CharField(
        max_length=100,
        verbose_name=_("Nombre"),
    )
    apellido = models.CharField(
        max_length=100,
        verbose_name=_("Apellido"),
    )
    nro_documento = models.CharField(
        max_length=20,
        unique=True,
        verbose_name=_("Número de documento"),
    )
    email = models.EmailField(
        unique=True,
        verbose_name=_("Email"),
    )
    fecha_nacimiento = models.DateField(
        verbose_name=_("Fecha de nacimiento"),
        validators=[validar_mayor_de_edad],
    )

    # Campos requeridos por Django auth
    is_active = models.BooleanField(default=True, verbose_name=_("Activo"))
    is_staff = models.BooleanField(default=False, verbose_name=_("Staff"))
    date_joined = models.DateTimeField(auto_now_add=True, verbose_name=_("Fecha de registro"))

    objects = UsuarioManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["nombre", "apellido", "nro_documento", "fecha_nacimiento"]

    class Meta:
        verbose_name = _("Usuario")
        verbose_name_plural = _("Usuarios")
        ordering = ["apellido", "nombre"]

    def __str__(self):
        return f"{self.nombre} {self.apellido} <{self.email}>"

    def get_full_name(self):
        return f"{self.nombre} {self.apellido}".strip()

    def get_short_name(self):
        return self.nombre

    @property
    def edad(self):
        """
        Propiedad calculada en tiempo real. No se persiste en la base de datos.
        """
        hoy = timezone.now().date()
        return (
            hoy.year - self.fecha_nacimiento.year
            - ((hoy.month, hoy.day) < (self.fecha_nacimiento.month, self.fecha_nacimiento.day))
        )