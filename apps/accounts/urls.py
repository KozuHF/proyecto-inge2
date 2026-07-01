from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    # Autenticación
    path("login/",   views.vista_login,   name="login"),
    path("logout/",  views.vista_logout,  name="logout"),
    path("registro/", views.registro_usuario, name="registro"),
    path(
        "olvide-password/",
        views.RecuperarPasswordView.as_view(),
        name="password_reset",
    ),
    path(
        "olvide-password/enviado/",
        views.RecuperarPasswordEnviadoView.as_view(),
        name="password_reset_done",
    ),
    path(
        "restablecer-password/<uidb64>/<token>/",
        views.RestablecerPasswordView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "restablecer-password/completado/",
        views.RestablecerPasswordCompletoView.as_view(),
        name="password_reset_complete",
    ),

    # CRUD
    path("",                          views.lista_usuarios,    name="lista"),
    path("buscar/",                   views.busqueda_global,   name="busqueda"),
    path("<int:pk>/",                 views.detalle_usuario,   name="detalle"),
    path("<int:pk>/editar/",          views.editar_usuario,    name="editar"),
    path("eliminar-usuario/",          views.eliminar_usuario_por_dni, name="eliminar_por_dni"),
    path("<int:pk>/desactivar/",      views.desactivar_usuario, name="desactivar"),
    path("<int:pk>/activar/",         views.activar_usuario,   name="activar"),
    path("cambiar-password/",         views.cambiar_password,  name="cambiar_password"),
    path("mi-tarjeta/",               views.gestionar_tarjeta, name="gestionar_tarjeta"),
    path("eliminar-cuenta/",          views.eliminar_cuenta,   name="eliminar_cuenta"),
    path("crear-empleado/",           views.crear_empleado,    name="crear_empleado"),
]