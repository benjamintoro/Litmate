from django.urls import path, include, re_path
from . import views, chat

urlpatterns = [
    path('registro/', views.register), path('login/', views.login), path('logout/', views.logout),
    path('suscripciones/planes/', views.plans),
    path('cuenta/activar-gratis/', views.activate_free, name='reader_activate_free'),
    path('perfil/', views.account), path('suscripciones/mi-suscripcion/', views.account),
    path('cuenta/conversaciones/<int:pk>/', views.conversation, name='reader_conversation'),
    path('api/cuota-ia/', views.quota),
    path('chat/', views.chat_page), path('chatbot/', views.chat_page),
    path('chatbot_query/', chat.query), path('chatbot_finalize/', chat.finalize),
    re_path(r'^suscripciones/(iniciar-pago|webpay/commit|mercadopago/callback|paypal/callback|simulador-gateway)/$',
            lambda request, *_: views.payment_disabled(request)),
    path('', include('litmate_project.demo_urls')),
]
