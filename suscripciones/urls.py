from django.urls import path
from . import views

app_name = 'suscripciones'

urlpatterns = [
    # Visualización y estado
    path('planes/', views.planes_view, name='planes'),
    path('mi-suscripcion/', views.mi_suscripcion_view, name='mi_suscripcion'),
    path('api/estado/', views.api_estado_suscripcion, name='api_estado'),
    
    # Pasarelas de Pago y Checkout
    path('checkout/<slug:plan_slug>/', views.checkout_view, name='checkout'),
    path('iniciar-pago/', views.iniciar_pago_gateway_view, name='iniciar_pago'),
    
    # Callbacks oficiales de cada pasarela
    path('webpay/commit/', views.webpay_commit_view, name='webpay_commit'),
    path('mercadopago/callback/', views.mercadopago_callback_view, name='mercadopago_callback'),
    path('paypal/callback/', views.paypal_callback_view, name='paypal_callback'),
    
    # Simulador Sandbox y Pantallas de Resultado
    path('simulador-gateway/', views.simulador_gateway_view, name='simulador_gateway'),
    path('pago-exitoso/<str:transaccion_id>/', views.pago_exitoso_view, name='pago_exitoso'),
    path('pago-cancelado/', views.pago_cancelado_view, name='pago_cancelado'),
    path('cancelar/', views.cancelar_suscripcion_view, name='cancelar_suscripcion'),
]
