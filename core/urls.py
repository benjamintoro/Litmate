from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Vistas generales
    path('', views.index, name='index'),
    path('about/', views.about, name='about'),
    path('post/', views.post, name='post'),
    path('contact/', views.contact, name='contact'),
    
    # Funcionalidades Principales
    path('libros/', views.buscar_libros, name='buscar_libros'),
    path('chat/', views.chatbot_page, name='chatbot_page'),
    path('chatbot_query/', views.chatbot_query, name='chatbot_query'),
    
    # Autenticación y Perfil (NUEVO)
    path('registro/', views.register, name='register'),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(template_name='registration/logout.html'), name='logout'),
    
    path('perfil/', views.perfil, name='perfil'),
    path('perfil/editar/', views.editar_perfil, name='editar_perfil'),
    
    # Favoritos (NUEVO)
    path('favoritos/agregar/', views.agregar_favorito, name='agregar_favorito'),
    path('favoritos/eliminar/<int:id>/', views.eliminar_favorito, name='eliminar_favorito'),
]