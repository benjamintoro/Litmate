"""Páginas de producción sin previsualizaciones de la demo ni pagos aparentes."""
import json
import re
from django.conf import settings
from django.db import connections, DatabaseError
from django.http import JsonResponse, Http404, HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_safe
from core.public_audio import serve_cached_audio
from .contact import contact


@require_safe
@never_cache
def live(request):
    return JsonResponse({'status':'ok'})


@require_safe
@never_cache
def ready(request):
    try:
        with connections['accounts'].cursor() as cursor:
            cursor.execute('SELECT 1 FROM auth_user LIMIT 1')
    except DatabaseError:
        return JsonResponse({'status':'unavailable'},status=503)
    return JsonResponse({'status':'ok'})


def unavailable(request, **kwargs):
    raise Http404




@require_POST
def tracking_disabled(request):
    return JsonResponse({'status':'ok','tracked':False})


@require_POST
def voice(request):
    from core.literary_ai_views import voice_query
    response=voice_query(request)
    if response.status_code==200:
        data=json.loads(response.content)
        url=data.get('audio_url') or ''
        if re.fullmatch(r'/media/tts_cache/miku_[a-f0-9]{64}\.mp3',url):
            request.session['production_audio']=(request.session.get('production_audio',[])+[url])[-20:]
    return response


@require_safe
def own_audio(request,name):
    if '/media/tts_cache/'+name not in request.session.get('production_audio',[]):
        raise Http404
    return serve_cached_audio(request,name)
