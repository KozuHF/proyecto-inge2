import logging

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from .decorators import rol_requerido
from .forms import (
    CambiarPasswordForm,
    LoginForm,
    RecuperarPasswordForm,
    RestablecerPasswordForm,
    UsuarioCreacionForm,
    UsuarioFiltroForm,
    UsuarioModificacionForm,
    UsuarioPerfilForm,
)
from .repository import UsuarioRepository

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
        next_url = request.GET.get("next")
        if next_url:
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

@rol_requerido(["admin", "employee"])
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


@rol_requerido(["admin", "employee"])
def busqueda_global(request):
    """Búsqueda rápida por término libre sobre nombre, apellido, email y documento."""
    termino = request.GET.get("q", "").strip()
    qs = UsuarioRepository.buscar_con_filtros(busqueda_global=termino) if termino else []

    return render(request, "accounts/busqueda.html", {
        "resultados": qs,
        "termino": termino,
    })


def registro_usuario(request):
    """Registro de un nuevo usuario. Accesible sin autenticación."""
    form = UsuarioCreacionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            usuario = form.save()
            logger.info("Nuevo usuario registrado: %s (ID=%s)", usuario.email, usuario.pk)
            messages.success(request, _("Cuenta creada exitosamente. Podés iniciar sesión."))
            return redirect("accounts:login")
        except Exception as exc:
            logger.error("Error al registrar usuario: %s", exc)
            messages.error(request, _("Ocurrió un error al crear la cuenta. Intente nuevamente."))

    return render(request, "accounts/registro.html", {"form": form})


@login_required
def detalle_usuario(request, pk):
    """Detalle de un usuario específico."""
    usuario = get_object_or_404(UsuarioRepository.obtener_todos(), pk=pk)
    return render(request, "accounts/detalle.html", {"usuario": usuario})


@login_required
def editar_usuario(request, pk):
    """Edición de datos de un usuario (sin contraseña)."""
    from apps.turnos import services as turnos_services

    usuario = get_object_or_404(UsuarioRepository.obtener_todos(), pk=pk)

    # Solo staff o el propio usuario pueden editar
    if not request.user.is_staff and request.user.pk != usuario.pk:
        messages.error(request, _("No tenés permiso para editar este usuario."))
        return redirect("accounts:detalle", pk=pk)

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
    if es_propio_perfil:
        from apps.creditos.services import resumen_creditos_usuario

        creditos_resumen = resumen_creditos_usuario(usuario)

    return render(request, "accounts/editar.html", {
        "form": form,
        "usuario": usuario,
        "es_propio_perfil": es_propio_perfil,
        "creditos_resumen": creditos_resumen,
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
