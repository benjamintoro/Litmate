"""Publicaciones literarias, feed e interacciones con permisos compartidos."""
from types import SimpleNamespace
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef, Q
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from core.models import Libro

from .library import present_book
from .models import Follow, PostLike, SocialComment, SocialPost, SocialProfile, SocialReport
from .social_forms import CommentForm, PostForm, ReportForm
from .social_policy import action_limit, community, visible_comments, visible_post, visible_posts
from .social_profiles import profile_for


def catalogue_book(book):
    card = present_book(SimpleNamespace(titulo=book.titulo, autores=book.autor.nombre,
        google_id=book.google_book_id or f'db_{book.pk}', imagen_url=book.portada_url))
    card.catalogue_id = book.pk
    return card


def posts_page(request, queryset, number, size=10):
    comment_visibility = Q(comments__author__published=True, comments__author__user__is_active=True)
    if request.user.is_authenticated:
        comment_visibility |= Q(comments__author__user=request.user)
    queryset = queryset.select_related('author').annotate(
        like_count=Count('likes', distinct=True),
        comment_count=Count('comments', filter=Q(comments__moderated=False) & comment_visibility, distinct=True),
    )
    if request.user.is_authenticated:
        queryset = queryset.annotate(viewer_likes=Exists(
            PostLike.objects.filter(author__user=request.user, post_id=OuterRef('pk'))))
    page = Paginator(queryset.order_by('-created_at', '-pk'), size).get_page(number)
    page.object_list = list(page.object_list)
    ids = {post.catalogue_id for post in page if post.catalogue_id}
    books = Libro.objects.select_related('autor').in_bulk(ids) if ids else {}
    for post in page:
        post.linked_book = catalogue_book(books[post.catalogue_id]) if post.catalogue_id in books else None
        post.can_link_author = post.author.published
    return page


def owned_post(request, pk):
    return get_object_or_404(SocialPost.objects.select_related('author'), pk=pk, author__user=request.user)


@community
@require_safe
def feed(request):
    scope = 'seguidos' if request.GET.get('ver') == 'seguidos' and request.user.is_authenticated else 'recientes'
    posts = visible_posts(request.user).filter(author__published=True, author__user__is_active=True)
    if scope == 'seguidos':
        following = Follow.objects.filter(follower__user=request.user, follower__published=True).values('target_id')
        posts = posts.filter(author_id__in=following).exclude(visibility=SocialPost.Visibility.PRIVATE)
    else:
        posts = posts.filter(visibility=SocialPost.Visibility.PUBLIC)
    return render(request, 'accounts/social/feed.html', {
        'feed_scope': scope, 'posts': posts_page(request, posts, request.GET.get('page')),
    })


@community
@require_safe
def book(request, pk):
    if not 0 < pk <= 2**63-1:
        raise Http404
    found = get_object_or_404(Libro.objects.select_related('autor'), pk=pk)
    return render(request, 'accounts/social/book.html', {'book': catalogue_book(found), 'synopsis': found.sinopsis})


def search_books(term):
    if not 2 <= len(term) <= 80:
        return []
    return Libro.objects.select_related('autor').filter(
        Q(titulo__icontains=term) | Q(autor__nombre__icontains=term) |
        Q(isbn_10=term) | Q(isbn_13=term),
    ).order_by('titulo', 'pk')[:12]


@community
@login_required
@action_limit('post', 12)
@require_http_methods(['GET', 'HEAD', 'POST'])
def post_editor(request, pk=None):
    entry = owned_post(request, pk) if pk else None
    profile = entry.author if entry else (
        SocialProfile.objects.filter(user=request.user).first() or SocialProfile(user=request.user))
    initial = {'submission_id': uuid4(), 'allow_comments': True} if entry is None else {}
    if request.method != 'POST':
        selected = request.GET.get('libro', '')
        if selected.isascii() and selected.isdecimal() and len(selected) <= 18:
            initial['catalogue_id'] = int(selected)
        elif selected == 'ninguno':
            initial['catalogue_id'] = None
    form = PostForm(request.POST if request.method == 'POST' else None, instance=entry, profile=profile,
                    initial=initial, editing=bool(entry))
    if request.method == 'POST' and form.is_valid():
        if entry:
            saved = form.save()
        else:
            profile = profile_for(request.user)
            # Reenvíos del mismo formulario reutilizan la primera publicación.
            fields = {name: form.cleaned_data[name] for name in PostForm.Meta.fields}
            saved, _ = SocialPost.objects.get_or_create(
                author=profile, submission_id=form.cleaned_data['submission_id'], defaults=fields)
        messages.success(request, 'Guardamos tu publicación.')
        if saved.moderated:
            return redirect('perfil')
        return redirect('social_post', pk=saved.pk)
    term = request.GET.get('q', '').strip()
    selection = form.selected_book
    if not form.is_bound:
        selected_id = form.initial.get('catalogue_id')
        if selected_id:
            selection = Libro.objects.select_related('autor').filter(pk=selected_id).first()
    return render(request, 'accounts/social/post_editor.html', {
        'form': form, 'entry': entry, 'search_term': term, 'search_books': search_books(term),
        'selected': selection,
    }, status=400 if form.is_bound else 200)


@community
@login_required
@require_POST
@action_limit('post', 12)
def delete_post(request, pk):
    post = owned_post(request, pk)
    if request.POST.get('confirm') != 'yes':
        return HttpResponseBadRequest('Confirma la eliminación de la publicación.')
    post.delete()
    messages.success(request, 'Eliminamos la publicación.')
    return redirect('perfil')


def post_response(request, post, *, form=None, status=200):
    page = posts_page(request, visible_posts(request.user).filter(pk=post.pk), 1)
    if not page:
        raise Http404
    post = page[0]
    comments = visible_comments(post, request.user) if post.allow_comments else SocialComment.objects.none()
    return render(request, 'accounts/social/post.html', {
        'entry': post, 'comments': Paginator(comments, 15).get_page(request.GET.get('page')),
        'comment_form': form or CommentForm(initial={'submission_id': uuid4()}),
        'report_form': ReportForm(),
    }, status=status)


@community
@require_safe
def post_detail(request, pk):
    return post_response(request, visible_post(request.user, pk))


def published_actor(request):
    profile = SocialProfile.objects.filter(user=request.user, published=True).first()
    if not profile:
        messages.error(request, 'Habilita tu perfil público para interactuar con otros lectores.')
    return profile


@community
@login_required
@require_POST
@action_limit('like', 36)
def like_post(request, pk):
    post = visible_post(request.user, pk)
    if post.visibility == SocialPost.Visibility.PRIVATE:
        raise Http404
    action = request.POST.get('action')
    if action == 'remove':
        PostLike.objects.filter(author__user=request.user, post=post).delete()
    elif action == 'add':
        actor = published_actor(request)
        if actor:
            PostLike.objects.get_or_create(author=actor, post=post)
    else:
        return HttpResponseBadRequest('Acción inválida.')
    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({'liked': PostLike.objects.filter(author__user=request.user, post=post).exists(),
                             'count': post.likes.count()})
    return redirect('social_post', pk=pk)


@community
@login_required
@require_POST
@action_limit('comment', 10)
def comment_post(request, pk):
    post = visible_post(request.user, pk)
    if not post.allow_comments or post.visibility == SocialPost.Visibility.PRIVATE:
        raise Http404
    actor = published_actor(request)
    if actor is None:
        return redirect('social_post', pk=pk)
    form = CommentForm(request.POST)
    if not form.is_valid():
        return post_response(request, post, form=form, status=400)
    SocialComment.objects.get_or_create(post=post, author=actor, submission_id=form.cleaned_data['submission_id'],
                                      defaults={'body': form.cleaned_data['body']})
    return redirect('social_post', pk=pk)


@community
@login_required
@require_POST
@action_limit('comment', 10)
def delete_comment(request, pk, comment_id):
    post = visible_post(request.user, pk)
    if request.POST.get('confirm') != 'yes':
        return HttpResponseBadRequest('Confirma la eliminación del comentario.')
    comments = SocialComment.objects.filter(post=post)
    if post.author.user_id != request.user.pk:
        comments = comments.filter(author__user=request.user)
    get_object_or_404(comments, pk=comment_id).delete()
    return redirect('social_post', pk=pk)


@community
@login_required
@require_POST
@action_limit('report', 6)
def report_content(request, pk, comment_id=None):
    post = visible_post(request.user, pk)
    if post.visibility == SocialPost.Visibility.PRIVATE:
        raise Http404
    if comment_id:
        if not post.allow_comments:
            raise Http404
        comment = get_object_or_404(visible_comments(post, request.user), pk=comment_id)
        target = {'comment': comment}
        author_id = comment.author.user_id
    else:
        target = {'post': post}
        author_id = post.author.user_id
    if author_id == request.user.pk:
        return HttpResponseBadRequest('Puedes retirar tu propio contenido desde la publicación.')
    form = ReportForm(request.POST)
    if not form.is_valid():
        return render(request, 'accounts/social/report.html', {'entry': post, 'form': form}, status=400)
    SocialReport.objects.get_or_create(reporter=request.user, **target, defaults={'reason': form.cleaned_data['reason']})
    messages.success(request, 'El reporte quedó registrado para revisión.')
    return redirect('social_post', pk=pk)
