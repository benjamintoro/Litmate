"""Entrega acotada del audio generado; nunca publica un directorio privado."""
from django.http import FileResponse, Http404
from django.conf import settings


def serve_cached_audio(request, name):
    root=settings.MEDIA_ROOT.resolve()
    path=root/'tts_cache'/name
    if (path.parent.is_symlink() or path.is_symlink() or not path.is_file()
            or not path.resolve().is_relative_to(root) or path.stat().st_size>5*1024*1024):
        raise Http404
    response=FileResponse(path.open('rb'),content_type='audio/mpeg')
    response['Cache-Control']='private, max-age=300'
    return response
