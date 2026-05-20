from functools import wraps
from django.core.exceptions import PermissionDenied


def rol_requerido(roles_permitidos):
    """
    Decorador para vistas de Django que restringe el acceso según el rol del usuario.
    
    Acepta una cadena única (ej: 'admin') o una lista/tupla (ej: ['admin', 'employee']).
    Si el usuario no está autenticado o no posee el rol requerido, lanza PermissionDenied (HTTP 403).
    """
    if isinstance(roles_permitidos, str):
        roles_permitidos = [roles_permitidos]

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if request.user.is_authenticated and request.user.rol in roles_permitidos:
                return view_func(request, *args, **kwargs)
            raise PermissionDenied
        return _wrapped_view
    return decorator
