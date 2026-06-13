from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _


def rol_requerido(roles_permitidos):
    """
    Decorador que restringe el acceso a una vista según el rol del usuario.

    Acepta una cadena ('admin') o una lista/tupla (['admin', 'employee']).

    - Si el usuario no está autenticado: lo manda al login (con `next`).
    - Si está autenticado pero no tiene el rol: lo redirige al inicio con un
      mensaje, en vez de mostrar un error 403.
    """
    if isinstance(roles_permitidos, str):
        roles_permitidos = [roles_permitidos]

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if getattr(request.user, "rol", None) in roles_permitidos:
                return view_func(request, *args, **kwargs)
            messages.error(request, _("No tenés permiso para acceder a esa sección."))
            return redirect("home")
        return _wrapped_view
    return decorator
