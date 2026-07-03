import logging

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from .decorators import rol_requerido
from .models import Roles
from .forms import (
    CambiarPasswordForm,
    LoginForm,
    RecuperarPasswordForm,
    RestablecerPasswordForm,
    UsuarioCreacionForm,
    UsuarioFiltroForm,
    UsuarioModificacionForm,
    UsuarioPerfilForm,
    EmpleadoCreacionForm,
)
from .repository import UsuarioRepository
from . import services

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
#  Autenticación
# ──────────────────────────────────────────────────────────────────

def vista_login(request):
    """Autenticación de usuario con el sistema de login de Django."""
    if request.user.is_authenticated:
        return redirect("home")

    form = LoginForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        usuario = form.get_user()
        login(request, usuario)
        logger.info("Login exitoso: %s (ID=%s)", usuario.email, usuario.pk)
        # Solo se redirige a `next` si apunta al mismo sitio: evita un open
        # redirect (?next=https://sitio-malicioso) que se podría usar para phishing.
        next_url = request.GET.get("next")
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return redirect("home")

    return render(request, "accounts/login.html", {"form": form})


class RecuperarPasswordView(auth_views.PasswordResetView):
    """Solicita el email y envía el enlace de recuperación si está registrado."""

    form_class = RecuperarPasswordForm
    template_name = "accounts/password_reset_form.html"
    email_template_name = "accounts/emails/password_reset_email.html"
    subject_template_name = "accounts/emails/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")

    def form_valid(self, form):
        response = super().form_valid(form)
        logger.info("Solicitud de recuperación de contraseña para: %s", form.cleaned_data["email"])
        return response


class RecuperarPasswordEnviadoView(auth_views.PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class RestablecerPasswordView(auth_views.PasswordResetConfirmView):
    """Formulario de nueva contraseña al abrir el enlace del correo."""

    form_class = RestablecerPasswordForm
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")

    def form_valid(self, form):
        response = super().form_valid(form)
        logger.info("Contraseña restablecida vía enlace para usuario ID=%s", self.user.pk)
        return response


class RestablecerPasswordCompletoView(auth_views.PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"


@login_required
def vista_logout(request):
    """Cierra la sesión del usuario actual."""
    logger.info("Logout: %s (ID=%s)", request.user.email, request.user.pk)
    logout(request)
    messages.info(request, _("Sesión cerrada correctamente."))
    return redirect("accounts:login")


# ──────────────────────────────────────────────────────────────────
#  CRUD de usuarios
# ──────────────────────────────────────────────────────────────────

@login_required
@rol_requerido("admin")
def lista_usuarios(request):
    """
    Lista usuarios con búsqueda y filtros.
    Acepta parámetros GET del formulario UsuarioFiltroForm.
    """
    form_filtro = UsuarioFiltroForm(request.GET or None)
    qs = UsuarioRepository.obtener_todos()

    if form_filtro.is_valid():
        data = form_filtro.cleaned_data
        qs = UsuarioRepository.buscar_con_filtros(
            nombre=data.get("nombre"),
            apellido=data.get("apellido"),
            email=data.get("email"),
            nro_documento=data.get("nro_documento"),
            fecha_nacimiento_desde=data.get("fecha_nacimiento_desde"),
            fecha_nacimiento_hasta=data.get("fecha_nacimiento_hasta"),
            is_active=data.get("is_active"),
        )

    paginator = Paginator(qs, per_page=20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "accounts/lista.html", {
        "page_obj": page_obj,
        "form_filtro": form_filtro,
        "total": qs.count(),
    })


@login_required
@rol_requerido("admin")
def busqueda_global(request):
    """Búsqueda rápida por término libre sobre nombre, apellido, email y documento."""
    termino = request.GET.get("q", "").strip()
    qs = UsuarioRepository.buscar_con_filtros(busqueda_global=termino) if termino else []

    return render(request, "accounts/busqueda_global.html", {
        "resultados": qs,
        "termino": termino,
    })


def registro_usuario(request):
    """Registro de un nuevo usuario. Accesible sin autenticación."""
    from apps.pagos.forms import TarjetaAltaForm
    from apps.pagos import tarjetas as tarjetas_svc

    form = UsuarioCreacionForm(request.POST or None)
    tarjeta_form = TarjetaAltaForm(request.POST or None)

    if request.method == "POST":
        form_valid = form.is_valid()
        tarjeta_valid = tarjeta_form.is_valid()
        if form_valid and tarjeta_valid:
            try:
                usuario = form.save()
                tarjetas_svc.guardar_tarjeta(
                    usuario,
                    tarjeta_form.cleaned_data["numero_tarjeta"],
                    tarjeta_form.cleaned_data["titular"],
                    tarjeta_form.cleaned_data["vencimiento"],
                )
                logger.info("Nuevo usuario registrado: %s (ID=%s)", usuario.email, usuario.pk)
                messages.success(request, _("Cuenta creada exitosamente. Podés iniciar sesión."))
                return redirect("accounts:login")
            except ValidationError as exc:
                messages.error(request, exc.message)
            except Exception as exc:
                logger.error("Error al registrar usuario: %s", exc)
                messages.error(request, _("Ocurrió un error al crear la cuenta. Intente nuevamente."))

    return render(request, "accounts/registro.html", {
        "form": form,
        "tarjeta_form": tarjeta_form,
    })


@login_required
def detalle_usuario(request, pk):
    """Detalle de un usuario. Solo el administrador o el propio dueño."""
    usuario = get_object_or_404(UsuarioRepository.obtener_todos(), pk=pk)
    if request.user.rol != Roles.ADMIN and request.user.pk != usuario.pk:
        messages.error(request, _("No tenés permiso para ver esta cuenta."))
        return redirect("home")
    return render(request, "accounts/detalle.html", {"usuario": usuario})


@login_required
def editar_usuario(request, pk):
    """Edición de datos de un usuario (sin contraseña)."""
    from apps.turnos import services as turnos_services

    usuario = get_object_or_404(UsuarioRepository.obtener_todos(), pk=pk)

    # Solo el administrador o el propio usuario pueden editar la cuenta.
    if request.user.rol != Roles.ADMIN and request.user.pk != usuario.pk:
        messages.error(request, _("No tenés permiso para acceder a esta cuenta."))
        return redirect("home")

    es_propio_perfil = request.user.pk == usuario.pk
    if es_propio_perfil:
        turnos_services.verificar_plazos_abonos_mensuales(usuario)

    FormClass = UsuarioPerfilForm if es_propio_perfil else UsuarioModificacionForm
    form = FormClass(request.POST or None, instance=usuario)
    if request.method == "POST" and form.is_valid():
        form.save()
        logger.info("Usuario editado: %s (ID=%s) por %s", usuario.email, usuario.pk, request.user.email)
        messages.success(request, _("Datos actualizados correctamente."))
        if es_propio_perfil:
            return redirect("accounts:editar", pk=pk)
        return redirect("accounts:detalle", pk=pk)

    creditos_resumen = None
    tarjeta_guardada = None
    aviso_penalidad = None
    suspensiones_abonado = None
    if es_propio_perfil and usuario.rol == Roles.USER:
        from apps.creditos.services import resumen_creditos_usuario
        from apps.pagos import tarjetas as tarjetas_svc
        from apps.turnos import suspensiones as turnos_suspensiones
        from apps.turnos.penalidad_cancelaciones import aviso_penalidad_en_cuenta

        creditos_resumen = resumen_creditos_usuario(usuario)
        tarjeta_guardada = tarjetas_svc.obtener_tarjeta_guardada(usuario)
        aviso_penalidad = aviso_penalidad_en_cuenta(usuario)
        suspensiones_abonado = turnos_suspensiones.suspensiones_activas_de(usuario)

    return render(request, "accounts/editar.html", {
        "form": form,
        "usuario": usuario,
        "es_propio_perfil": es_propio_perfil,
        "creditos_resumen": creditos_resumen,
        "tarjeta_guardada": tarjeta_guardada,
        "aviso_penalidad": aviso_penalidad,
        "suspensiones_abonado": suspensiones_abonado,
        "is_panel": not es_propio_perfil,
    })


@login_required
def gestionar_tarjeta(request):
    """Cambiar o registrar la tarjeta guardada del usuario."""
    from apps.pagos.forms import TarjetaAltaForm
    from apps.pagos import tarjetas as tarjetas_svc

    tarjeta_guardada = tarjetas_svc.obtener_tarjeta_guardada(request.user)
    form = TarjetaAltaForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        if tarjeta_guardada:
            tarjetas_svc.eliminar_tarjeta_guardada(request.user)
        try:
            tarjetas_svc.guardar_tarjeta(
                request.user,
                form.cleaned_data["numero_tarjeta"],
                form.cleaned_data["titular"],
                form.cleaned_data["vencimiento"],
            )
            messages.success(request, _("Tarjeta guardada correctamente."))
            return redirect("accounts:editar", pk=request.user.pk)
        except ValidationError as exc:
            messages.error(request, exc.message)

    return render(request, "accounts/gestionar_tarjeta.html", {
        "form": form,
        "tarjeta_guardada": tarjeta_guardada,
    })


@login_required
def cambiar_password(request):
    """Permite al usuario autenticado cambiar su propia contraseña."""
    form = CambiarPasswordForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        usuario = form.save()
        # Mantiene la sesión activa tras el cambio de contraseña
        update_session_auth_hash(request, usuario)
        logger.info("Contraseña cambiada para usuario ID=%s", usuario.pk)
        messages.success(request, _("Contraseña actualizada correctamente."))
        return redirect("accounts:editar", pk=usuario.pk)

    return render(request, "accounts/cambiar_password.html", {"form": form})


@login_required
def eliminar_cuenta(request):
    """
    Permite al usuario autenticado eliminar permanentemente su cuenta.
    GET muestra la página de confirmación; POST ejecuta el borrado.
    Los administradores no pueden eliminar su propia cuenta.
    """
    usuario = request.user

    # Las cuentas de administrador no pueden eliminarse desde esta sección.
    if usuario.rol == Roles.ADMIN:
        messages.error(
            request,
            _("Las cuentas de administrador no pueden eliminarse desde esta sección."),
        )
        return redirect("accounts:editar", pk=usuario.pk)

    if request.method == "POST":
        email = usuario.email
        pk = usuario.pk
        services.eliminar_cuenta(usuario)
        logout(request)
        logger.warning("Cuenta eliminada: %s (ID=%s)", email, pk)
        messages.success(request, _("Tu cuenta fue eliminada."))
        return redirect("home")

    return render(request, "accounts/eliminar_cuenta.html")


@login_required
@rol_requerido(["admin", "employee"])
def eliminar_usuario_por_dni(request):
    """
    Sección para eliminar un usuario buscándolo por DNI.

    GET             → formulario de búsqueda (vacío).
    POST buscar     → muestra el usuario encontrado con la confirmación (o error si no procede).
    POST confirmar  → ejecuta el borrado permanente.

    Reglas:
    - Nadie puede eliminarse a sí mismo.
    - Empleados solo pueden eliminar clientes (rol USER).
    - Admins pueden eliminar clientes y empleados, pero no a otro admin.
    """
    operador = request.user
    usuario = None
    error = None
    buscado = False

    accion = request.POST.get("accion")

    if request.method == "POST" and accion == "confirmar":
        pk = request.POST.get("usuario_pk")
        usuario = get_object_or_404(UsuarioRepository.obtener_todos(), pk=pk)
        error = _verificar_eliminacion(operador, usuario)
        if error:
            messages.error(request, error)
        else:
            email = usuario.email
            uid = usuario.pk
            services.eliminar_cuenta(usuario)
            logger.warning(
                "Cuenta eliminada por %s: %s (ID=%s)",
                operador.email, email, uid,
            )
            messages.success(request, _("Se ha eliminado la cuenta."))
            return redirect("accounts:eliminar_por_dni")
        usuario = None

    elif request.method == "POST" and accion == "buscar":
        buscado = True
        dni = request.POST.get("nro_documento", "").strip()
        if dni:
            usuario = UsuarioRepository.obtener_por_documento(dni)
            if usuario is None:
                error = _("No se encontró ningún usuario con ese DNI.")
            else:
                error = _verificar_eliminacion(operador, usuario)

    return render(request, "accounts/eliminar_por_dni.html", {
        "usuario": usuario,
        "error": error,
        "buscado": buscado,
    })


def _tiene_reservas_activas(usuario) -> bool:
    """Reserva activa = tiene el cupo asegurado (confirmada o invitada). Estar en
    lista de espera no cuenta, ya que ahí no se llegó a ocupar ningún cupo."""
    from apps.turnos.models import Reserva

    return Reserva.objects.filter(
        usuario=usuario,
        estado__in=[Reserva.Estado.CONFIRMADA, Reserva.Estado.INVITADO],
    ).exists()


def _tiene_pagos_pendientes(usuario) -> bool:
    """Deuda pendiente por una suspensión activa (global o por deporte)."""
    from apps.turnos.models import SuspensionAbonado

    if usuario.suspendido:
        return True
    return SuspensionAbonado.objects.filter(usuario=usuario, activa=True).exists()


def _verificar_eliminacion(operador, usuario):
    """Devuelve un mensaje de error si la eliminación no está permitida, o None si procede."""
    if usuario.pk == operador.pk:
        return _("No podés eliminar tu propia cuenta.")
    if usuario.rol == Roles.ADMIN:
        return _("No se pueden eliminar cuentas de administrador.")
    if operador.rol == Roles.EMPLOYEE and usuario.rol != Roles.USER:
        return _("Los empleados solo pueden eliminar cuentas de clientes.")
    if _tiene_reservas_activas(usuario):
        return _("No se puede eliminar: el usuario tiene reservas activas (con cupo asegurado).")
    if _tiene_pagos_pendientes(usuario):
        return _("No se puede eliminar: el usuario tiene pagos pendientes (deuda de suspensión sin saldar).")
    return None


@rol_requerido("admin")
@require_POST
def desactivar_usuario(request, pk):
    """Desactivación (soft delete) de un usuario. Solo administradores."""
    usuario = get_object_or_404(UsuarioRepository.obtener_todos(), pk=pk)
    UsuarioRepository.desactivar(usuario)
    logger.warning("Usuario desactivado: %s (ID=%s) por %s", usuario.email, usuario.pk, request.user.email)
    messages.warning(request, _("Usuario %s desactivado.") % usuario.get_full_name())
    return redirect("accounts:lista")


@rol_requerido("admin")
@require_POST
def activar_usuario(request, pk):
    """Reactiva un usuario desactivado. Solo administradores."""
    usuario = get_object_or_404(UsuarioRepository.obtener_todos(), pk=pk)
    UsuarioRepository.activar(usuario)
    logger.info("Usuario activado: %s (ID=%s) por %s", usuario.email, usuario.pk, request.user.email)
    messages.success(request, _("Usuario %s activado.") % usuario.get_full_name())
    return redirect("accounts:lista")


@login_required
@rol_requerido(["admin", "employee"])
def panel_control(request):
    """Panel de control para administradores y empleados."""
    from datetime import date

    from apps.turnos.models import Turno

    hay_clases_pasadas = Turno.objects.filter(fecha__lt=date.today()).exists()
    return render(request, "accounts/panel.html", {
        "hay_clases_pasadas": hay_clases_pasadas,
    })


@login_required
@rol_requerido("admin")
def crear_empleado(request):
    """Permite al administrador registrar una nueva cuenta de empleado."""
    form = EmpleadoCreacionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            empleado = form.save()
            logger.info("Nuevo empleado registrado: %s (ID=%s) por admin %s", empleado.email, empleado.pk, request.user.email)
            messages.success(request, _("Cuenta de empleado creada exitosamente."))
            return redirect("panel_control")
        except Exception as exc:
            logger.error("Error al registrar empleado: %s", exc)
            messages.error(request, _("Ocurrió un error al crear la cuenta de empleado. Intente nuevamente."))
    
    return render(request, "accounts/crear_empleado.html", {"form": form})
