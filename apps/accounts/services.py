"""
Capa de servicios para la app accounts.

Concentra la lógica de negocio de gestión de cuentas que va más allá
de un CRUD simple, manteniendo las vistas lo más delgadas posible.
"""
import logging

from django.db import transaction

from apps.turnos.services import cancelar_reservas_futuras_de_usuario
from .repository import UsuarioRepository

logger = logging.getLogger(__name__)


@transaction.atomic
def eliminar_cuenta(usuario) -> int:
    """
    Elimina permanentemente la cuenta de un usuario.

    Antes de borrarlo, cancela sus reservas futuras para promover la
    lista de espera de cada turno liberado. El resto de los datos
    asociados (reservas pasadas, grupos mensuales, pagos) se borra
    en cascada al eliminar el usuario.

    Devuelve la cantidad de turnos próximos que se cancelaron.
    """
    turnos_cancelados = cancelar_reservas_futuras_de_usuario(usuario)
    logger.warning(
        "Eliminando cuenta: %s (ID=%s) – %d turnos próximos cancelados",
        usuario.email, usuario.pk, turnos_cancelados,
    )
    UsuarioRepository.eliminar(usuario)
    return turnos_cancelados
