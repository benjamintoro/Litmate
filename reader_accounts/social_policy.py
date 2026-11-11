"""Política común de visibilidad para perfiles, feed, medios y escrituras."""
from functools import wraps
import time

from django.conf import settings
from django.db import DatabaseError
from django.db.models import Exists, OuterRef, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache

from core.ai_concurrency import rate_increment

from .models import Follow, SocialComment, SocialPost, SocialProfile


def community(view):
    @never_cache
    @wraps(view)
    def guarded(request, *args, **kwargs):
        if not getattr(settings, 'LITMATE_COMMUNITY_ENABLED', False):
            raise Http404
        try:
            return view(request, *args, **kwargs)
        except DatabaseError:
            return HttpResponse('No pudimos acceder a la comunidad. Inténtalo más tarde.', status=503)
    return guarded


def action_limit(scope, limit):
    def decorate(view):
        @wraps(view)
        def guarded(request, *args, **kwargs):
            if request.method == 'POST':
                key = f'litmate-social:{scope}:{request.user.pk}:{int(time.time()) // 60}'
                try:
                    limited = rate_increment(key, 120) > limit
                except Exception:
                    return HttpResponse('No pudimos comprobar el límite. Inténtalo más tarde.', status=503)
                if limited:
                    return HttpResponse('Espera un minuto antes de repetir esta acción.', status=429,
                                        headers={'Retry-After': '60'})
            return view(request, *args, **kwargs)
        return guarded
    return decorate


def public_profiles():
    return SocialProfile.objects.filter(published=True, user__is_active=True)


def visible_posts(viewer):
    public_author = Q(author__published=True, author__user__is_active=True)
    public = public_author & Q(visibility=SocialPost.Visibility.PUBLIC)
    posts = SocialPost.objects.filter(moderated=False)
    if not viewer.is_authenticated:
        return posts.filter(public)
    followed = Follow.objects.filter(follower__user=viewer, follower__published=True, target=OuterRef('author_id'))
    return posts.alias(viewer_follows=Exists(followed)).filter(
        public | Q(author__user=viewer) |
        (public_author & Q(visibility=SocialPost.Visibility.FOLLOWERS, viewer_follows=True))
    )


def visible_post(viewer, pk):
    return get_object_or_404(visible_posts(viewer).select_related('author'), pk=pk)


def visible_comments(post, viewer):
    public = Q(author__published=True, author__user__is_active=True)
    if viewer.is_authenticated:
        public |= Q(author__user=viewer)
    return SocialComment.objects.filter(public, post=post, moderated=False).select_related('author')
