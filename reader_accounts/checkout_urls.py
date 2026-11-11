from django.urls import path
from . import checkout_views as checkout

urlpatterns = [
    path('suscripciones/checkout/<slug:plan_slug>/', checkout.checkout, name='sim_checkout'),
    path('suscripciones/checkout/<slug:plan_slug>/metodo/', checkout.methods, name='sim_methods'),
    path('suscripciones/pedido/<uuid:order_id>/', checkout.order, name='sim_order'),
    path('suscripciones/pedido/<uuid:order_id>/confirmar/', checkout.confirm, name='sim_confirm'),
    path('suscripciones/pedido/<uuid:order_id>/cancelar/', checkout.cancel_order, name='sim_cancel_order'),
    path('suscripciones/comprobante/<uuid:order_id>/', checkout.receipt, name='sim_receipt'),
    path('suscripciones/mi-suscripcion/', checkout.subscription, name='sim_subscription'),
    path('suscripciones/simulada/cancelar/', checkout.cancel_subscription, name='sim_cancel_subscription'),
    path('suscripciones/simulada/gratuito/', checkout.switch_free, name='sim_switch_free'),
    path('cuenta/pagos/', checkout.history, name='sim_history'),
]
