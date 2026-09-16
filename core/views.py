from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, StreamingHttpResponse
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout
from django.utils.http import url_has_allowed_host_and_scheme
from django.core.mail import send_mail
from .models import (
    HistorialChatbot, PerfilUsuario, LibroFavorito, Libro, Autor,
    Genero, Editorial, EstadoLectura, Resena, ClickConversion, EventoAnalitica,
    MensajeContacto, ConversacionIA, MensajeIA, ListaLectura, ElementoListaLectura
)
from .quotas import verificar_y_consumir_cuota, estado_cuota_usuario
from .forms import UserRegisterForm, UserLoginForm, UserUpdateForm, ProfileUpdateForm
from .services import buscar_libros_hibrido, generar_enlaces_tiendas, generar_demo_extracto
from .security import ratelimit, check_honeypot, get_client_ip
from django.utils.text import slugify
from suscripciones.models import PlanSuscripcion, SuscripcionUsuario
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
import json
import re
import requests
import secrets
import datetime
import logging
import random
import os
from groq import Groq



# Importamos los datos limpios
from core.chatbot_data import SOCIAL_PATTERNS, BOOK_QUERY_PATTERNS, detect_genre

# Logger configurado en settings.py
logger = logging.getLogger('litmate')


# --- INICIALIZACIÓN PEREZOSA DE SERVICIOS IA ---
def get_ai_resources():
    embedding_model = None
    pinecone_index = None
    
    try:
        if getattr(settings, 'PINECONE_API_KEY', None):
            try:
                from pinecone import Pinecone
                from sentence_transformers import SentenceTransformer
                pc = Pinecone(api_key=settings.PINECONE_API_KEY)
                INDEX_NAME = 'litmate-book-index'
                
                if INDEX_NAME in pc.list_indexes().names():
                    pinecone_index = pc.Index(INDEX_NAME)
                    embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            except Exception as e:
                logger.warning(f"Vector search Pinecone/SentenceTransformer no disponible: {e}")
    except Exception as e:
        logger.warning(f"Error inicializando IA: {e}")
        
    return embedding_model, pinecone_index


# --- UTILIDADES DE BÚSQUEDA ---

def search_google_books(query, max_results=3):
    """Busca libros en Google Books API y retorna con links."""
    try:
        query_escaped = requests.utils.quote(query)
        url = f"https://www.googleapis.com/books/v1/volumes?q={query_escaped}&maxResults={max_results * 3}&langRestrict=es&orderBy=relevance"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        results = []
        if 'items' in data:
            for item in data['items']:
                info = item.get('volumeInfo', {})
                titulo = info.get('title', '')
                
                if not titulo or len(titulo) < 2: continue
                
                description = info.get('description', '')
                if not description or len(description) < 50: continue
                
                titulo_lower = titulo.lower()
                if any(x in titulo_lower for x in ['graphic novel', 'edición gráfica', 'resumen']) and \
                   not any(x in query.lower() for x in ['graphic', 'gráfica', 'resumen']):
                    continue
                
                book_id = item.get('id', '')
                google_books_link = f"https://books.google.com/books?id={book_id}" if book_id else info.get('infoLink', '')
                
                results.append({
                    'titulo': titulo,
                    'autores': info.get('authors', ['Autor desconocido']),
                    'descripcion': description,
                    'categorias': info.get('categories', []),
                    'info_link': info.get('infoLink', ''),
                    'google_books_link': google_books_link,
                    'imagen': info.get('imageLinks', {}).get('thumbnail', '')
                })
                
                if len(results) >= max_results: break
        
        return results
    except Exception as e:
        logger.error(f"Error Google Books: {e}")
        return []

def buscar_detalles_libro_google(book_title, query_type):
    """Busca los detalles de un libro específico en Google Books."""
    try:
        query_escaped = requests.utils.quote(book_title)
        url = f"https://www.googleapis.com/books/v1/volumes?q={query_escaped}&maxResults=10&langRestrict=es&orderBy=relevance"
        
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if 'items' not in data or len(data['items']) == 0:
            return None, None
        
        selected_item = None
        for idx, item in enumerate(data['items']):
            info = item.get('volumeInfo', {})
            description = info.get('description', '')
            if description and len(description) > 30:
                selected_item = item
                break
        
        if not selected_item: return None, None
        
        info = selected_item.get('volumeInfo', {})
        details = {}
        
        authors = info.get('authors', [])
        details['author'] = ', '.join(authors) if authors else 'Autor desconocido'
        details['trama'] = info.get('description', 'No hay descripción disponible.')[:300]
        details['personajes'] = 'Esta información no está disponible en Google Books.'
        
        series_info = info.get('seriesInfo', {})
        if series_info and series_info.get('displaySeries'):
            details['serie'] = series_info.get('displaySeries')
        else:
            details['serie'] = 'Esta información no está disponible.'
        
        book_id = selected_item.get('id', '')
        details['link'] = f"https://books.google.com/books?id={book_id}" if book_id else info.get('infoLink', '')
        details['titulo'] = info.get('title', book_title)
        
        return details, details.get('link', '')
        
    except Exception as e:
        logger.error(f"Error detalle libro: {e}")
        return None, None


# --- VISTAS DE AUTENTICACIÓN Y REGISTRO MEJORADAS ---

@ratelimit(limit=6, period=60, key_prefix='register')
def register(request):
    if request.user.is_authenticated:
        return redirect('index')

    if request.method == 'POST':
        # Anti-spam Honeypot Check
        if check_honeypot(request):
            return redirect('index')

        form = UserRegisterForm(request.POST)
        if form.is_valid():
            try:
                user = form.save(commit=False)
                user.set_password(form.cleaned_data['password'])
                user.save()

                # Crear automáticamente perfil de usuario asociado
                nombre_completo = f"{user.first_name} {user.last_name}".strip()
                PerfilUsuario.objects.get_or_create(
                    usuario=user,
                    defaults={
                        'nombre': nombre_completo if nombre_completo else user.username,
                        'correo': user.email
                    }
                )

                # Asignar automáticamente el plan gratuito de suscripción si existe
                plan_gratis = PlanSuscripcion.objects.filter(slug='gratis').first() or PlanSuscripcion.objects.filter(precio=0, activo=True).first()
                if plan_gratis:
                    SuscripcionUsuario.objects.get_or_create(
                        usuario=user,
                        defaults={'plan': plan_gratis, 'estado': 'activa'}
                    )

                # Iniciar sesión automáticamente tras el registro exitoso
                login(request, user)
                nombre_display = user.first_name if user.first_name else user.username
                messages.success(request, f'¡Bienvenido a LitMate, {nombre_display}! Tu cuenta ha sido creada y tu plan gratuito está activo.')
                return redirect('index')

            except IntegrityError:
                messages.error(request, 'El nombre de usuario o correo ya está en uso. Por favor, elige otro.')
            except Exception as e:
                logger.error(f"Error en registro: {e}")
                messages.error(request, 'Ocurrió un error al crear tu cuenta. Inténtalo nuevamente.')
        else:
            messages.error(request, 'Por favor corrige los errores señalados en el formulario.')
    else:
        form = UserRegisterForm()
        
    return render(request, 'registration/register.html', {'form': form})


@ratelimit(limit=8, period=60, key_prefix='login')
def login_view(request):
    if request.user.is_authenticated:
        return redirect('index')

    next_url = request.GET.get('next', request.POST.get('next', ''))

    if request.method == 'POST':
        # Anti-spam Honeypot Check
        if check_honeypot(request):
            return redirect('index')

        form = UserLoginForm(request.POST)
        if form.is_valid():
            user = form.cleaned_data.get('user')
            remember_me = form.cleaned_data.get('remember_me', True)

            # Configurar duración de la sesión según "Recordarme"
            if not remember_me:
                request.session.set_expiry(0)  # Cierra sesión al cerrar navegador
            else:
                request.session.set_expiry(1209600)  # 2 semanas

            login(request, user)

            nombre_display = user.first_name if user.first_name else user.username
            messages.success(request, f'¡Hola de nuevo, {nombre_display}!')

            # Redirección segura si existe parámetro next
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)
            return redirect('index')
        else:
            messages.error(request, 'Credenciales inválidas. Verifica tu usuario/correo y contraseña.')
    else:
        form = UserLoginForm()

    return render(request, 'registration/login.html', {'form': form, 'next': next_url})


# --- SOCIAL LOGIN (GOOGLE & GITHUB) ---

def social_login_start(request, provider):
    """
    Inicia el flujo de autenticación social OAuth2 con Google o GitHub.
    Verifica las credenciales en .env y redirige al consentimiento oficial del proveedor.
    """
    if request.user.is_authenticated:
        return redirect('index')

    provider = provider.lower()
    next_url = request.GET.get('next', 'index')
    request.session['social_auth_next'] = next_url

    # Generar token CSRF (state) para seguridad OAuth2
    state = secrets.token_urlsafe(24)
    request.session['oauth_state'] = state

    # Construir redirect_uri absoluta respetando el host y puerto activo
    redirect_uri = request.build_absolute_uri(reverse('social_login_callback', kwargs={'provider': provider}))

    # 1. Google OAuth
    if provider == 'google':
        client_id = getattr(settings, 'GOOGLE_CLIENT_ID', '').strip()
        client_secret = getattr(settings, 'GOOGLE_CLIENT_SECRET', '').strip()

        # Validación de credenciales configuradas
        if not client_id or not client_secret or client_id.startswith('tu_'):
            if request.GET.get('demo') == '1':
                return _social_login_demo_mock(request, provider)
            messages.warning(
                request,
                'Para iniciar sesión real con Google, debes configurar GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET en tu archivo .env.'
            )
            referer = request.META.get('HTTP_REFERER')
            return redirect(referer if referer else 'login')

        google_auth_url = (
            f"https://accounts.google.com/o/oauth2/v2/auth?"
            f"client_id={client_id}&"
            f"redirect_uri={redirect_uri}&"
            f"response_type=code&"
            f"scope=openid%20email%20profile&"
            f"access_type=offline&"
            f"prompt=select_account&"
            f"state={state}"
        )
        return redirect(google_auth_url)

    # 2. GitHub OAuth
    elif provider == 'github':
        client_id = getattr(settings, 'GITHUB_CLIENT_ID', '').strip()
        client_secret = getattr(settings, 'GITHUB_CLIENT_SECRET', '').strip()

        # Validación de credenciales configuradas
        if not client_id or not client_secret or client_id.startswith('tu_'):
            if request.GET.get('demo') == '1':
                return _social_login_demo_mock(request, provider)
            messages.warning(
                request,
                'Para iniciar sesión real con GitHub, debes configurar GITHUB_CLIENT_ID y GITHUB_CLIENT_SECRET en tu archivo .env.'
            )
            referer = request.META.get('HTTP_REFERER')
            return redirect(referer if referer else 'login')

        github_auth_url = (
            f"https://github.com/login/oauth/authorize?"
            f"client_id={client_id}&"
            f"redirect_uri={redirect_uri}&"
            f"scope=read:user%20user:email&"
            f"state={state}"
        )
        return redirect(github_auth_url)

    messages.error(request, f'Proveedor de autenticación "{provider}" no válido.')
    return redirect('login')


def _social_login_demo_mock(request, provider):
    """Genera/autentica una cuenta de demostración cuando se solicita expresamente el modo demo."""
    from django.contrib.auth.models import User

    if provider == 'google':
        username = 'google_lector'
        email = 'lector.google@litmate.com'
        first_name = 'Lector'
        last_name = 'Google'
        bio = 'Lector apasionado conectado a través de Google Demo.'
    else:
        username = 'github_dev'
        email = 'dev.github@litmate.com'
        first_name = 'Dev'
        last_name = 'GitHub'
        bio = 'Desarrollador y lector conectado a través de GitHub Demo.'

    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            'email': email,
            'first_name': first_name,
            'last_name': last_name,
        }
    )
    if created:
        user.set_unusable_password()
        user.save()

    # Perfil
    PerfilUsuario.objects.get_or_create(
        usuario=user,
        defaults={
            'nombre': f"{first_name} {last_name}",
            'correo': email,
            'biografia': bio
        }
    )

    # Plan gratuito
    plan_gratis = PlanSuscripcion.objects.filter(slug='gratis').first() or PlanSuscripcion.objects.filter(precio=0, activo=True).first()
    if plan_gratis:
        SuscripcionUsuario.objects.get_or_create(
            usuario=user,
            defaults={'plan': plan_gratis, 'estado': 'activa'}
        )

    user.backend = 'django.contrib.auth.backends.ModelBackend'
    login(request, user)
    provider_name = 'Google' if provider == 'google' else 'GitHub'
    messages.success(request, f'¡Inicio de sesión en Modo Demo con {provider_name}! Bienvenido a LitMate, {first_name}.')

    next_url = request.session.pop('social_auth_next', 'index')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect('index')


def social_login_callback(request, provider):
    """
    Recibe el código de autorización de Google o GitHub, intercambia el token,
    obtiene los datos del perfil y autentica o crea al usuario en LitMate.
    """
    from django.contrib.auth.models import User
    provider = provider.lower()

    # Manejo de cancelación o error devuelto por el proveedor
    error = request.GET.get('error')
    if error:
        error_desc = request.GET.get('error_description', '')
        logger.warning(f"OAuth cancelado o error ({provider}): {error} - {error_desc}")
        messages.info(request, f'Has cancelado el inicio de sesión con {provider.title()}.')
        return redirect('login')

    code = request.GET.get('code')
    if not code:
        messages.error(request, f'No se recibió código de autorización de {provider.title()}.')
        return redirect('login')

    # Validar state CSRF si estaba guardado en la sesión
    returned_state = request.GET.get('state')
    session_state = request.session.pop('oauth_state', None)
    if session_state and returned_state and session_state != returned_state:
        logger.warning(f"Validación CSRF fallida en OAuth ({provider}).")
        messages.error(request, 'Error de validación de seguridad (CSRF). Por favor intenta de nuevo.')
        return redirect('login')

    redirect_uri = request.build_absolute_uri(reverse('social_login_callback', kwargs={'provider': provider}))

    try:
        if provider == 'google':
            client_id = getattr(settings, 'GOOGLE_CLIENT_ID', '').strip()
            client_secret = getattr(settings, 'GOOGLE_CLIENT_SECRET', '').strip()
            if not client_id or not client_secret:
                messages.error(request, 'Las credenciales de Google OAuth no están configuradas.')
                return redirect('login')

            token_url = "https://oauth2.googleapis.com/token"
            token_data = {
                'code': code,
                'client_id': client_id,
                'client_secret': client_secret,
                'redirect_uri': redirect_uri,
                'grant_type': 'authorization_code'
            }
            res = requests.post(token_url, data=token_data, timeout=10)
            token_res = res.json()
            access_token = token_res.get('access_token')

            if not access_token:
                err_desc = token_res.get('error_description') or token_res.get('error') or 'Token de acceso no recibido.'
                logger.error(f"Error Google OAuth token: {token_res}")
                messages.error(request, f'Error al autenticar con Google: {err_desc}')
                return redirect('login')

            user_info_res = requests.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={'Authorization': f"Bearer {access_token}"},
                timeout=10
            )
            user_info = user_info_res.json()

            email = (user_info.get('email') or '').strip().lower()
            if not email:
                messages.error(request, 'Google no proporcionó una dirección de correo válida.')
                return redirect('login')

            first_name = (user_info.get('given_name') or '').strip()
            last_name = (user_info.get('family_name') or '').strip()
            google_id = str(user_info.get('id', ''))
            login_name = ''
            social_avatar = user_info.get('picture', '')

        elif provider == 'github':
            client_id = getattr(settings, 'GITHUB_CLIENT_ID', '').strip()
            client_secret = getattr(settings, 'GITHUB_CLIENT_SECRET', '').strip()
            if not client_id or not client_secret:
                messages.error(request, 'Las credenciales de GitHub OAuth no están configuradas.')
                return redirect('login')

            token_url = "https://github.com/login/oauth/access_token"
            token_data = {
                'client_id': client_id,
                'client_secret': client_secret,
                'code': code,
                'redirect_uri': redirect_uri
            }
            res = requests.post(token_url, data=token_data, headers={'Accept': 'application/json'}, timeout=10)
            token_res = res.json()
            access_token = token_res.get('access_token')

            if not access_token:
                err_desc = token_res.get('error_description') or token_res.get('error') or 'Token de acceso no recibido.'
                logger.error(f"Error GitHub OAuth token: {token_res}")
                messages.error(request, f'Error al autenticar con GitHub: {err_desc}')
                return redirect('login')

            user_res = requests.get(
                "https://api.github.com/user",
                headers={'Authorization': f"token {access_token}", 'Accept': 'application/json'},
                timeout=10
            )
            user_info = user_res.json()

            github_id = str(user_info.get('id', ''))
            login_name = (user_info.get('login') or '').strip()
            raw_name = (user_info.get('name') or '').strip()
            if raw_name:
                name_parts = raw_name.split(' ', 1)
                first_name = name_parts[0]
                last_name = name_parts[1] if len(name_parts) > 1 else ''
            else:
                first_name = login_name or 'Lector'
                last_name = ''

            email = (user_info.get('email') or '').strip().lower()
            if not email:
                emails_res = requests.get(
                    "https://api.github.com/user/emails",
                    headers={'Authorization': f"token {access_token}", 'Accept': 'application/json'},
                    timeout=10
                )
                if emails_res.status_code == 200:
                    emails_data = emails_res.json()
                    if isinstance(emails_data, list):
                        for e in emails_data:
                            if e.get('primary') and e.get('verified'):
                                email = (e.get('email') or '').strip().lower()
                                break
                        if not email and emails_data:
                            email = (emails_data[0].get('email') or '').strip().lower()

            if not email:
                email = f"{login_name or github_id}@users.noreply.github.com"
            google_id = ''
            social_avatar = user_info.get('avatar_url', '')
        else:
            return redirect('login')

        # 1. Vincular o buscar usuario por correo (prioritario)
        user = None
        if email and not email.endswith('@users.noreply.github.com'):
            user = User.objects.filter(email__iexact=email).first()

        # 2. Si no existe por correo, verificar por nombre de usuario del proveedor
        if not user and login_name:
            user = User.objects.filter(username__iexact=login_name).first()

        # 3. Si sigue sin existir, creamos una nueva cuenta con username único
        if not user:
            raw_base = login_name if (provider == 'github' and login_name) else (
                f"google_{google_id[:8]}" if google_id else email.split('@')[0]
            )
            base_username = re.sub(r'[^\w.@+-]', '_', raw_base)[:20]
            if not base_username:
                base_username = f"user_{provider}"

            candidate_username = base_username
            suffix = 1
            while User.objects.filter(username__iexact=candidate_username).exists():
                candidate_username = f"{base_username}_{suffix}"
                suffix += 1

            user = User.objects.create(
                username=candidate_username,
                email=email,
                first_name=first_name,
                last_name=last_name
            )
            user.set_unusable_password()
            user.save()
        else:
            # Actualizar nombres si estaban vacíos
            updated = False
            if not user.first_name and first_name:
                user.first_name = first_name
                updated = True
            if not user.last_name and last_name:
                user.last_name = last_name
                updated = True
            if not user.email and email:
                user.email = email
                updated = True
            if updated:
                user.save()

        # 4. Asegurar PerfilUsuario
        full_name = f"{user.first_name} {user.last_name}".strip() or user.username
        perfil, created = PerfilUsuario.objects.get_or_create(
            usuario=user,
            defaults={
                'nombre': full_name,
                'correo': email
            }
        )
        if not created:
            save_perfil = False
            if not perfil.nombre and full_name:
                perfil.nombre = full_name
                save_perfil = True
            if not perfil.correo and email:
                if not PerfilUsuario.objects.filter(correo__iexact=email).exclude(id=perfil.id).exists():
                    perfil.correo = email
                    save_perfil = True
            if save_perfil:
                try:
                    perfil.save()
                except Exception as e:
                    logger.warning(f"No se pudo actualizar email en perfil: {e}")

        # Guardar foto social de perfil (Google / GitHub) si no tiene una personalizada
        if social_avatar and (not perfil.imagen or perfil.imagen.name == 'default.jpg' or 'default' in str(perfil.imagen.name)):
            try:
                from django.core.files.base import ContentFile
                img_res = requests.get(social_avatar, timeout=6)
                if img_res.status_code == 200:
                    perfil.imagen.save(f"user_{user.id}_avatar.jpg", ContentFile(img_res.content), save=True)
            except Exception as img_err:
                logger.warning(f"No se pudo guardar la imagen de perfil social: {img_err}")

        # 5. Asegurar suscripción con plan gratuito si no existe
        plan_gratis = PlanSuscripcion.objects.filter(slug='gratis').first() or PlanSuscripcion.objects.filter(precio=0, activo=True).first()
        if plan_gratis:
            SuscripcionUsuario.objects.get_or_create(
                usuario=user,
                defaults={'plan': plan_gratis, 'estado': 'activa'}
            )

        # 6. Autenticar en la sesión
        user.backend = 'django.contrib.auth.backends.ModelBackend'
        login(request, user)

        display_name = user.first_name if user.first_name else user.username
        provider_display = 'Google' if provider == 'google' else 'GitHub'
        messages.success(request, f'¡Inicio de sesión exitoso con {provider_display}! Bienvenido a LitMate, {display_name}.')

        next_url = request.session.pop('social_auth_next', 'index')
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect('index')

    except Exception as e:
        logger.error(f"Error en social_login_callback ({provider}): {e}", exc_info=True)
        messages.error(request, f'Ocurrió un error inesperado al procesar el inicio de sesión con {provider.title()}.')
        return redirect('login')


def logout_view(request):
    if request.user.is_authenticated:
        logout(request)
        messages.info(request, 'Has cerrado sesión correctamente. ¡Hasta pronto!')
    return redirect('index')
@login_required
def perfil(request):
    """
    Panel de Usuario LitMate con 4 Secciones Especializadas:
    1. Mi Biblioteca (Favoritos, Leyendo, Leídos, Listas Personalizadas)
    2. Radar / Alertas de Precios y Ofertas
    3. Estadísticas de Lectura y Meta Anual
    4. Preferencias del Lector y Recomendaciones
    """
    try:
        perfil_user, _ = PerfilUsuario.objects.get_or_create(usuario=request.user)
    except Exception:
        perfil_user = None

    # 1. Mi Biblioteca: Favoritos, Estados y Listas
    favoritos = LibroFavorito.objects.filter(usuario=request.user).order_by('-fecha_agregado')
    
    try:
        listas = ListaLectura.objects.filter(usuario=request.user).prefetch_related('elementos').order_by('-fecha_creacion')
    except Exception:
        listas = []

    try:
        estados = EstadoLectura.objects.filter(usuario=request.user).select_related('libro')
        libros_leyendo = estados.filter(estado='leyendo')
        libros_leidos = estados.filter(estado='completado')
        libros_por_leer = estados.filter(estado='por_leer')
    except Exception:
        libros_leyendo = []
        libros_leidos = []
        libros_por_leer = []

    # 2. Radar de Ofertas & Seguimiento de Precios
    radar_libros = []
    base_radar_books = list(favoritos[:5])
    if len(base_radar_books) < 3:
        featured = get_featured_books()
        for f in featured[:4]:
            radar_libros.append({
                'id': f.get('google_id', ''),
                'titulo': f.get('titulo', ''),
                'autor': f.get('autor', ''),
                'portada': f.get('portada', ''),
                'precio_actual': f.get('precio_desde', '$14.990 CLP'),
                'precio_anterior': '$19.990 CLP',
                'descuento': '-25%',
                'tienda_top': 'Buscalibre',
                'tiendas': [
                    {'nombre': 'Buscalibre', 'precio': f.get('precio_desde', '$14.990 CLP'), 'url': 'https://www.buscalibre.cl', 'disponible': True, 'es_mejor': True},
                    {'nombre': 'Amazon', 'precio': 'USD $18.50 (~$17.800 CLP)', 'url': 'https://www.amazon.com', 'disponible': True, 'es_mejor': False},
                    {'nombre': 'Feria Chilena del Libro', 'precio': '$18.990 CLP', 'url': 'https://www.feriachilenadellibro.cl', 'disponible': True, 'es_mejor': False},
                ]
            })
    for fav in base_radar_books:
        radar_libros.append({
            'id': fav.google_id,
            'titulo': fav.titulo,
            'autor': fav.autores,
            'portada': fav.imagen_url or 'https://covers.openlibrary.org/b/id/8231856-L.jpg',
            'precio_actual': '$13.990 CLP',
            'precio_anterior': '$17.990 CLP',
            'descuento': '-22%',
            'tienda_top': 'Buscalibre',
            'tiendas': [
                {'nombre': 'Buscalibre', 'precio': '$13.990 CLP', 'url': 'https://www.buscalibre.cl', 'disponible': True, 'es_mejor': True},
                {'nombre': 'Amazon', 'precio': 'USD $16.99 (~$16.200 CLP)', 'url': 'https://www.amazon.com', 'disponible': True, 'es_mejor': False},
                {'nombre': 'Feria Chilena del Libro', 'precio': '$16.990 CLP', 'url': 'https://www.feriachilenadellibro.cl', 'disponible': True, 'es_mejor': False},
            ]
        })

    # 3. Estadísticas de Lectura (Calculadas a partir de los datos reales del usuario)
    meta_anual = getattr(perfil_user, 'meta_anual_libros', 12) if perfil_user else 12
    
    libros_leyendo_count = ElementoListaLectura.objects.filter(lista__usuario=request.user, estado_lectura='leyendo').count() + (libros_leyendo.count() if hasattr(libros_leyendo, 'count') else len(libros_leyendo))
    libros_leidos_count = ElementoListaLectura.objects.filter(lista__usuario=request.user, estado_lectura='completado').count() + (libros_leidos.count() if hasattr(libros_leidos, 'count') else len(libros_leidos))
    libros_planeo_count = ElementoListaLectura.objects.filter(lista__usuario=request.user, estado_lectura='por_leer').count() + (libros_por_leer.count() if hasattr(libros_por_leer, 'count') else len(libros_por_leer))
    total_guardados = favoritos.count() + ElementoListaLectura.objects.filter(lista__usuario=request.user).count()

    leidos_para_meta = max(libros_leidos_count, 1 if total_guardados > 0 else 0)
    progreso_meta_pct = min(100, int((leidos_para_meta / max(1, meta_anual)) * 100))
    paginas_leidas = (leidos_para_meta * 320) + (libros_leyendo_count * 150)
    tiempo_lectura_horas = max(1, paginas_leidas // 40)
    
    # Géneros disponibles y cálculo dinámico de estadísticas
    TODOS_GENEROS = [
        'Ciencia Ficción', 'Fantasía Épica', 'Literatura Clásica',
        'Filosofía & Ensayo', 'Misterio & Suspenso', 'Desarrollo Personal',
        'Novela Histórica', 'Terror & Gótico', 'Biografía'
    ]
    
    generos_guardados_str = getattr(perfil_user, 'genero_lector_preferido', '') or ''
    generos_seleccionados = [g.strip() for g in generos_guardados_str.split(',') if g.strip()] if generos_guardados_str else ['Ciencia Ficción', 'Literatura Clásica', 'Filosofía & Ensayo']
    
    COLORES_PALETA = ['var(--lm-teal)', 'var(--lm-ochre)', 'var(--lm-dark-wood)', 'var(--lm-oxide-red)']
    DISTRIBUCIONES = {
        1: [100],
        2: [60, 40],
        3: [45, 35, 20],
        4: [40, 30, 20, 10],
    }
    
    n_gen = min(len(generos_seleccionados), 4)
    pcts = DISTRIBUCIONES.get(n_gen, [40, 30, 20, 10])
    
    generos_stats = []
    for i, g_nombre in enumerate(generos_seleccionados[:4]):
        generos_stats.append({
            'nombre': g_nombre,
            'porcentaje': pcts[i] if i < len(pcts) else 10,
            'color': COLORES_PALETA[i % len(COLORES_PALETA)]
        })

    # 4. Historial de Búsquedas del Lector
    historial_busquedas = request.session.get('search_history', [])
    if not historial_busquedas:
        historial_busquedas = [
            {'query': 'Cien años de soledad', 'fecha': 'Hoy', 'total': 18, 'es_sugerido': True},
            {'query': 'Dune Frank Herbert', 'fecha': 'Ayer', 'total': 24, 'es_sugerido': True},
            {'query': 'Hábitos Atómicos', 'fecha': 'Esta semana', 'total': 12, 'es_sugerido': True},
            {'query': 'Ciencia Ficción Distópica', 'fecha': 'Esta semana', 'total': 36, 'es_sugerido': True},
        ]

    context = {
        'perfil_user': perfil_user,
        'favoritos': favoritos,
        'listas': listas,
        'libros_leyendo': libros_leyendo,
        'libros_leidos': libros_leidos,
        'libros_por_leer': libros_por_leer,
        'libros_leyendo_count': libros_leyendo_count,
        'libros_leidos_count': libros_leidos_count,
        'libros_planeo_count': libros_planeo_count,
        'total_guardados': total_guardados,
        'radar_libros': radar_libros,
        'meta_anual': meta_anual,
        'total_leidos_count': leidos_para_meta,
        'progreso_meta_pct': progreso_meta_pct,
        'paginas_leidas': paginas_leidas,
        'tiempo_lectura_horas': tiempo_lectura_horas,
        'generos_stats': generos_stats,
        'generos_disponibles': TODOS_GENEROS,
        'generos_seleccionados': generos_seleccionados,
        'historial_busquedas': historial_busquedas,
    }
    return render(request, 'core/perfil.html', context)

@login_required
def actualizar_preferencias_stats_api(request):
    """API para actualizar la meta anual de lectura y géneros preferidos del usuario."""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            perfil, _ = PerfilUsuario.objects.get_or_create(usuario=request.user)
            
            if 'meta_anual' in data:
                meta = int(data.get('meta_anual', 12))
                if meta > 0:
                    perfil.meta_anual_libros = meta
            
            if 'generos' in data:
                generos = data.get('generos', [])
                if isinstance(generos, list):
                    perfil.genero_lector_preferido = ','.join([g.strip() for g in generos if g.strip()])
                elif isinstance(generos, str):
                    perfil.genero_lector_preferido = generos.strip()

            perfil.save()
            return JsonResponse({'status': 'ok', 'msg': 'Preferencias de lectura y estadísticas actualizadas.'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'msg': str(e)}, status=500)
    return JsonResponse({'status': 'error', 'msg': 'Método no permitido'}, status=405)

@login_required
def crear_lista_api(request):
    """API para crear una nueva lista de lectura personalizada."""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            nombre = data.get('nombre', '').strip()
            descripcion = data.get('descripcion', '').strip()
            es_publica = bool(data.get('es_publica', False))
            
            if not nombre:
                return JsonResponse({'status': 'error', 'msg': 'El nombre de la lista es obligatorio.'}, status=400)
            
            lista = ListaLectura.objects.create(
                usuario=request.user,
                nombre=nombre,
                descripcion=descripcion,
                es_publica=es_publica
            )
            
            # Si se proporcionó un libro inicial para añadirlo inmediatamente
            google_id = data.get('google_id', '').strip()
            if google_id:
                ElementoListaLectura.objects.get_or_create(
                    lista=lista,
                    google_id=google_id,
                    defaults={
                        'titulo': data.get('titulo', 'Sin título'),
                        'autores': data.get('autores', ''),
                        'imagen_url': data.get('imagen_url', ''),
                        'estado_lectura': data.get('estado_lectura', 'por_leer')
                    }
                )

            return JsonResponse({
                'status': 'ok',
                'id': lista.id,
                'nombre': lista.nombre,
                'descripcion': lista.descripcion,
                'es_publica': lista.es_publica,
                'msg': f'Lista "{lista.nombre}" creada con éxito.'
            })
        except Exception as e:
            return JsonResponse({'status': 'error', 'msg': str(e)}, status=500)
    return JsonResponse({'status': 'error', 'msg': 'Método no permitido'}, status=405)

@login_required
def eliminar_lista_api(request, id):
    """API para eliminar una lista de lectura personalizada."""
    lista = get_object_or_404(ListaLectura, id=id, usuario=request.user)
    nombre = lista.nombre
    lista.delete()
    return JsonResponse({'status': 'ok', 'msg': f'Lista "{nombre}" eliminada correctamente.'})

@login_required
def obtener_mis_listas_api(request):
    """API que retorna las listas personalizadas del usuario con indicador de si contienen un libro específico y su estado de lectura."""
    book_id = request.GET.get('book_id', '').strip()
    listas = ListaLectura.objects.filter(usuario=request.user).prefetch_related('elementos').order_by('-fecha_creacion')
    
    estado_actual = 'por_leer'
    if book_id:
        est = EstadoLectura.objects.filter(usuario=request.user, libro__google_book_id=book_id).first()
        if est:
            estado_actual = est.estado
        else:
            elem = ElementoListaLectura.objects.filter(lista__usuario=request.user, google_id=book_id).first()
            if elem:
                estado_actual = elem.estado_lectura

    resultado = []
    for l in listas:
        contiene = False
        if book_id:
            contiene = l.elementos.filter(google_id=book_id).exists()
        resultado.append({
            'id': l.id,
            'nombre': l.nombre,
            'descripcion': l.descripcion,
            'es_publica': l.es_publica,
            'total_libros': l.elementos.count(),
            'contiene_libro': contiene
        })
    return JsonResponse({
        'status': 'ok',
        'listas': resultado,
        'estado_actual': estado_actual
    })

@login_required
def agregar_a_lista_api(request):
    """API para agregar o quitar un libro de una lista personalizada y actualizar su estado de lectura."""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            lista_id = data.get('lista_id')
            google_id = data.get('google_id', '').strip()
            estado_lectura = data.get('estado_lectura', 'por_leer')
            action = data.get('action', 'toggle')
            
            if not lista_id or not google_id:
                return JsonResponse({'status': 'error', 'msg': 'Faltan parámetros requeridos.'}, status=400)
                
            lista = get_object_or_404(ListaLectura, id=lista_id, usuario=request.user)
            
            elem = ElementoListaLectura.objects.filter(lista=lista, google_id=google_id).first()
            
            if elem:
                if action == 'remove' or (action == 'toggle' and not data.get('force_add')):
                    elem.delete()
                    return JsonResponse({
                        'status': 'ok',
                        'action': 'removed',
                        'msg': f'Libro quitado de "{lista.nombre}".'
                    })
                else:
                    elem.estado_lectura = estado_lectura
                    elem.save()
                    return JsonResponse({
                        'status': 'ok',
                        'action': 'updated',
                        'msg': f'Estado actualizado en "{lista.nombre}".'
                    })
            else:
                ElementoListaLectura.objects.create(
                    lista=lista,
                    google_id=google_id,
                    titulo=data.get('titulo', 'Sin título'),
                    autores=data.get('autores', ''),
                    imagen_url=data.get('imagen_url', ''),
                    estado_lectura=estado_lectura
                )
                return JsonResponse({
                    'status': 'ok',
                    'action': 'added',
                    'msg': f'¡Añadido a "{lista.nombre}"!'
                })
        except Exception as e:
            return JsonResponse({'status': 'error', 'msg': str(e)}, status=500)
    return JsonResponse({'status': 'error', 'msg': 'Método no permitido'}, status=405)

@login_required
def quitar_de_lista_api(request, id):
    """API para quitar un elemento específico de una lista."""
    elem = get_object_or_404(ElementoListaLectura, id=id, lista__usuario=request.user)
    titulo = elem.titulo
    lista_nombre = elem.lista.nombre
    elem.delete()
    return JsonResponse({'status': 'ok', 'msg': f'"{titulo}" quitado de "{lista_nombre}".'})

@login_required
def limpiar_historial_busqueda_api(request):
    """API para limpiar el historial de búsquedas del usuario."""
    request.session['search_history'] = []
    request.session.modified = True
    return JsonResponse({'status': 'ok', 'msg': 'Historial de búsqueda limpiado.'})

@login_required
def editar_perfil(request):
    perfil, _ = PerfilUsuario.objects.get_or_create(usuario=request.user)
    if request.method == 'POST':
        u_form = UserUpdateForm(request.POST, instance=request.user)
        p_form = ProfileUpdateForm(request.POST, request.FILES, instance=perfil)
        if u_form.is_valid() and p_form.is_valid():
            u_form.save()
            p_form.save()
            messages.success(request, '¡Tu perfil ha sido actualizado!')
            return redirect('perfil')
    else:
        u_form = UserUpdateForm(instance=request.user)
        p_form = ProfileUpdateForm(instance=perfil)
    return render(request, 'core/editar_perfil.html', {'u_form': u_form, 'p_form': p_form})

@csrf_exempt
@login_required
def agregar_favorito(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            favorito, created = LibroFavorito.objects.get_or_create(
                usuario=request.user,
                google_id=data.get('google_id'),
                defaults={
                    'titulo': data.get('titulo'),
                    'autores': data.get('autores'),
                    'imagen_url': data.get('imagen_url')
                }
            )
            return JsonResponse({'status': 'ok', 'msg': 'Añadido' if created else 'Ya existe'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'msg': str(e)})
    return JsonResponse({'status': 'error'})

@login_required
def eliminar_favorito(request, id):
    favorito = get_object_or_404(LibroFavorito, id=id, usuario=request.user)
    favorito.delete()
    messages.warning(request, 'Eliminado de favoritos.')
    return redirect('perfil')


# --- VISTAS STANDARD ---

def get_featured_books():
    """Retorna libros recomendados para el carrusel y escaparate de la página principal."""
    # Lista curada de alta calidad con portadas verificadas y permanentes
    curated_books = [
        {
            'id': 'curated_1',
            'google_id': 'zyTCAlFPjgYC',
            'isbn': '9788437604947',
            'titulo': 'Cien años de soledad',
            'autor': 'Gabriel García Márquez',
            'genero': 'Realismo Mágico',
            'editorial': 'Editorial Sudamericana',
            'ano': 1967,
            'paginas': 496,
            'rating': '4.9★',
            'precio_desde': '$14.990 CLP',
            'portada': 'https://covers.openlibrary.org/b/id/12627383-L.jpg',
            'sinopsis': 'Muchos años después, frente al pelotón de fusilamiento, el coronel Aureliano Buendía había de recordar aquella tarde remota en que su padre lo llevó a conocer el hielo. Macondo era entonces una aldea de veinte casas de barro y cañabrava...',
            'demo_texto': 'Adelanto de lectura — "Cien años de soledad" de Gabriel García Márquez:\n\nEl mundo era tan reciente, que muchas cosas carecían de nombre, y para mencionarlas había que señalarlas con el dedo. Todos los años, por el mes de marzo, una familia de gitanos desarrapados plantaba su carpa cerca de la aldea, y con un gran alboroto de pitos y timbales daban a conocer los nuevos inventos.',
            'partner_badge': 'Buscalibre'
        },
        {
            'id': 'curated_2',
            'google_id': 'B1hGBAAAQBAJ',
            'isbn': '9788466353779',
            'titulo': 'Dune',
            'autor': 'Frank Herbert',
            'genero': 'Ciencia Ficción',
            'editorial': 'Nova',
            'ano': 1965,
            'paginas': 704,
            'rating': '4.8★',
            'precio_desde': '$18.990 CLP',
            'portada': 'https://covers.openlibrary.org/b/id/11481354-L.jpg',
            'sinopsis': 'En el desértico planeta Arrakis, el agua es el bien más preciado y la codiciada especia melange es la sustancia que permite los viajes interestelares. El joven Paul Atreides deberá enfrentarse a conspiraciones imperiales para cumplir su destino...',
            'demo_texto': 'Adelanto de lectura — "Dune" de Frank Herbert:\n\n"No debo tener miedo. El miedo es el asesino de la mente. El miedo es la pequeña muerte que conduce a la destrucción total. Afrontaré mi miedo. Permitiré que pase sobre mí y a través de mí."',
            'partner_badge': 'Buscalibre'
        },
        {
            'id': 'curated_3',
            'google_id': 'kotPYEqx7kMC',
            'isbn': '9788499890944',
            'titulo': '1984',
            'autor': 'George Orwell',
            'genero': 'Distopía Clásica',
            'editorial': 'Debolsillo',
            'ano': 1949,
            'paginas': 352,
            'rating': '4.8★',
            'precio_desde': '$11.500 CLP',
            'portada': 'https://covers.openlibrary.org/b/id/8745958-L.jpg',
            'sinopsis': 'En una sociedad dominada por el Gran Hermano y la Policía del Pensamiento, Winston Smith trabaja en el Ministerio de la Verdad reescribiendo la historia. Pero su anhelo de libertad lo llevará a desafiar al Partido.',
            'demo_texto': 'Adelanto de lectura — "1984" de George Orwell:\n\nEra un día luminoso y frío de abril y los relojes daban las trece. Winston Smith, con la barbilla clavada en el pecho en su intento por escapar al viento cortante, se deslizó rápidamente por las puertas de cristal de las Casas de la Victoria.',
            'partner_badge': 'Buscalibre'
        },
        {
            'id': 'curated_4',
            'google_id': '9b7ZDAAAQBAJ',
            'isbn': '9788498381498',
            'titulo': 'El Principito',
            'autor': 'Antoine de Saint-Exupéry',
            'genero': 'Fábula Filosófica',
            'editorial': 'Salamandra',
            'ano': 1943,
            'paginas': 120,
            'rating': '4.9★',
            'precio_desde': '$8.990 CLP',
            'portada': 'https://covers.openlibrary.org/b/id/10570776-L.jpg',
            'sinopsis': 'Un piloto varado en el desierto del Sahara se encuentra con un pequeño príncipe que viaja de planeta en planeta. Una historia poética sobre la amistad, el amor y la importancia de ver las cosas con el corazón.',
            'demo_texto': 'Adelanto de lectura — "El Principito" de Antoine de Saint-Exupéry:\n\n"—Aquí está mi secreto. Es muy simple: solo con el corazón se puede ver bien; lo esencial es invisible a los ojos.\n—Lo esencial es invisible a los ojos —repitió el principito para acordarse."',
            'partner_badge': 'Buscalibre'
        },
        {
            'id': 'curated_5',
            'google_id': '8W_NDwAAQBAJ',
            'isbn': '9780062511409',
            'titulo': 'El Alquimista',
            'autor': 'Paulo Coelho',
            'genero': 'Espiritualidad & Aventura',
            'editorial': 'Grijalbo',
            'ano': 1988,
            'paginas': 192,
            'rating': '4.7★',
            'precio_desde': '$12.900 CLP',
            'portada': 'https://covers.openlibrary.org/b/id/10515159-L.jpg',
            'sinopsis': 'Santiago, un joven pastor andaluz, emprende un viaje hacia las pirámides de Egipto en busca de un tesoro soñado. En el camino aprenderá a escuchar a su corazón y a descifrar el lenguaje de las señales universales.',
            'demo_texto': 'Adelanto de lectura — "El Alquimista" de Paulo Coelho:\n\n"Cuando quieres algo, todo el universo conspira para que realices tu deseo. Escucha a tu corazón. Él conoce todas las cosas, porque proviene del Alma del Mundo y un día retornará a ella."',
            'partner_badge': 'Buscalibre'
        },
        {
            'id': 'curated_6',
            'google_id': 'vf0_EAAAQBAJ',
            'isbn': '9788418118036',
            'titulo': 'Hábitos Atómicos',
            'autor': 'James Clear',
            'genero': 'Desarrollo Personal',
            'editorial': 'Paidós',
            'ano': 2018,
            'paginas': 336,
            'rating': '4.9★',
            'precio_desde': '$16.900 CLP',
            'portada': 'https://covers.openlibrary.org/b/id/12539702-L.jpg',
            'sinopsis': 'Un marco probado para mejorar un 1% cada día. James Clear explica cómo los pequeños cambios cotidianos producen resultados extraordinarios a lo largo del tiempo, eliminando hábitos negativos y adoptando rutinas exitosas.',
            'demo_texto': 'Adelanto de lectura — "Hábitos Atómicos" de James Clear:\n\n"Los cambios que parecen pequeños y poco importantes al principio se convertirán en resultados notables si estás dispuesto a mantenerlos durante años. Eres lo que haces repetidamente."',
            'partner_badge': 'Buscalibre'
        }
    ]
    
    # Enriquecer con scraping real de tiendas
    from core.models import PrecioLibroTienda
    from core.scraper import obtener_datos_comparador_libro

    for cb in curated_books:
        precios_bd = list(PrecioLibroTienda.objects.filter(titulo_referencia__iexact=cb['titulo'], es_enlace_directo=True))
        if not precios_bd:
            try:
                res_scraper = obtener_datos_comparador_libro(
                    titulo=cb['titulo'],
                    autor=cb['autor'],
                    google_id=cb.get('google_id'),
                    isbn=cb.get('isbn')
                )
                if res_scraper.get('tiendas'):
                    precios_bd = list(PrecioLibroTienda.objects.filter(titulo_referencia__iexact=cb['titulo'], es_enlace_directo=True))
            except Exception as e:
                logger.warning(f"Error scraping libro recomendado {cb['titulo']}: {e}")

        if precios_bd:
            precio_min = min(p.precio_actual for p in precios_bd if p.precio_actual > 0)
            cb['precio_desde'] = f"${precio_min:,.0f} CLP".replace(',', '.')
            tienda_min = min(precios_bd, key=lambda p: p.precio_actual)
            cb['partner_badge'] = tienda_min.tienda.split(' ')[0]
            cb['tiendas'] = [
                {
                    'tienda': p.tienda,
                    'precio_clp': p.precio_actual,
                    'precio_formateado': f"${p.precio_actual:,.0f} CLP".replace(',', '.'),
                    'formato': p.formato,
                    'disponibilidad': p.disponibilidad,
                    'url': p.enlace_directo,
                    'es_directo': True
                }
                for p in precios_bd
            ]
        else:
            cb['tiendas'] = generar_enlaces_tiendas(cb['titulo'], cb['autor'], cb['google_id'], 14990, isbn=cb.get('isbn'))
            
    return curated_books


def index(request): 
    libros_destacados = get_featured_books()
    return render(request, 'index.html', {'libros_destacados': libros_destacados})

def about(request): 
    return render(request, 'about.html')

def post(request): 
    return render(request, 'post.html')

def chatbot_page(request): 
    return render(request, 'chatbot.html')

@ratelimit(limit=4, period=300, key_prefix='contact')
def contact(request):
    if request.method == 'POST':
        # Anti-spam Honeypot Check
        if check_honeypot(request):
            messages.success(request, '¡Tu mensaje ha sido enviado con éxito!')
            return redirect('contact')

        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        message_text = request.POST.get('message', '').strip()

        if not name or not email or not message_text:
            messages.error(request, 'Por favor completa todos los campos requeridos (Nombre, Correo y Mensaje).')
            return render(request, 'contact.html', {
                'name': name,
                'email': email,
                'phone': phone,
                'message_text': message_text
            })

        # 1. Guardar mensaje en Base de Datos TiDB Cloud
        try:
            msg_obj = MensajeContacto.objects.create(
                nombre=name,
                email=email,
                telefono=phone,
                mensaje=message_text
            )
            logger.info(f"Nuevo mensaje de contacto guardado: ID {msg_obj.id} de {name} ({email})")
        except Exception as db_err:
            logger.error(f"Error guardando mensaje de contacto en BD: {db_err}")

        # 2. Despachar correo de notificación al administrador (litmateproject@gmail.com)
        try:
            admin_subject = f"[LitMate Contacto] Nuevo mensaje de {name}"
            admin_body = (
                f"Has recibido una nueva consulta desde el formulario web de LitMate:\n\n"
                f"👤 Nombre: {name}\n"
                f"📧 Correo Electrónico: {email}\n"
                f"📞 Teléfono: {phone if phone else 'No proporcionado'}\n"
                f"📅 Fecha: {timezone.now().strftime('%d/%m/%Y %H:%M')}\n\n"
                f"💬 Mensaje:\n"
                f"--------------------------------------------------\n"
                f"{message_text}\n"
                f"--------------------------------------------------\n"
            )
            send_mail(
                subject=admin_subject,
                message=admin_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[getattr(settings, 'EMAIL_HOST_USER', 'litmateproject@gmail.com')],
                fail_silently=True
            )
        except Exception as mail_err:
            logger.warning(f"No se pudo enviar notificación al admin: {mail_err}")

        # 3. Despachar acuse de recibo automático al usuario
        try:
            user_subject = "Hemos recibido tu mensaje - LitMate"
            user_body = (
                f"Hola {name},\n\n"
                f"Muchas gracias por ponerte en contacto con el equipo de LitMate.\n\n"
                f"Hemos recibido tu consulta correctamente y nos pondremos en contacto contigo a la brevedad.\n\n"
                f"Resumen de tu mensaje:\n"
                f"\"{message_text}\"\n\n"
                f"Atentamente,\n"
                f"El equipo de LitMate\n"
                f"litmateproject@gmail.com"
            )
            send_mail(
                subject=user_subject,
                message=user_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=True
            )
        except Exception as user_mail_err:
            logger.warning(f"No se pudo enviar confirmación al usuario: {user_mail_err}")

        messages.success(request, '¡Tu mensaje ha sido enviado con éxito! Te responderemos a la brevedad por correo.')
        return redirect('contact')

    return render(request, 'contact.html')

def terminos_condiciones(request):
    return render(request, 'legal/terminos.html')

def politica_privacidad(request):
    return render(request, 'legal/privacidad.html')

def politica_cookies(request):
    return render(request, 'legal/cookies.html')

def buscar_libros(request):
    """
    Vista principal de exploración y comparador de precios de libros.
    Utiliza el motor híbrido (Base de Datos TiDB Cloud + Google Books API / Open Library resiliente).
    """
    query = request.GET.get('q', '').strip()
    author = request.GET.get('author', '').strip()
    genre = request.GET.get('genre', '').strip()
    year = request.GET.get('year', '').strip()
    order = request.GET.get('order', '').strip()

    # Si no hay filtros aplicados, traemos una selección destacada inicial
    busqueda_activa = bool(query or author or genre or year or order)
    
    libros = buscar_libros_hibrido(
        query=query,
        author=author,
        genre=genre,
        year=year,
        order=order,
        max_results=36
    )

    # Registrar evento de analítica si hubo búsqueda activa
    if busqueda_activa:
        try:
            EventoAnalitica.objects.create(
                usuario=request.user if hasattr(request, 'user') and request.user.is_authenticated else None,
                session_key=request.session.session_key or 'anon_explorer',
                tipo_evento='busqueda_explorar',
                modulo='explorar_catalogo',
                detalles_evento={
                    'query': query,
                    'author': author,
                    'genre': genre,
                    'year': year,
                    'order': order,
                    'total_encontrados': len(libros)
                },
                ip_origen=request.META.get('REMOTE_ADDR')
            )
        except Exception as e:
            logger.warning(f"No se pudo registrar evento de analítica: {e}")

    # Registrar búsqueda en historial de sesión
    if query:
        historial = request.session.get('search_history', [])
        # Filtrar duplicados del mismo término
        historial = [h for h in historial if h.get('query', '').strip().lower() != query.lower()]
        historial.insert(0, {
            'query': query,
            'fecha': timezone.now().strftime('%d %b, %H:%M'),
            'total': len(libros),
            'es_sugerido': False
        })
        request.session['search_history'] = historial[:15]
        request.session.modified = True

    # Obtener listas creadas por el usuario autenticado
    listas_usuario = []
    if request.user.is_authenticated:
        listas_usuario = ListaLectura.objects.filter(usuario=request.user).order_by('-fecha_creacion')

    # Obtener géneros consolidados de la base de datos
    generos_set = set(Genero.objects.values_list('nombre', flat=True))
    generos_libros = set(Libro.objects.values_list('genero', flat=True).distinct())
    todos_generos = sorted(list(generos_set.union(generos_libros)))
    if not todos_generos:
        todos_generos = ["Ciencia Ficción", "Fantasía", "Terror", "Misterio", "Literatura Clásica", "Desarrollo Personal", "Juvenil / Aventura", "Filosofía", "Historia", "Romance"]

    # Píldoras de géneros rápidos más destacados
    generos_destacados = [
        "Fantasía", "Ciencia Ficción", "Terror", "Misterio", 
        "Literatura Clásica", "Desarrollo Personal", "Juvenil / Aventura", "Filosofía"
    ]

    return render(request, 'buscar_libros.html', {
        'libros': libros,
        'valores_busqueda': request.GET,
        'busqueda_activa': busqueda_activa,
        'generos': todos_generos,
        'generos_destacados': generos_destacados,
        'listas_usuario': listas_usuario,
        'años': range(datetime.date.today().year, 1950, -1),
    })


@csrf_exempt
def track_conversion_click(request):
    """
    Endpoint para registrar clics a librerías externas (Buscalibre, Google Books, Amazon).
    Permite monetización por afiliados y analítica de conversión comercial.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'msg': 'Método no permitido'}, status=405)

    try:
        data = json.loads(request.body)
        titulo_libro = data.get('titulo', 'Libro')
        proveedor = data.get('proveedor', 'Buscalibre')
        url_destino = data.get('url', '')
        precio_ref = Decimal(str(data.get('precio', '0')))
        google_id = data.get('google_id')

        # Buscar si el libro existe en la base de datos
        libro_obj = None
        if google_id:
            libro_obj = Libro.objects.filter(google_book_id=google_id).first()
        if not libro_obj and titulo_libro:
            libro_obj = Libro.objects.filter(titulo__icontains=titulo_libro).first()

        ClickConversion.objects.create(
            usuario=request.user if request.user.is_authenticated else None,
            libro=libro_obj,
            proveedor=proveedor,
            url_destino=url_destino,
            precio_referencia=precio_ref
        )

        return JsonResponse({'status': 'ok', 'msg': 'Conversión registrada'})
    except Exception as e:
        logger.error(f"Error registrando conversión: {e}")
        return JsonResponse({'status': 'error', 'msg': str(e)}, status=400)


@csrf_exempt
def api_precios_libro(request):
    """
    Endpoint para consultar precios escrapeados y enlaces directos de un libro.
    Soporta parámetros GET o POST: libro_id, titulo, autor, google_id, isbn, force.
    """
    if request.method == 'POST':
        try:
            body_data = json.loads(request.body) if request.body else {}
        except Exception:
            body_data = request.POST.dict()
    else:
        body_data = request.GET.dict()

    libro_id = body_data.get('libro_id') or body_data.get('id')
    titulo = body_data.get('titulo', '').strip()
    autor = body_data.get('autor', '').strip()
    google_id = body_data.get('google_id', '').strip()
    isbn = body_data.get('isbn', '').strip()
    force_refresh = str(body_data.get('force', '')).lower() in ('true', '1')

    if not libro_id and not titulo and not google_id:
        return JsonResponse({'status': 'error', 'msg': 'Faltan parámetros de búsqueda (libro_id, titulo o google_id)'}, status=400)

    try:
        from core.scraper import obtener_datos_comparador_libro
        datos = obtener_datos_comparador_libro(
            libro_id=libro_id,
            titulo=titulo,
            autor=autor,
            google_id=google_id,
            isbn=isbn,
            force_refresh=force_refresh
        )
        return JsonResponse(datos)
    except Exception as e:
        logger.error(f"Error en api_precios_libro: {e}")
        return JsonResponse({'status': 'error', 'msg': str(e)}, status=500)


@csrf_exempt
@login_required
def actualizar_estado_lectura(request):
    """Permite al usuario marcar un libro como 'por_leer', 'leyendo' o 'completado'."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'msg': 'Método no permitido'}, status=405)

    try:
        data = json.loads(request.body)
        google_id = data.get('google_id')
        titulo = data.get('titulo', 'Libro')
        autor_nom = data.get('autor', 'Autor')
        nuevo_estado = data.get('estado', 'por_leer')

        libro_obj = None
        if google_id:
            libro_obj = Libro.objects.filter(google_book_id=google_id).first()

        if not libro_obj:
            autor_obj, _ = Autor.objects.get_or_create(nombre=autor_nom)
            libro_obj, _ = Libro.objects.get_or_create(
                google_book_id=google_id,
                defaults={
                    'titulo': titulo,
                    'autor': autor_obj,
                    'sinopsis': data.get('sinopsis', ''),
                    'portada_url': data.get('imagen_url', '')
                }
            )

        p_avance = 100.0 if nuevo_estado == 'completado' else (50.0 if nuevo_estado == 'leyendo' else 0.0)
        
        estado_obj, created = EstadoLectura.objects.update_or_create(
            usuario=request.user,
            libro=libro_obj,
            defaults={
                'estado': nuevo_estado,
                'porcentaje_avance': p_avance,
                'fecha_inicio': timezone.now() if nuevo_estado in ['leyendo', 'completado'] else None,
                'fecha_termino': timezone.now() if nuevo_estado == 'completado' else None,
            }
        )

        return JsonResponse({
            'status': 'ok',
            'msg': f'Marcado como {estado_obj.get_estado_display()}',
            'estado': nuevo_estado
        })
    except Exception as e:
        logger.error(f"Error actualizando estado de lectura: {e}")
        return JsonResponse({'status': 'error', 'msg': str(e)}, status=400)


def detalle_libro_demo(request, book_id):
    """Retorna los datos completos de demo, resumen y tiendas para el modal interactivo."""
    libro = Libro.objects.filter(google_book_id=book_id).first()
    if libro:
        tiendas = generar_enlaces_tiendas(libro.titulo, libro.autor.nombre, google_id=libro.google_book_id)
        return JsonResponse({
            'status': 'ok',
            'titulo': libro.titulo,
            'autor': libro.autor.nombre,
            'editorial': libro.editorial.nombre if libro.editorial else 'N/A',
            'genero': libro.genero,
            'paginas': libro.paginas,
            'año': str(libro.fecha_publicacion.year) if libro.fecha_publicacion else 'N/A',
            'sinopsis': libro.sinopsis,
            'demo_extracto': generar_demo_extracto(libro_obj=libro, sinopsis=libro.sinopsis, titulo=libro.titulo, autor=libro.autor.nombre),
            'portada': libro.portada_url,
            'calificacion': libro.calificacion_promedio,
            'total_resenas': libro.total_resenas,
            'tiendas': tiendas
        })

    return JsonResponse({'status': 'error', 'msg': 'Libro no encontrado en catálogo'}, status=404)


# --- LÓGICA CHATBOT ---

def obtener_historial_sesion(request):
    """Obtiene los últimos mensajes del usuario para mantener la memoria conversacional."""
    historial = []
    if hasattr(request, 'user') and request.user.is_authenticated:
        mensajes_db = MensajeIA.objects.filter(conversacion__usuario=request.user).order_by('-fecha_envio')[:8]
        for m in reversed(mensajes_db):
            historial.append({'rol': m.rol, 'contenido': m.contenido})
    else:
        if hasattr(request, 'session'):
            if 'chat_history' not in request.session:
                request.session['chat_history'] = []
            historial = request.session.get('chat_history', [])[-8:]
    return historial

def guardar_historial_sesion(request, mensaje_usuario, respuesta_bot):
    try:
        if hasattr(request, 'user') and request.user.is_authenticated:
            conv, _ = ConversacionIA.objects.get_or_create(
                usuario=request.user,
                defaults={'titulo': mensaje_usuario[:40]}
            )
            MensajeIA.objects.create(conversacion=conv, rol='user', contenido=mensaje_usuario)
            MensajeIA.objects.create(conversacion=conv, rol='assistant', contenido=respuesta_bot)
            conv.ultima_actividad = timezone.now()
            conv.save(update_fields=['ultima_actividad'])
        elif hasattr(request, 'session'):
            if 'chat_history' not in request.session:
                request.session['chat_history'] = []
            request.session['chat_history'].append({'rol': 'user', 'contenido': mensaje_usuario})
            request.session['chat_history'].append({'rol': 'assistant', 'contenido': respuesta_bot})
            if len(request.session['chat_history']) > 20:
                request.session['chat_history'] = request.session['chat_history'][-20:]
            if hasattr(request.session, 'modified'):
                request.session.modified = True
    except Exception as e:
        logger.error(f"Error guardando sesión: {e}")


def limpiar_simbolos_markdown(texto):
    """Elimina asteriscos (*) y numerales (#) de las respuestas de la IA y normaliza comillas."""
    if not texto:
        return ""
    # Quitar etiquetas de encabezados (# Título -> Título)
    texto = re.sub(r'^[ \t]*#+[ \t]*', '', texto, flags=re.MULTILINE)
    # Quitar asteriscos de negrita y cursiva
    texto = re.sub(r'\*\*(.*?)\*\*', r'\1', texto)
    texto = re.sub(r'\*(.*?)\*', r'\1', texto)
    # Quitar cualquier asterisco o numeral remanente
    texto = texto.replace('*', '').replace('#', '')
    # Normalizar comillas repetidas (""Texto"" -> "Texto")
    texto = re.sub(r'"{2,}', '"', texto)
    return texto.strip()


def extraer_palabras_clave_busqueda(query):
    """Limpia frases interrogativas para extraer palabras clave precisas de búsqueda."""
    frases_a_limpiar = [
        r'\bbusco un libro que trata de\b',
        r'\bbusco un libro donde\b',
        r'\bbusco un libro de\b',
        r'\bbusco un libro sobre\b',
        r'\bbusco un libro\b',
        r'\bcomo se llama el libro donde\b',
        r'\bcomo se llama el libro que\b',
        r'\bcomo se llama el libro de\b',
        r'\bcomo se llama el libro\b',
        r'\brecuerdo un libro donde\b',
        r'\brecuerdo un libro que\b',
        r'\brecuerdo un libro\b',
        r'\bno me acuerdo del titulo pero\b',
        r'\bno recuerdo el titulo pero\b',
        r'\buna novela donde\b',
        r'\bun libro donde\b',
        r'\bun libro que\b',
        r'\bquien escribio el libro de\b',
    ]
    limpio = query.lower()
    for f in frases_a_limpiar:
        limpio = re.sub(f, '', limpio, flags=re.IGNORECASE)
    limpio = re.sub(r'[¿?¡!.,;:"]+', ' ', limpio).strip()
    return limpio if len(limpio) > 2 else query

import time

# =====================================================================
# BÚSQUEDA WEB EN TIEMPO REAL (GROUNDING ESTILO GOOGLE AI OVERVIEW)
# =====================================================================
def buscar_informacion_web_en_vivo(query):
    """
    Realiza una búsqueda web en tiempo real consultando Wikipedia y DuckDuckGo
    sin requerir API Keys pagadas. Extrae títulos, resúmenes y contexto factual
    para alimentar a la IA cuando el catálogo local no tiene la respuesta exacta.
    """
    snippets = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    # 1. Búsqueda semántica en Wikipedia API (Resúmenes de libros, autores y crímenes históricos)
    try:
        wiki_url = f"https://es.wikipedia.org/w/api.php?action=opensearch&search={requests.utils.quote(query + ' libro')}&limit=3&namespace=0&format=json"
        res_wiki = requests.get(wiki_url, headers=headers, timeout=4)
        if res_wiki.ok:
            data_wiki = res_wiki.json()
            titulos = data_wiki[1] if len(data_wiki) > 1 else []
            descripciones = data_wiki[2] if len(data_wiki) > 2 else []
            for tit, desc in zip(titulos, descripciones):
                if desc and len(desc) > 30 and not "desambiguación" in desc.lower():
                    snippets.append(f"Wikipedia ({tit}): {desc[:280]}")
    except Exception as e:
        logger.warning(f"Error búsqueda Wikipedia: {e}")

    # 2. Búsqueda web abierta en DuckDuckGo HTML (Para capturar novelas, ficción y crímenes reales)
    try:
        ddg_url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query + ' libros recomendados sinopsis')}"
        res_ddg = requests.get(ddg_url, headers=headers, timeout=4)
        if res_ddg.ok:
            # Extraer los resúmenes limpios de los primeros 3 resultados
            raw_snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', res_ddg.text, re.DOTALL)
            for snip in raw_snippets[:3]:
                texto_limpio = re.sub(r'<[^>]+>', '', snip)
                texto_limpio = re.sub(r'\s+', ' ', texto_limpio).strip()
                if len(texto_limpio) > 40:
                    snippets.append(f"Web: {texto_limpio[:250]}")
    except Exception as e:
        logger.warning(f"Error búsqueda DuckDuckGo: {e}")

    return "\n".join(snippets[:4])


# =====================================================================
# ENDPOINT PRINCIPAL DEL CHATBOT CON STREAMING Y GROUNDING WEB
# =====================================================================
@csrf_exempt
@ratelimit(limit=30, period=60, key_prefix='chatbot_query', json_response=True)
def chatbot_query(request):
    """
    Endpoint del Asistente Literario LitMate con Streaming SSE.
    Combina catálogo interno, búsqueda web en vivo en tiempo real (Google AI style)
    y selector prioritario de modelos LLM.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    try:
        data = json.loads(request.body)
        user_message = data.get('message', '').strip()

        if not user_message:
            return JsonResponse({'response': "¡Hola! ¿En qué lectura u obra puedo ayudarte hoy?"})
        # =====================================================================
        # CONTROL DE CUOTA DIARIA POR PLAN
        # =====================================================================
        cuota_ok, info_cuota = verificar_y_consumir_cuota(request)
        if not cuota_ok:
            mensaje_bloqueo = (
                f"Has alcanzado el límite diario de consultas de tu {info_cuota['plan']} "
                f"({info_cuota['limite']} mensajes al día). Tu cuota se reiniciará a la medianoche. "
                "Para obtener consultas ilimitadas y análisis literarios avanzados, mejora tu suscripción."
            )
            return JsonResponse({
                'error': 'quota_exceeded',
                'response': mensaje_bloqueo,
                'info_cuota': info_cuota
            }, status=429)
        if not request.session.session_key:
            request.session.save()

        historial = obtener_historial_sesion(request)
        contexto_extra = ""
        libros_sugeridos = []

        msg_limpio = user_message.lower().strip()
        
        # Detección de saludos iniciales
        saludos = ['hola', 'buenos dias', 'buenas tardes', 'buenas noches', 'que tal', 'hey', 'saludos']
        es_saludo = any(msg_limpio == s or msg_limpio.startswith(s + ' ') for s in saludos) and len(user_message) < 25

        # Detección de confirmaciones cortas o continuidad de hilo
        palabras_continuacion = [
            'si', 'sí', 'claro', 'por favor', 'ok', 'dale', 'bueno', 'vale', 'no',
            'resumen', 'analisis', 'análisis', 'detalle', 'detalles', 'mas', 'más',
            'el primero', 'el segundo', 'el tercero', 'profundiza', 'cuentame', 'cuéntame'
        ]
        es_continuacion = any(
            msg_limpio == p or msg_limpio.startswith(p + ' ') or msg_limpio.startswith('si ')
            for p in palabras_continuacion
        ) or (len(msg_limpio.split()) <= 2 and len(msg_limpio) <= 12)

        # Si es una búsqueda temática real, activar Grounding en catálogo y en la web en vivo
        if not es_saludo and not es_continuacion:
            query_busqueda = extraer_palabras_clave_busqueda(user_message)

            # 1. Catálogo local
            libros_sugeridos = buscar_libros_hibrido(query=query_busqueda, max_results=3)
            if libros_sugeridos:
                contexto_extra += "Obras disponibles en catálogo LitMate:\n"
                for b in libros_sugeridos:
                    contexto_extra += f"- \"{b['titulo']}\" de {b['autor_str']}. Precio: {b.get('precio_desde', '$14.990 CLP')}.\n"

            # 2. Búsqueda Web en Vivo (Grounding)
            datos_web = buscar_informacion_web_en_vivo(query_busqueda)
            if datos_web:
                contexto_extra += f"\nResultados de búsqueda web en tiempo real (Google AI Grounding):\n{datos_web}\n"

            # 3. Embeddings en Pinecone (si está activo)
            embedding_model, pinecone_index = get_ai_resources()
            if pinecone_index and embedding_model:
                try:
                    query_embedding = embedding_model.encode(query_busqueda).tolist()
                    search_results = pinecone_index.query(vector=query_embedding, top_k=2, include_metadata=True)
                    if search_results.get('matches'):
                        for match in search_results.get('matches', []):
                            if match.get('score', 0) > getattr(settings, 'LITMATE_SCORE_THRESHOLD', 0.30):
                                meta = match.get('metadata', {})
                                contexto_extra += f"- {meta.get('title', 'Libro')}: {meta.get('text', '')[:100]}...\n"
                except Exception as e:
                    logger.warning(f"Búsqueda Pinecone: {e}")

        user_info = ""
        if hasattr(request, 'user') and request.user.is_authenticated:
            nombre = request.user.first_name or request.user.username
            user_info = f"Nombre del usuario: {nombre}."

        api_key = os.getenv('GROQ_API_KEY') or getattr(settings, 'GROQ_API_KEY', '')

        system_prompt = (
            "Eres LitMate, un asistente literario de vanguardia. Te comportas como un motor de búsqueda literario inteligente con visión general (estilo Google AI Overview).\n\n"
            "DIRECTRICES DE RESPUESTA Y GROUNDING:\n"
            "1. USO DE BÚSQUEDA WEB: Utiliza la información de búsqueda web en tiempo real proporcionada para recomendar libros reales, exactos y canónicos de la temática solicitada (por ejemplo, si piden crímenes o asesinatos en Rusia, usa obras como 'Crimen y castigo' de Dostoyevski, 'El niño 44' de Tom Rob Smith o crónicas sobre Andréi Chikatilo).\n"
            "2. FORMATO AI OVERVIEW (CUANDO PIDEN RECOMENDACIONES):\n"
            "   - Inicia con una síntesis directa categorizando las opciones (ej: Ficción y Novela Negra vs. Crónica y Asesinos Reales).\n"
            "   - Breve descripción de cada obra recomendada (1 o 2 líneas explicando por qué se ajusta a lo que pidió).\n"
            "   - AL FINAL, incluye obligatoriamente las 3 tarjetas de libros en líneas separadas con este formato exacto:\n"
            "     [LIBRO: Título del libro | Nombre del Autor | $14.990 CLP]\n"
            "   - Cierra con una frase breve invitando a profundizar o pedir un resumen de cualquiera de ellos.\n"
            "3. MEMORIA CONVERSACIONAL: Si el usuario responde con 'sí', 'cuéntame más', 'el primero' o hace una pregunta de seguimiento, NO pongas tarjetas [LIBRO:...]; profundiza en el análisis de la obra que eligió con rigor literario.\n"
            "4. PROHIBICIONES ESTRICTAS:\n"
            "   - NUNCA digas que no puedes proporcionar imágenes con derechos de autor (el frontend web se encarga de mostrar las portadas).\n"
            "   - No uses asteriscos (*) ni numerales (#).\n"
            "   - No escribas enlaces URL en tu texto explicativo.\n"
            "   - Títulos siempre entre comillas dobles. Habla siempre en español."
        )

        if user_info:
            system_prompt += f"\n\nPerfil del usuario: {user_info}"
        if contexto_extra:
            system_prompt += f"\n\nContexto factual y búsqueda en vivo:\n{contexto_extra}"

        mensajes_payload = [{"role": "system", "content": system_prompt}]
        for m_hist in historial:
            rol_llm = "assistant" if m_hist['rol'] in ["assistant", "bot"] else "user"
            mensajes_payload.append({"role": rol_llm, "content": m_hist['contenido']})
        mensajes_payload.append({"role": "user", "content": user_message})

        def event_stream():
            full_content = []
            stream_started = False

            if api_key:
                try:
                    client = Groq(api_key=api_key)

                    modelos_candidatos = [
                        "llama-3.3-70b-versatile",
                        "deepseek-r1-distill-llama-70b",
                        "qwen-2.5-32b",
                        "llama-3.1-8b-instant",
                        "openai/gpt-oss-120b",
                        "openai/gpt-oss-20b",
                        "groq/compound",
                        "qwen/qwen3.6-27b"
                    ]

                    for modelo in modelos_candidatos:
                        try:
                            stream_response = client.chat.completions.create(
                                messages=mensajes_payload,
                                model=modelo,
                                temperature=0.35,
                                max_tokens=1800,
                                stream=True
                            )
                            
                            in_think_block = False

                            for chunk in stream_response:
                                delta = chunk.choices[0].delta.content or ""
                                if delta:
                                    if "<think>" in delta:
                                        in_think_block = True
                                        delta = delta.split("<think>")[0]
                                    if "</think>" in delta:
                                        in_think_block = False
                                        delta = delta.split("</think>")[-1]

                                    if in_think_block or not delta:
                                        continue

                                    stream_started = True
                                    clean_delta = delta.replace('*', '').replace('#', '')
                                    full_content.append(clean_delta)
                                    yield f"data: {json.dumps({'token': clean_delta})}\n\n"
                            
                            if stream_started:
                                break
                        except Exception as mod_err:
                            logger.warning(f"Error con modelo {modelo}: {mod_err}")
                except Exception as client_err:
                    logger.error(f"Error cliente Groq: {client_err}")

            if not stream_started:
                if es_saludo:
                    fallback_text = "¡Hola! Qué gusto saludarte. Soy LitMate, tu compañera de lectura. ¿Qué temática o libro te gustaría explorar hoy?"
                else:
                    fallback_text = "Disculpa, tuve un problema momentáneo de conexión con la IA. ¿Podrías repetir tu última pregunta?"

                for palabra in fallback_text.split(" "):
                    yield f"data: {json.dumps({'token': palabra + ' '})}\n\n"
                    time.sleep(0.015)
                full_content.append(fallback_text)

            respuesta_completa = limpiar_simbolos_markdown("".join(full_content))
            guardar_historial_sesion(request, user_message, respuesta_completa)
            yield "data: [DONE]\n\n"

        response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response

    except Exception as e:
        logger.error(f"Error en chatbot_query: {e}")
        return JsonResponse({'response': "Ocurrió un error inesperado al procesar tu consulta."}, status=500)


def quick_search_api(request):
    """
    Endpoint ultrarrápido para el Command Palette / Búsqueda Global (Ctrl+K).
    Retorna atajos de navegación y resultados coincidentes de libros y autores.
    """
    query = request.GET.get('q', '').strip()
    
    # 1. Atajos de navegación rápidos en la plataforma
    shortcuts_all = [
        {'title': 'Explorar Catálogo', 'desc': 'Buscar libros, filtrar por género y comparar precios', 'url': '/libros/', 'icon': 'iconoir-open-book', 'category': 'Navegación'},
        {'title': 'Asistente IA (Chatbot)', 'desc': 'Conversar con el recomendador inteligente de lecturas', 'url': '/chat/', 'icon': 'iconoir-sparks', 'category': 'Inteligencia Artificial'},
        {'title': 'Planes y Precios', 'desc': 'Conoce las membresías Premium y suscripciones', 'url': '/suscripciones/planes/', 'icon': 'iconoir-crown', 'category': 'Membresías'},
        {'title': 'Novedades y Artículos', 'desc': 'Explorar el blog y publicaciones literarias', 'url': '/post/', 'icon': 'iconoir-journal', 'category': 'Comunidad'},
        {'title': 'Sobre Nosotros', 'desc': 'Conoce la misión y el equipo detrás de LitMate', 'url': '/about/', 'icon': 'iconoir-info-circle', 'category': 'Información'},
        {'title': 'Contacto y Soporte', 'desc': 'Envíanos un mensaje o sugerencia', 'url': '/contact/', 'icon': 'iconoir-mail', 'category': 'Soporte'},
    ]
    
    if hasattr(request, 'user') and request.user.is_authenticated:
        shortcuts_all.insert(0, {'title': 'Mi Perfil & Favoritos', 'desc': 'Ver tus libros guardados y progreso de lectura', 'url': '/perfil/', 'icon': 'iconoir-user', 'category': 'Cuenta'})
    else:
        shortcuts_all.append({'title': 'Iniciar Sesión / Registro', 'desc': 'Accede a tu cuenta de lector', 'url': '/login/', 'icon': 'iconoir-log-in', 'category': 'Cuenta'})

    filtered_shortcuts = []
    q_lower = query.lower()
    if query:
        for s in shortcuts_all:
            if q_lower in s['title'].lower() or q_lower in s['desc'].lower() or q_lower in s['category'].lower():
                filtered_shortcuts.append(s)
    else:
        filtered_shortcuts = shortcuts_all[:4]

    # 2. Búsqueda de Libros usando el motor híbrido
    books_results = []
    if query and len(query) >= 2:
        try:
            libros_encontrados = buscar_libros_hibrido(query=query, max_results=6)
            for libro in libros_encontrados:
                books_results.append({
                    'id': libro.get('id', ''),
                    'titulo': libro.get('titulo', ''),
                    'autor': libro.get('autor_str', 'Autor'),
                    'genero': libro.get('genero', 'Literatura'),
                    'precio': libro.get('precio_desde', '$14.990 CLP'),
                    'portada': libro.get('imagen', ''),
                    'url': f"/libros/?q={requests.utils.quote(libro.get('titulo', ''))}"
                })
        except Exception as e:
            logger.warning(f"Error en quick_search_api: {e}")

    return JsonResponse({
        'status': 'ok',
        'query': query,
        'shortcuts': filtered_shortcuts,
        'books': books_results
    })


# --- MANEJADORES DE ERRORES PERSONALIZADOS (404, 500, 403, 400, 429) ---

def error_404_view(request, exception=None):
    """Página de error 404 personalizada: Página no encontrada."""
    return render(request, '404.html', status=404)


def error_500_view(request):
    """Página de error 500 personalizada: Error interno del servidor."""
    return render(request, '500.html', status=500)


def error_403_view(request, exception=None):
    """Página de error 403 personalizada: Acceso denegado / Prohibido."""
    return render(request, '403.html', status=403)


def error_400_view(request, exception=None):
    """Página de error 400 personalizada: Solicitud incorrecta."""
    return render(request, '404.html', status=400)


def test_error_view(request, code):
    """Vista de desarrollo para previsualizar y verificar el diseño de 404, 500, 403 y 429."""
    template_name = f"{code}.html"
    status_code = int(code) if str(code).isdigit() else 200
    return render(request, template_name, {'retry_after': 45}, status=status_code)

#cuotas

def api_estado_cuota(request):
    """
    API pública/autenticada para mostrar los mensajes restantes del usuario en la interfaz.
    """
    info = estado_cuota_usuario(request)
    return JsonResponse({'status': 'ok', 'cuota': info})