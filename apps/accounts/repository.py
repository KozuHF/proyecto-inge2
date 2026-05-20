"""
Capa de repositorio (Repository Pattern).

Encapsula toda la lógica de acceso a datos del modelo Usuario,
manteniendo las vistas (controllers) limpias y desacopladas del ORM.
"""
from django.db.models import Q
from django.utils import timezone

from .models import Usuario


class UsuarioRepository:
    """
    Repositorio para operaciones CRUD y búsqueda de usuarios.
    Todas las consultas pasan por aquí para centralizar el acceso a datos.
    """

    @staticmethod
    def obtener_todos():
        """Retorna todos los usuarios ordenados por apellido y nombre."""
        return Usuario.objects.all()

    @staticmethod
    def obtener_por_id(usuario_id: int):
        """Retorna un usuario por su ID o None si no existe."""
        try:
            return Usuario.objects.get(pk=usuario_id)
        except Usuario.DoesNotExist:
            return None

    @staticmethod
    def obtener_por_email(email: str):
        """Retorna un usuario por su email o None si no existe."""
        try:
            return Usuario.objects.get(email=email)
        except Usuario.DoesNotExist:
            return None

    @staticmethod
    def obtener_por_documento(nro_documento: str):
        """Retorna un usuario por su número de documento."""
        try:
            return Usuario.objects.get(nro_documento=nro_documento)
        except Usuario.DoesNotExist:
            return None

    @staticmethod
    def buscar_con_filtros(
        nombre: str = None,
        apellido: str = None,
        email: str = None,
        nro_documento: str = None,
        fecha_nacimiento_desde=None,
        fecha_nacimiento_hasta=None,
        is_active: bool = None,
        busqueda_global: str = None,
    ):
        """
        Búsqueda flexible con múltiples filtros opcionales.

        Parámetros:
            nombre              -- Búsqueda parcial (icontains) en nombre.
            apellido            -- Búsqueda parcial en apellido.
            email               -- Búsqueda parcial en email.
            nro_documento       -- Búsqueda parcial en nro_documento.
            fecha_nacimiento_desde -- Rango de fecha de nacimiento (desde).
            fecha_nacimiento_hasta -- Rango de fecha de nacimiento (hasta).
            is_active           -- Filtrar por estado activo/inactivo.
            busqueda_global     -- Término que busca en nombre, apellido,
                                   email y nro_documento simultáneamente.

        Retorna:
            QuerySet filtrado y ordenado.
        """
        qs = Usuario.objects.all()

        # Búsqueda global (OR entre campos principales)
        if busqueda_global:
            qs = qs.filter(
                Q(nombre__icontains=busqueda_global)
                | Q(apellido__icontains=busqueda_global)
                | Q(email__icontains=busqueda_global)
                | Q(nro_documento__icontains=busqueda_global)
            )

        # Filtros individuales (AND entre sí)
        if nombre:
            qs = qs.filter(nombre__icontains=nombre)
        if apellido:
            qs = qs.filter(apellido__icontains=apellido)
        if email:
            qs = qs.filter(email__icontains=email)
        if nro_documento:
            qs = qs.filter(nro_documento__icontains=nro_documento)
        if fecha_nacimiento_desde:
            qs = qs.filter(fecha_nacimiento__gte=fecha_nacimiento_desde)
        if fecha_nacimiento_hasta:
            qs = qs.filter(fecha_nacimiento__lte=fecha_nacimiento_hasta)
        if is_active is not None:
            qs = qs.filter(is_active=is_active)

        return qs.distinct()

    @staticmethod
    def crear(
        email: str,
        nombre: str,
        apellido: str,
        nro_documento: str,
        fecha_nacimiento,
        password: str,
        **extra_fields,
    ):
        """
        Crea y persiste un nuevo usuario.
        La validación de mayoría de edad y el hasheo de contraseña
        se realizan en el Manager.
        """
        return Usuario.objects.create_user(
            email=email,
            nombre=nombre,
            apellido=apellido,
            nro_documento=nro_documento,
            fecha_nacimiento=fecha_nacimiento,
            password=password,
            **extra_fields,
        )

    @staticmethod
    def actualizar(usuario: Usuario, **campos):
        """
        Actualiza campos de un usuario existente.
        Si se incluye 'password', se hashea correctamente.
        """
        password = campos.pop("password", None)
        for campo, valor in campos.items():
            setattr(usuario, campo, valor)
        if password:
            usuario.set_password(password)
        usuario.save()
        return usuario

    @staticmethod
    def desactivar(usuario: Usuario):
        """Desactiva un usuario (soft delete) en lugar de eliminarlo."""
        usuario.is_active = False
        usuario.save(update_fields=["is_active"])
        return usuario

    @staticmethod
    def activar(usuario: Usuario):
        """Reactiva un usuario desactivado."""
        usuario.is_active = True
        usuario.save(update_fields=["is_active"])
        return usuario

    @staticmethod
    def eliminar(usuario: Usuario):
        """Elimina permanentemente un usuario de la base de datos."""
        usuario.delete()