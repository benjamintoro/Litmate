from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # --- Vistas Generales ---
    path('', views.index, name='index'),
    path('about/', views.about, name='about'),
    path('post/', views.post, name='post'),
    path('contact/', views.contact, name='contact'),
    path('terminos-y-condiciones/', views.terminos_condiciones, name='terminos'),
    path('politica-de-privacidad/', views.politica_privacidad, name='privacidad'),
    path('politica-de-cookies/', views.politica_cookies, name='cookies'),
    
    # --- Funcionalidades Principales (IA y Búsqueda) ---
    path('libros/', views.buscar_libros, name='buscar_libros'),
    path('chat/', views.chatbot_page, name='chatbot_page'),
    path('chatbot/', views.chatbot_page, name='chatbot'),
    path('chatbot_query/', views.chatbot_query, name='chatbot_query'),
    
    # --- Autenticación y Registro ---
    path('registro/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # --- Recuperación de Contraseña por Correo ---
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='registration/password_reset_form.html',
        email_template_name='registration/password_reset_email.html',
        subject_template_name='registration/password_reset_subject.txt',
        success_url=reverse_lazy('password_reset_done')
    ), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='registration/password_reset_done.html'
    ), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='registration/password_reset_confirm.html',
        success_url=reverse_lazy('password_reset_complete')
    ), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='registration/password_reset_complete.html'
    ), name='password_reset_complete'),
    
    # --- Gestión de Perfil ---
    path('perfil/', views.perfil, name='perfil'),
    path('perfil/editar/', views.editar_perfil, name='editar_perfil'),
    
    # --- Favoritos y Estados de Lectura ---
    path('favoritos/agregar/', views.agregar_favorito, name='agregar_favorito'),
    path('favoritos/eliminar/<int:id>/', views.eliminar_favorito, name='eliminar_favorito'),
    path('api/estado-lectura/', views.actualizar_estado_lectura, name='actualizar_estado_lectura'),

    # --- Comparador y Demo de Libros (Librerías / Afiliados) ---
    path('api/track-conversion/', views.track_conversion_click, name='track_conversion'),
    path('api/libro-demo/<str:book_id>/', views.detalle_libro_demo, name='detalle_libro_demo'),
    path('api/quick-search/', views.quick_search_api, name='quick_search_api'),

    # --- Social Login (Google & GitHub) ---
    path('auth/social/<str:provider>/', views.social_login_start, name='social_login'),
    path('auth/social/<str:provider>/callback/', views.social_login_callback, name='social_login_callback'),

    # --- Previsualización de Páginas de Error (404, 500, 403, 429) ---
    path('test-error/<str:code>/', views.test_error_view, name='test_error'),
]