"""Conserva los nombres de rutas para las plantillas; el gateway restringe acceso."""
from django.http import FileResponse, Http404
from django.conf import settings
from django.urls import path, re_path, include
from core import demo_frontend


def demo_audio(request, name):
    root = settings.MEDIA_ROOT.resolve()
    path = root / 'tts_cache' / name
    if (path.parent.is_symlink() or path.is_symlink() or not path.is_file()
            or not path.resolve().is_relative_to(root) or path.stat().st_size > 5 * 1024 * 1024):
        raise Http404
    response = FileResponse(path.open('rb'), content_type='audio/mpeg')
    response['Cache-Control'] = 'private, max-age=300'
    return response


urlpatterns = [
    *[path(route.lstrip('/'), demo_frontend.form_preview)
      for route in demo_frontend.FORM_PAGES],
    path('suscripciones/checkout/<slug:plan_slug>/', demo_frontend.payment_preview),
    path('auth/social/<str:provider>/', demo_frontend.social_preview),
    path('logout/', demo_frontend.logout_preview),
    path('api/track-conversion/', demo_frontend.tracking_disabled),
    re_path(r'^media/tts_cache/(?P<name>miku_[0-9a-f]{64}\.mp3)$', demo_audio),
    path('', include('litmate_project.urls')),
]
