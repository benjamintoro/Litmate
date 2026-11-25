"""Acceso público propio; no importa ni publica el URLconf de demostración."""
from django.urls import path, include, re_path
from reader_accounts.account_urls import urlpatterns as account_patterns
from reader_accounts import production_views as production
from reader_accounts.production_admin import site as operations

urlpatterns=[
    path('operacion/', operations.urls),
    *account_patterns,
    path('_health/live/',production.live),path('_health/ready/',production.ready),
    path('contact/',production.contact),
    path('api/track-conversion/',production.tracking_disabled),
    path('api/miku-tts/',production.voice),
    re_path(r'^media/tts_cache/(?P<name>miku_[0-9a-f]{64}\.mp3)$',production.own_audio),
    path('auth/social/<str:provider>/',production.unavailable),
    path('suscripciones/checkout/<slug:plan_slug>/',production.unavailable),
    path('',include('core.urls')),path('suscripciones/',include('suscripciones.urls')),
]
handler400='core.views.error_400_view'
handler403='core.views.error_403_view'
handler404='core.views.error_404_view'
handler500='core.views.error_500_view'
