from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from . import views
from . import literary_ai_views
from django.views.decorators.csrf import ensure_csrf_cookie

urlpatterns = [
    # --- Vistas Generales ---
    path('', ensure_csrf_cookie(views.index), name='index'),
    path('about/', ensure_csrf_cookie(views.about), name='about'),
    path('post/', ensure_csrf_cookie(views.post), name='post'),
    path('contact/', ensure_csrf_cookie(views.contact), name='contact'),
    path('terminos-y-condiciones/', ensure_csrf_cookie(views.terminos_condiciones), name='terminos'),
    path('politica-de-privacidad/', ensure_csrf_cookie(views.politica_privacidad), name='privacidad'),
    path('politica-de-cookies/', ensure_csrf_cookie(views.politica_cookies), name='cookies'),
    
    # --- Funcionalidades Principales (IA y Búsqueda) ---
    path('libros/', views.buscar_libros, name='buscar_libros'),
    path('chat/', literary_ai_views.chatbot_page, name='chatbot_page'),
    path('chatbot/', literary_ai_views.chatbot_page, name='chatbot'),
    path('chatbot_query/', literary_ai_views.chatbot_query, name='chatbot_query'),
    path('chatbot_finalize/', literary_ai_views.chatbot_finalize, name='chatbot_finalize'),
    
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
    path('api/listas/crear/', views.crear_lista_api, name='crear_lista_api'),
    path('api/listas/eliminar/<int:id>/', views.eliminar_lista_api, name='eliminar_lista_api'),
    path('api/listas/obtener/', views.obtener_mis_listas_api, name='obtener_mis_listas_api'),
    path('api/listas/agregar-libro/', views.agregar_a_lista_api, name='agregar_a_lista_api'),
    path('api/listas/quitar-libro/<int:id>/', views.quitar_de_lista_api, name='quitar_de_lista_api'),
    path('api/historial/limpiar/', views.limpiar_historial_busqueda_api, name='limpiar_historial_busqueda_api'),
    path('api/perfil/preferencias-stats/', views.actualizar_preferencias_stats_api, name='actualizar_preferencias_stats_api'),

    # --- Comparador y Demo de Libros (Librerías / Afiliados) ---
    path('api/track-conversion/', views.track_conversion_click, name='track_conversion'),
    path('api/libro/precios/', views.api_precios_libro, name='api_precios_libro'),
    path('api/libro-demo/<str:book_id>/', views.detalle_libro_demo, name='detalle_libro_demo'),
    path('api/quick-search/', views.quick_search_api, name='quick_search_api'),

    # --- Social Login (Google & GitHub) ---
    path('auth/social/<str:provider>/', views.social_login_start, name='social_login'),
    path('auth/social/<str:provider>/callback/', views.social_login_callback, name='social_login_callback'),

    # --- Previsualización de Páginas de Error (404, 500, 403, 429) ---
    path('test-error/<str:code>/', views.test_error_view, name='test_error'),
    path('api/cuota-ia/', views.api_estado_cuota, name='api_estado_cuota'),
    path('api/miku-tts/', literary_ai_views.voice_query, name='api_miku_tts'),
]
