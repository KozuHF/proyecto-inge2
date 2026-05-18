from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    # Autenticación
    path("login/",   views.vista_login,   name="login"),
    path("logout/",  views.vista_logout,  name="logout"),
    path("registro/", views.registro_usuario, name="registro"),

    # CRUD
    path("",                          views.lista_usuarios,    name="lista"),
    path("buscar/",                   views.busqueda_global,   name="busqueda"),
    path("<int:pk>/",                 views.detalle_usuario,   name="detalle"),
    path("<int:pk>/editar/",          views.editar_usuario,    name="editar"),
    path("<int:pk>/desactivar/",      views.desactivar_usuario, name="desactivar"),
    path("<int:pk>/activar/",         views.activar_usuario,   name="activar"),
    path("cambiar-password/",         views.cambiar_password,  name="cambiar_password"),
]