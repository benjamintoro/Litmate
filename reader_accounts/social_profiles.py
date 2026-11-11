"""Perfil público optativo y controles del propietario."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Max, Subquery
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_safe, require_POST, require_http_methods

from core.models import ElementoListaLectura, ListaLectura, PerfilUsuario

from . import avatars
from .library import own_readings, present_book, reading_counts
from .models import AnnualReading, Follow, ProfileCover, SharedList, SharedReading, SocialProfile
from .social_forms import SocialProfileForm
from .social_policy import action_limit, community, public_profiles, visible_posts


def profile_for(user):
    return SocialProfile.objects.get_or_create(user=user)[0]


def avatar_path(user_id):
    name = PerfilUsuario.objects.filter(usuario_id=user_id).values_list('imagen', flat=True).first()
    return avatars.own_path(name) if name else None


def summary(profile, *, owner=False, personal=None):
    data = {
        'has_cover': bool(profile.pk and (owner or profile.share_cover) and ProfileCover.objects.filter(profile=profile).exists()),
        'has_avatar': (owner or profile.share_avatar) and avatar_path(profile.user_id) is not None,
        'following_count': profile.following.filter(target__published=True, target__user__is_active=True).count() if profile.pk else 0,
        'follower_count': profile.followers.filter(follower__published=True, follower__user__is_active=True).count() if profile.pk else 0,
    }
    if owner or profile.share_stats:
        personal = personal or PerfilUsuario.objects.filter(usuario_id=profile.user_id).first()
        goal = max(1, personal.meta_anual_libros) if personal else 12
        annual = AnnualReading.objects.filter(user_id=profile.user_id, year=timezone.localdate().year).count()
        counts = reading_counts(profile.user)
        data['stats'] = {
            'finished': counts['completado'], 'reading': counts['leyendo'], 'pending': counts['por_leer'],
            'lists': ListaLectura.objects.filter(usuario_id=profile.user_id).count(),
            'annual': annual, 'goal': goal, 'progress': min(100, annual * 100 // goal),
        }
    return data


def owner_context(request, personal):
    from .social_posts import posts_page

    profile = profile_for(request.user)
    selected = request.GET.get('seccion', 'publicaciones')
    if selected not in {'publicaciones', 'biblioteca', 'listas', 'actividad', 'informacion', 'configuracion'}:
        selected = 'publicaciones'
    data = {'social': profile, 'social_tab': selected, 'profile_owner': True, **summary(profile, owner=True, personal=personal)}
    if profile.pk and selected in {'publicaciones', 'actividad'}:
        data['posts'] = posts_page(request, profile.posts.all(), request.GET.get('publicaciones'))
    if selected == 'biblioteca':
        data['currently_reading'] = [present_book(book) for book in own_readings(request.user).filter(estado_lectura='leyendo')[:6]]
    if selected == 'listas':
        data['featured_lists'] = ListaLectura.objects.filter(usuario=request.user)[:8]
    return data


@community
@require_safe
def public_profile(request, public_id):
    from .social_posts import posts_page

    profile = get_object_or_404(public_profiles(), public_id=public_id)
    selected = request.GET.get('seccion', 'publicaciones')
    if selected not in {'publicaciones', 'biblioteca', 'listas', 'actividad', 'informacion'}:
        selected = 'publicaciones'
    data = {'social': profile, 'social_tab': selected, 'profile_owner': False, **summary(profile)}
    if request.user.is_authenticated:
        data['visitor_is_owner'] = request.user.pk == profile.user_id
        data['follows_profile'] = profile.followers.filter(follower__user=request.user).exists()
    if selected in {'publicaciones', 'actividad'}:
        # La vista pública se puede previsualizar incluso por el dueño sin sus publicaciones privadas.
        visible = visible_posts(request.user).filter(author=profile).exclude(visibility='private')
        data['posts'] = posts_page(request, visible, request.GET.get('page'))
    if selected == 'biblioteca':
        shared = ElementoListaLectura.objects.filter(lista__usuario_id=profile.user_id, social_share__isnull=False)
        deduped = shared.order_by().values('google_id').annotate(last=Max('pk')).values('last')
        page = Paginator(shared.filter(pk__in=Subquery(deduped)).order_by('-pk'), 12).get_page(request.GET.get('page'))
        page.object_list = [present_book(item) for item in page.object_list]
        data['shared_books'] = page
    if selected == 'listas':
        lists = ListaLectura.objects.filter(usuario_id=profile.user_id, social_share__isnull=False)
        data['shared_lists'] = Paginator(lists.order_by('-fecha_creacion', '-pk'), 12).get_page(request.GET.get('page'))
    return render(request, 'accounts/social/public_profile.html', data)


@community
@require_safe
def shared_list(request, public_id, pk):
    profile = get_object_or_404(public_profiles(), public_id=public_id)
    reading_list = get_object_or_404(ListaLectura, pk=pk, usuario_id=profile.user_id, social_share__isnull=False)
    books = Paginator(reading_list.elementos.order_by('titulo', 'pk'), 16).get_page(request.GET.get('page'))
    books.object_list = [present_book(book) for book in books.object_list]
    return render(request, 'accounts/social/shared_list.html', {'social': profile, 'shared_list': reading_list, 'books': books})


@community
@login_required
@action_limit('profile', 10)
@require_http_methods(['GET', 'HEAD', 'POST'])
def edit_profile(request):
    social = SocialProfile.objects.filter(user=request.user).first() or SocialProfile(user=request.user)
    personal = PerfilUsuario.objects.filter(usuario=request.user).first()
    form = SocialProfileForm(request.POST if request.method == 'POST' else None,
                             request.FILES if request.method == 'POST' else None, instance=social,
                             initial={'annual_goal': personal.meta_anual_libros if personal else 12})
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic(using='accounts'):
                profile = form.save()
                personal, _ = PerfilUsuario.objects.get_or_create(usuario=request.user)
                personal.meta_anual_libros = form.cleaned_data['annual_goal']
                if form.cleaned_data['remove_photo']:
                    personal.imagen = ''
                if form.cleaned_data['photo']:
                    personal.imagen = avatars.store(form.cleaned_data['photo'])
                personal.save(update_fields=['meta_anual_libros', 'imagen'])
                if form.cleaned_data['remove_cover']:
                    ProfileCover.objects.filter(profile=profile).delete()
                if form.cleaned_data['cover']:
                    ProfileCover.objects.update_or_create(profile=profile, defaults={'jpeg': form.cleaned_data['cover']})
        except IntegrityError:
            form.add_error(None, 'El nombre público ya está en uso o el perfil cambió. Recarga y vuelve a intentarlo.')
        except OSError:
            form.add_error('photo', 'No se pudo guardar la fotografía. Inténtalo más tarde.')
        else:
            messages.success(request, 'Guardamos tu perfil literario.')
            return redirect('perfil')
    return render(request, 'accounts/social/edit.html', {'form': form, 'social': social,
                  **summary(social, owner=True, personal=personal)}, status=400 if form.is_bound else 200)


@community
@require_safe
def profile_image(request, public_id, kind):
    if kind not in {'avatar', 'portada'}:
        raise Http404
    is_avatar = kind == 'avatar'
    flag = 'share_avatar' if is_avatar else 'share_cover'
    profile = public_profiles().filter(**{flag: True}, public_id=public_id).first()
    if profile is None and request.user.is_authenticated:
        profile = SocialProfile.objects.filter(public_id=public_id, user=request.user).first()
    if profile is None:
        raise Http404
    if is_avatar:
        path = avatar_path(profile.user_id)
        if path is None:
            raise Http404
        response = FileResponse(path.open('rb'), content_type='image/jpeg')
    else:
        cover = get_object_or_404(ProfileCover, profile=profile)
        response = HttpResponse(cover.jpeg, content_type='image/jpeg')
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    response['X-Robots-Tag'] = 'noindex, noarchive'
    return response


@community
@login_required
@require_POST
@action_limit('follow', 30)
def follow_profile(request, public_id):
    target = get_object_or_404(public_profiles(), public_id=public_id)
    if request.user.pk == target.user_id:
        return HttpResponseBadRequest('No puedes seguir tu propio perfil.')
    action = request.POST.get('action')
    if action == 'remove':
        Follow.objects.filter(follower__user=request.user, target=target).delete()
    elif action == 'add':
        follower = SocialProfile.objects.filter(user=request.user, published=True).first()
        if follower:
            Follow.objects.get_or_create(follower=follower, target=target)
        else:
            messages.error(request, 'Habilita tu perfil público antes de seguir a otro lector.')
    else:
        return HttpResponseBadRequest('Acción inválida.')
    return redirect('social_public_profile', public_id=public_id)


@community
@login_required
@require_POST
@action_limit('share', 24)
def share_library(request, kind, pk):
    if kind == 'lectura':
        item = get_object_or_404(ElementoListaLectura, pk=pk, lista__usuario=request.user)
        shares = SharedReading.objects.filter(item__lista__usuario=request.user, item__google_id=item.google_id)
        model, target = SharedReading, {'item': item}
    elif kind == 'lista':
        reading_list = get_object_or_404(ListaLectura, pk=pk, usuario=request.user)
        shares = SharedList.objects.filter(reading_list=reading_list)
        model, target = SharedList, {'reading_list': reading_list}
    else:
        raise Http404
    action = request.POST.get('action')
    if action == 'remove':
        shares.delete()
        messages.success(request, 'Quitamos este elemento de tu perfil público.')
    elif action == 'add' and request.POST.get('confirm') == 'yes':
        if not SocialProfile.objects.filter(user=request.user, published=True).exists():
            messages.error(request, 'Habilita tu perfil público antes de compartir desde la biblioteca.')
        else:
            with transaction.atomic(using='accounts'):
                if not shares.exists():
                    model.objects.get_or_create(**target)
            messages.success(request, 'Guardamos este elemento en tu perfil público.')
    else:
        return HttpResponseBadRequest('Confirma que quieres compartir este elemento.')
    return redirect('reader_library')
