"""Biblioteca personal; reutiliza los modelos core, sin escribir el catálogo."""
import functools
import json
from urllib.parse import urlencode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, transaction
from django.db.models import Count, Exists, OuterRef, Max, Subquery
from django.http import JsonResponse, FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_http_methods
from core.models import LibroFavorito, ListaLectura, ElementoListaLectura, PerfilUsuario
from suscripciones.models import SuscripcionUsuario
from .forms import ReaderProfileForm, ReadingListForm, BookSnapshotForm
from .usage import entitlement, UsageError
from .auth_limits import auth_limit


def api(view):
    @functools.wraps(view)
    def guarded(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'status': 'error', 'msg': 'Inicia sesión para guardar libros.'}, status=401)
        try:
            return view(request, *args, **kwargs)
        except (ValueError, TypeError, json.JSONDecodeError):
            return JsonResponse({'status': 'error', 'msg': 'Revisa los datos enviados.'}, status=400)
        except DatabaseError:
            return JsonResponse({'status': 'error', 'msg': 'No pudimos guardar el cambio. Inténtalo más tarde.'}, status=503)
    return never_cache(guarded)


def payload(request):
    data = json.loads(request.body) if request.content_type == 'application/json' else request.POST.dict()
    if not isinstance(data, dict):
        raise ValueError('object required')
    return data


def snapshot(data):
    form = BookSnapshotForm(data)
    if not form.is_valid():
        raise ValueError('invalid book')
    return form.cleaned_data


READING_LABELS = {'por_leer': 'Quiero leer', 'leyendo': 'Leyendo', 'completado': 'Terminado'}


def own_readings(user):
    """Una obra por identificador, sin borrar su pertenencia a distintas listas."""
    owned = ElementoListaLectura.objects.filter(lista__usuario=user)
    latest = owned.order_by().values('google_id').annotate(latest=Max('pk')).values('latest')
    return owned.filter(pk__in=Subquery(latest)).order_by('-pk')


def reading_counts(user):
    counts = dict.fromkeys(READING_LABELS, 0)
    counts.update({row['estado_lectura']: row['total'] for row in
        own_readings(user).order_by().values('estado_lectura').annotate(total=Count('pk'))})
    return counts


def present_book(book):
    raw = book.imagen_url or ''
    if raw.startswith('http://'):
        raw = 'https://' + raw[7:]
    form = BookSnapshotForm({'google_id': book.google_id, 'titulo': book.titulo,
        'autores': book.autores, 'imagen_url': raw})
    book.display_cover = form.cleaned_data.get('imagen_url', '') if form.is_valid() else ''
    book.detail_url = reverse('reader_book_detail') + '?' + urlencode({'id': book.google_id})
    return book


def reading_groups(user):
    groups = {state: {'state': state, 'label': label, 'books': []} for state, label in READING_LABELS.items()}
    for book in own_readings(user):
        if book.estado_lectura in groups:
            groups[book.estado_lectura]['books'].append(present_book(book))
    return list(groups.values())


@api
@require_POST
def favorite_add(request):
    data = snapshot(payload(request))
    with transaction.atomic(using='accounts'):
        favorite = LibroFavorito.objects.filter(usuario=request.user, google_id=data['google_id']).first()
        if favorite:
            return JsonResponse({'status': 'exists', 'id': favorite.pk, 'msg': 'Este libro ya está guardado.'})
        try:
            entitlement(request.user)
        except UsageError as error:
            return JsonResponse({'status': 'error', 'msg': error.text}, status=error.status)
        sub = SuscripcionUsuario.objects.select_related('plan').get(usuario=request.user)
        limit = sub.plan.limite_favoritos
        if limit < 0 or (limit and LibroFavorito.objects.filter(usuario=request.user).count() >= limit):
            return JsonResponse({'status': 'error', 'msg': 'Alcanzaste el límite de favoritos de tu plan.'}, status=403)
        favorite = LibroFavorito.objects.create(usuario=request.user, **data)
    return JsonResponse({'status': 'ok', 'id': favorite.pk, 'msg': 'Libro guardado en favoritos.'})


@api
@require_POST
def favorite_remove(request, id):
    favorite = get_object_or_404(LibroFavorito, pk=id, usuario=request.user)
    favorite.delete()
    if request.content_type != 'application/json':
        return redirect('reader_library')
    return JsonResponse({'status': 'ok'})


@never_cache
@login_required
def library_page(request, *, list_form=None, status=200):
    favorites = [present_book(book) for book in LibroFavorito.objects.filter(usuario=request.user)]
    reading_lists = ListaLectura.objects.filter(usuario=request.user).prefetch_related('elementos')
    groups = reading_groups(request.user)
    if settings.LITMATE_COMMUNITY_ENABLED:
        from .models import SharedList, SharedReading
        reading_lists = reading_lists.annotate(shared=Exists(SharedList.objects.filter(reading_list_id=OuterRef('pk'))))
        shared = set(SharedReading.objects.filter(item__lista__usuario=request.user).values_list('item__google_id', flat=True))
        for group in groups:
            for book in group['books']:
                book.shared = book.google_id in shared
    return render(request, 'accounts/library.html', {
        'favorites': favorites,
        'reading_lists': reading_lists,
        'list_form': list_form if list_form is not None else ReadingListForm(),
        'reading_groups': groups, 'reading_labels': READING_LABELS,
    }, status=status)


@api
@require_POST
def list_create(request):
    data = payload(request)
    form = ReadingListForm(data)
    if not form.is_valid():
        if request.content_type != 'application/json':
            return library_page(request, list_form=form, status=400)
        raise ValueError('invalid list')
    with transaction.atomic(using='accounts'):
        existing = ListaLectura.objects.filter(usuario=request.user, nombre__iexact=form.cleaned_data['nombre']).first()
        if existing:
            if request.content_type != 'application/json':
                return redirect('reader_library')
            return JsonResponse({'status': 'ok', 'id': existing.pk, 'nombre': existing.nombre,
                                 'es_publica': False, 'msg': 'Ya tienes una lista con ese nombre.'})
        if ListaLectura.objects.filter(usuario=request.user).count() >= 100:
            return JsonResponse({'status': 'error', 'msg': 'Puedes guardar hasta 100 listas.'}, status=403)
        reading_list = form.save(commit=False)
        reading_list.usuario = request.user
        reading_list.es_publica = False
        reading_list.save()
        if data.get('google_id'):
            ElementoListaLectura.objects.create(lista=reading_list, **snapshot(data))
    if request.content_type != 'application/json':
        return redirect('reader_library')
    return JsonResponse({'status': 'ok', 'id': reading_list.pk, 'nombre': reading_list.nombre,
                         'es_publica': False, 'msg': 'Lista privada creada.'})


@never_cache
@login_required
@require_http_methods(['GET', 'POST'])
def list_edit(request, id):
    reading_list = get_object_or_404(ListaLectura, pk=id, usuario=request.user)
    form = ReadingListForm(request.POST if request.method == 'POST' else None, instance=reading_list)
    status = 200
    if request.method == 'POST':
        try:
            with transaction.atomic(using='accounts'):
                if form.is_valid():
                    form.save()
                    return redirect('reader_library')
        except DatabaseError:
            form.add_error(None, 'No pudimos guardar la lista. Inténtalo más tarde.')
            status = 503
    return render(request, 'accounts/edit.html', {'form': form, 'heading': 'Editar lista',
        'return_to_library': True}, status=status)


@api
@require_POST
def list_remove(request, id):
    data = payload(request)
    if data.get('confirmar') not in (True, 'si'):
        return JsonResponse({'status': 'error', 'msg': 'Confirma la eliminación de tu lista.'}, status=400)
    get_object_or_404(ListaLectura, pk=id, usuario=request.user).delete()
    if request.content_type != 'application/json':
        return redirect('reader_library')
    return JsonResponse({'status': 'ok'})


@api
@require_http_methods(['GET'])
def list_get(request):
    book = request.GET.get('book_id', '')[:100]
    rows = []
    contains = ElementoListaLectura.objects.filter(lista_id=OuterRef('pk'), google_id=book)
    for reading_list in ListaLectura.objects.filter(usuario=request.user).annotate(
            item_count=Count('elementos'), contains=Exists(contains)):
        rows.append({'id': reading_list.pk, 'nombre': reading_list.nombre, 'es_publica': False,
                     'total_libros': reading_list.item_count, 'contiene_libro': reading_list.contains})
    state = ElementoListaLectura.objects.filter(lista__usuario=request.user, google_id=book).order_by('-pk').values_list('estado_lectura', flat=True).first()
    return JsonResponse({'status': 'ok', 'listas': rows,
                         'estado_actual': state or 'por_leer'})


@api
@require_POST
def list_add(request):
    data = payload(request)
    with transaction.atomic(using='accounts'):
        reading_list = get_object_or_404(ListaLectura, pk=data.get('lista_id'), usuario=request.user)
        book = snapshot(data)
        already_completed = own_readings(request.user).filter(google_id=book['google_id'], estado_lectura='completado').exists()
        item = reading_list.elementos.filter(google_id=book['google_id']).first()
        action = data.get('action', 'add')
        if action not in ('add', 'toggle', 'remove'):
            raise ValueError('invalid action')
        if item and action in ('toggle', 'remove'):
            item.delete()
            return JsonResponse({'status': 'ok', 'action': 'removed', 'msg': 'Libro quitado de la lista.'})
        if action == 'remove':
            return JsonResponse({'status': 'ok', 'action': 'removed'})
        state = data.get('estado_lectura', 'por_leer')
        if state not in dict(ElementoListaLectura.ESTADO_CHOICES):
            raise ValueError('invalid state')
        if not item and reading_list.elementos.count() >= 500:
            return JsonResponse({'status': 'error', 'msg': 'Puedes guardar hasta 500 libros por lista.'}, status=403)
        item, _ = ElementoListaLectura.objects.update_or_create(lista=reading_list,
            google_id=book['google_id'], defaults={**book, 'estado_lectura': state})
        record_completion(request.user, book['google_id'], state, already_completed)
    return JsonResponse({'status': 'ok', 'action': 'added', 'id': item.pk, 'msg': 'Lista actualizada.'})


@api
@require_POST
def item_remove(request, id):
    get_object_or_404(ElementoListaLectura, pk=id, lista__usuario=request.user).delete()
    if request.content_type != 'application/json':
        return redirect('reader_library')
    return JsonResponse({'status': 'ok'})


@never_cache
@login_required
@auth_limit(12)
@require_http_methods(['GET', 'POST'])
def profile_edit(request):
    try:
        profile = PerfilUsuario.objects.filter(usuario=request.user).first() or PerfilUsuario(usuario=request.user)
    except DatabaseError:
        return HttpResponse('No pudimos cargar el perfil. Inténtalo más tarde.', status=503)
    form = ReaderProfileForm(request.POST if request.method == 'POST' else None,
                             request.FILES if request.method == 'POST' else None, instance=profile)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic(using='accounts'):
                edited = form.save(commit=False)
                if form.cleaned_data.get('remove_photo'):
                    # Se retira la referencia privada, sin borrar archivos de
                    # respaldos ni aceptar una ruta elegida por el navegador.
                    edited.imagen = ''
                if form.cleaned_data.get('photo'):
                    from .avatars import store
                    edited.imagen = store(form.cleaned_data['photo'])
                edited.save()
                request.user.first_name = form.cleaned_data['nombre'] or ''
                request.user.last_name = form.cleaned_data['apellido'] or ''
                request.user.save(update_fields=['first_name', 'last_name'])
        except OSError:
            form.add_error('photo', 'No pudimos guardar la imagen. Inténtalo más tarde.')
            return render(request, 'accounts/edit.html', {'form': form, 'heading': 'Editar perfil'}, status=503)
        except DatabaseError:
            form.add_error(None, 'No pudimos guardar el perfil. Inténtalo más tarde.')
            return render(request, 'accounts/edit.html', {'form': form, 'heading': 'Editar perfil'}, status=503)
        messages.success(request, 'Perfil actualizado.')
        return redirect('perfil')
    return render(request, 'accounts/edit.html', {'form': form, 'heading': 'Editar perfil'})


@never_cache
@login_required
def avatar(request):
    from .avatars import own_path
    profile = PerfilUsuario.objects.filter(usuario=request.user).first()
    path = own_path(profile.imagen.name) if profile else None
    if path is None:
        raise Http404
    response = FileResponse(path.open('rb'), content_type='image/jpeg')
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return response


@api
@require_POST
def reading_state(request):
    """El selector existente guarda progreso en ElementoListaLectura, no en MySQL."""
    data = payload(request)
    state = data.get('estado')
    if state not in dict(ElementoListaLectura.ESTADO_CHOICES):
        raise ValueError('invalid state')
    book = snapshot({**data, 'autores': data.get('autor', data.get('autores', ''))})
    with transaction.atomic(using='accounts'):
        items = ElementoListaLectura.objects.filter(lista__usuario=request.user, google_id=book['google_id'])
        already_completed = own_readings(request.user).filter(google_id=book['google_id'], estado_lectura='completado').exists()
        if items.exists():
            items.update(estado_lectura=state)
        else:
            if not ListaLectura.objects.filter(usuario=request.user, nombre='Mis lecturas').exists() and ListaLectura.objects.filter(usuario=request.user).count() >= 100:
                return JsonResponse({'status': 'error', 'msg': 'Puedes guardar hasta 100 listas.'}, status=403)
            reading_list, _ = ListaLectura.objects.get_or_create(usuario=request.user, nombre='Mis lecturas',
                defaults={'es_publica': False})
            if reading_list.elementos.count() >= 500:
                return JsonResponse({'status': 'error', 'msg': 'La lista Mis lecturas está completa.'}, status=403)
            ElementoListaLectura.objects.create(lista=reading_list, estado_lectura=state, **book)
        record_completion(request.user, book['google_id'], state, already_completed)
    if request.content_type != 'application/json':
        messages.success(request, 'Estado de lectura actualizado.')
        return redirect('reader_library')
    return JsonResponse({'status': 'ok', 'estado': state})


def record_completion(user, book_id, state, already_completed):
    if settings.LITMATE_COMMUNITY_ENABLED and state == 'completado' and not already_completed:
        from .models import AnnualReading
        AnnualReading.objects.get_or_create(user=user, book_id=book_id, year=timezone.localdate().year)


@api
@require_http_methods(['GET'])
def book_status(request):
    identifiers = request.GET.getlist('id')
    if not identifiers or len(identifiers) > 50 or any(not value or len(value) > 100 for value in identifiers):
        raise ValueError('invalid identifiers')
    saved = dict(LibroFavorito.objects.filter(usuario=request.user, google_id__in=identifiers).values_list('google_id', 'pk'))
    states = dict(own_readings(request.user).filter(google_id__in=identifiers).values_list('google_id', 'estado_lectura'))
    return JsonResponse({'books': {key: {'favorite_id': saved.get(key), 'state': states.get(key)} for key in identifiers}})


@never_cache
@login_required
def book_detail(request):
    key = request.GET.get('id', '')
    if not key or len(key) > 100:
        raise Http404
    favorite = LibroFavorito.objects.filter(usuario=request.user, google_id=key).first()
    items = list(ElementoListaLectura.objects.filter(lista__usuario=request.user, google_id=key).select_related('lista').order_by('-pk'))
    book = favorite or (items[0] if items else None)
    if book is None:
        raise Http404
    query = urlencode({'q': book.titulo + ' ' + book.autores})
    return render(request, 'accounts/book.html', {'book': present_book(book), 'items': items,
        'reading_labels': READING_LABELS, 'current_state': items[0].estado_lectura if items else 'por_leer',
        'book_links': [('Amazon', 'https://www.amazon.com/s?' + urlencode({'k': book.titulo+' '+book.autores})),
                       ('Buscalibre', 'https://www.buscalibre.cl/libros/search?' + query)]})


@never_cache
@login_required
@require_POST
def reading_note(request, id):
    item = get_object_or_404(ElementoListaLectura, pk=id, lista__usuario=request.user)
    value = request.POST.get('nota_personal', '').strip()
    if len(value) > 255:
        return HttpResponse('Utiliza un máximo de 255 caracteres para tu nota.', status=400)
    try:
        item.nota_personal = value
        item.save(update_fields=['nota_personal'])
    except DatabaseError:
        return HttpResponse('No pudimos guardar la nota. Inténtalo más tarde.', status=503)
    messages.success(request, 'Nota personal guardada.')
    return redirect(reverse('reader_book_detail') + '?' + urlencode({'id': item.google_id}))
