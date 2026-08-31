from django.shortcuts import render, redirect, get_object_or_404
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
    MensajeContacto, ConversacionIA, MensajeIA
)
from .forms import UserRegisterForm, UserLoginForm, UserUpdateForm, ProfileUpdateForm
from .services import buscar_libros_hibrido, generar_enlaces_tiendas, generar_demo_extracto
from .security import ratelimit, check_honeypot, get_client_ip
from django.utils.text import slugify
from suscripciones.models import PlanSuscripcion, SuscripcionUsuario
from django.db import IntegrityError
from django.utils import timezone
from decimal import Decimal
import json
import re
import requests
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
    Inicia el flujo de autenticación social con Google o GitHub.
    Si las credenciales no están configuradas en .env o se activa el modo demo,
    inicia sesión con una cuenta de prueba para desarrollo rápido.
    """
    if request.user.is_authenticated:
        return redirect('index')

    provider = provider.lower()
    next_url = request.GET.get('next', 'index')
    request.session['social_auth_next'] = next_url

    host = request.get_host()
    scheme = request.scheme
    redirect_uri = f"{scheme}://{host}/auth/social/{provider}/callback/"

    # 1. Google OAuth
    if provider == 'google':
        client_id = getattr(settings, 'GOOGLE_CLIENT_ID', '')
        if client_id and not request.GET.get('demo'):
            google_auth_url = (
                f"https://accounts.google.com/o/oauth2/v2/auth?"
                f"client_id={client_id}&"
                f"redirect_uri={redirect_uri}&"
                f"response_type=code&"
                f"scope=openid%20email%20profile&"
                f"access_type=offline&"
                f"prompt=select_account"
            )
            return redirect(google_auth_url)

    # 2. GitHub OAuth
    elif provider == 'github':
        client_id = getattr(settings, 'GITHUB_CLIENT_ID', '')
        if client_id and not request.GET.get('demo'):
            github_auth_url = (
                f"https://github.com/login/oauth/authorize?"
                f"client_id={client_id}&"
                f"redirect_uri={redirect_uri}&"
                f"scope=user:email"
            )
            return redirect(github_auth_url)

    # 3. Fallback / Modo Demo Seguro para Desarrollo
    return _social_login_demo_mock(request, provider)


def _social_login_demo_mock(request, provider):
    """Genera/autentica una cuenta de demostración cuando no hay credenciales OAuth de producción."""
    from django.contrib.auth.models import User

    if provider == 'google':
        username = 'google_lector'
        email = 'lector.google@litmate.com'
        first_name = 'Lector'
        last_name = 'Google'
        bio = 'Lector apasionado conectado a través de Google.'
    else:
        username = 'github_dev'
        email = 'dev.github@litmate.com'
        first_name = 'Dev'
        last_name = 'GitHub'
        bio = 'Desarrollador y lector conectado a través de GitHub.'

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

    login(request, user)
    provider_name = 'Google' if provider == 'google' else 'GitHub'
    messages.success(request, f'¡Inicio de sesión exitoso con {provider_name}! Bienvenido a LitMate, {first_name}.')

    next_url = request.session.pop('social_auth_next', 'index')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect('index')


def social_login_callback(request, provider):
    """Recibe el código de autorización de Google o GitHub y autentica al usuario."""
    code = request.GET.get('code')
    if not code:
        messages.error(request, f'No se pudo completar la autenticación con {provider.title()}.')
        return redirect('login')

    from django.contrib.auth.models import User
    provider = provider.lower()
    host = request.get_host()
    scheme = request.scheme
    redirect_uri = f"{scheme}://{host}/auth/social/{provider}/callback/"

    try:
        if provider == 'google':
            token_url = "https://oauth2.googleapis.com/token"
            token_data = {
                'code': code,
                'client_id': settings.GOOGLE_CLIENT_ID,
                'client_secret': settings.GOOGLE_CLIENT_SECRET,
                'redirect_uri': redirect_uri,
                'grant_type': 'authorization_code'
            }
            token_res = requests.post(token_url, data=token_data, timeout=8).json()
            access_token = token_res.get('access_token')

            if not access_token:
                messages.error(request, 'Error al obtener token de acceso de Google.')
                return redirect('login')

            user_info = requests.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={'Authorization': f"Bearer {access_token}"},
                timeout=8
            ).json()

            email = user_info.get('email')
            first_name = user_info.get('given_name', 'Lector')
            last_name = user_info.get('family_name', 'Google')
            google_id = user_info.get('id', '')
            username = f"google_{google_id[:10]}" if google_id else email.split('@')[0]

        elif provider == 'github':
            token_url = "https://github.com/login/oauth/access_token"
            token_data = {
                'client_id': settings.GITHUB_CLIENT_ID,
                'client_secret': settings.GITHUB_CLIENT_SECRET,
                'code': code,
                'redirect_uri': redirect_uri
            }
            token_res = requests.post(token_url, data=token_data, headers={'Accept': 'application/json'}, timeout=8).json()
            access_token = token_res.get('access_token')

            if not access_token:
                messages.error(request, 'Error al obtener token de acceso de GitHub.')
                return redirect('login')

            user_info = requests.get(
                "https://api.github.com/user",
                headers={'Authorization': f"token {access_token}"},
                timeout=8
            ).json()

            github_id = str(user_info.get('id', ''))
            username = user_info.get('login') or f"gh_{github_id}"
            first_name = user_info.get('name') or username
            last_name = ""
            email = user_info.get('email')

            if not email:
                emails_res = requests.get(
                    "https://api.github.com/user/emails",
                    headers={'Authorization': f"token {access_token}"},
                    timeout=8
                ).json()
                if isinstance(emails_res, list) and emails_res:
                    email = emails_res[0].get('email')
                else:
                    email = f"{username}@users.noreply.github.com"
        else:
            return redirect('login')

        # Buscar usuario por email o username
        user = User.objects.filter(email=email).first() or User.objects.filter(username=username).first()
        if not user:
            user = User.objects.create(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name
            )
            user.set_unusable_password()
            user.save()

        # Perfil y suscripción
        PerfilUsuario.objects.get_or_create(
            usuario=user,
            defaults={'nombre': f"{first_name} {last_name}".strip(), 'correo': email}
        )
        plan_gratis = PlanSuscripcion.objects.filter(slug='gratis').first() or PlanSuscripcion.objects.filter(precio=0, activo=True).first()
        if plan_gratis:
            SuscripcionUsuario.objects.get_or_create(
                usuario=user,
                defaults={'plan': plan_gratis, 'estado': 'activa'}
            )

        login(request, user)
        messages.success(request, f'¡Bienvenido a LitMate, {first_name}!')

        next_url = request.session.pop('social_auth_next', 'index')
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect('index')

    except Exception as e:
        logger.error(f"Error en social_login_callback ({provider}): {e}")
        messages.error(request, f'Ocurrió un error al procesar el inicio de sesión con {provider.title()}.')
        return redirect('login')


def logout_view(request):
    if request.user.is_authenticated:
        logout(request)
        messages.info(request, 'Has cerrado sesión correctamente. ¡Hasta pronto!')
    return redirect('index')
@login_required
def perfil(request):
    try:
        if not hasattr(request.user, 'perfil'):
            PerfilUsuario.objects.create(usuario=request.user)
    except Exception: pass
        
    favoritos = LibroFavorito.objects.filter(usuario=request.user).order_by('-fecha_agregado')
    return render(request, 'core/perfil.html', {'favoritos': favoritos})

@login_required
def editar_perfil(request):
    if request.method == 'POST':
        u_form = UserUpdateForm(request.POST, instance=request.user)
        p_form = ProfileUpdateForm(request.POST, request.FILES, instance=request.user.perfil)
        if u_form.is_valid() and p_form.is_valid():
            u_form.save()
            p_form.save()
            messages.success(request, '¡Tu perfil ha sido actualizado!')
            return redirect('perfil')
    else:
        u_form = UserUpdateForm(instance=request.user)
        p_form = ProfileUpdateForm(instance=request.user.perfil)
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

def index(request): 
    return render(request, 'index.html')

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


@csrf_exempt
@ratelimit(limit=30, period=60, key_prefix='chatbot_query', json_response=True)
def chatbot_query(request):
    """
    Endpoint del Asistente Literario IA LitMate.
    Ofrece respuestas precisas, libres de alucinaciones (no inventa libros), estructuradas y con memoria conversacional.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    try:
        data = json.loads(request.body)
        user_message = data.get('message', '').strip()

        if not user_message:
            return JsonResponse({'response': "¡Hola! ¿En qué lectura u obra puedo ayudarte hoy?"})

        historial = obtener_historial_sesion(request)
        contexto_extra = ""
        libros_sugeridos = []
        
        msg_limpio = user_message.lower()
        palabras_comunes = ['hola', 'buenos dias', 'buenas tardes', 'buenas noches', 'que tal', 'hey', 'como estas']
        es_saludo = any(saludo in msg_limpio for saludo in palabras_comunes) and len(user_message) < 25

        if not es_saludo:
            # Extraer términos clave para búsqueda híbrida real (Grounding)
            query_busqueda = extraer_palabras_clave_busqueda(user_message)
            libros_sugeridos = buscar_libros_hibrido(query=query_busqueda, max_results=4)
            if libros_sugeridos:
                contexto_extra += "Libros reales registrados en el catálogo de LitMate y librerías:\n"
                for b in libros_sugeridos:
                    tiendas_str = ", ".join([f"{t['tienda']} ({t['precio_formateado']})" for t in b.get('tiendas', [])[:2]])
                    contexto_extra += (
                        f"- Título: \"{b['titulo']}\" de {b['autor_str']}. Género: {b['genero']}. "
                        f"Sinopsis: {b['sinopsis'][:240]}... "
                        f"Precio referencia: {b.get('precio_desde', '$14.990 CLP')}. Tiendas: {tiendas_str}. Link directo: {b.get('link_principal')}\n"
                    )

            # Búsqueda vectorial semántica (si Pinecone está configurado)
            embedding_model, pinecone_index = get_ai_resources()
            if pinecone_index and embedding_model:
                try:
                    query_embedding = embedding_model.encode(query_busqueda).tolist()
                    search_results = pinecone_index.query(vector=query_embedding, top_k=2, include_metadata=True)
                    if search_results.get('matches'):
                        contexto_extra += "\nCoincidencias semánticas adicionales:\n"
                        for match in search_results.get('matches', []):
                            if match.get('score', 0) > getattr(settings, 'LITMATE_SCORE_THRESHOLD', 0.30):
                                meta = match.get('metadata', {})
                                contexto_extra += f"- {meta.get('title', 'Libro')}: {meta.get('text', '')[:120]}...\n"
                except Exception as e:
                    logger.warning(f"Búsqueda Pinecone no disponible: {e}")

        # Datos del perfil del usuario (si está autenticado)
        user_info = ""
        if hasattr(request, 'user') and request.user.is_authenticated:
            nombre = request.user.first_name or request.user.username
            user_info = f"El usuario se llama {nombre}."
            if hasattr(request.user, 'perfil') and request.user.perfil.genero_lector_preferido:
                user_info += f" Su género literario preferido es: {request.user.perfil.genero_lector_preferido}."

        api_key = os.getenv('GROQ_API_KEY') or getattr(settings, 'GROQ_API_KEY', '')
        
        system_prompt = (
            "Eres LitMate, un asistente virtual experto, apasionado y riguroso sobre el mundo de los libros.\n"
            "Tu misión es guiar al lector, responder con profundidad y precisión factual, recomendar obras reales y ayudarlo a encontrar o recordar libros.\n\n"
            "DIRECTRICES DE PRECISIÓN Y ANTI-ALUCINACIÓN (ESTRICTAS Y OBLIGATORIAS):\n"
            "1. PROHIBICIÓN ABSOLUTA DE INVENTAR LIBROS: NUNCA inventes títulos de libros, autores ni tramas ficticias. Todos los libros que menciones deben ser obras reales existentes y verificables.\n"
            "2. CUANDO EL USUARIO BUSCA RECORDAR UN LIBRO (POR TRAMAS O PISTAS VAGAS):\n"
            "   a) Si tienes certeza de la obra real: Nómbrala con su título y autor verdadero, explicando por qué coincide con sus pistas.\n"
            "   b) Si hay varias opciones reales posibles: Preséntalas como posibilidades reales (\"Podría tratarse de alguna de estas obras:\").\n"
            "   c) Si las pistas son muy vagas o no corresponden a ningún libro real conocido: Sé honesto, di que esas pistas no coinciden con un libro registrado con certeza y actúa en 'Modo Detective Literario', haciendo 2 preguntas amables de descarte (ej: época aproximada en que lo leyó, público juvenil vs adulto, o detalles de portada/personajes).\n"
            "3. PROHIBIDO USAR ASTERISCOS (*) Y NUMERALES (#): No uses asteriscos (*) ni almohadillas/numerales (#) bajo ninguna circunstancia. No uses markdown como #, ##, **palabra** ni *palabra*.\n"
            "4. FORMATO DE TÍTULOS: Escribe siempre los títulos de libros entre comillas dobles (ejemplo: \"Cien años de soledad\" de Gabriel García Márquez).\n"
            "5. LISTAS Y ENLACES: Enumera con números (1., 2.) o guiones (-). Para cada libro real recomendado, incluye en su propia línea el enlace de compra o consulta:\n"
            "   https://www.buscalibre.cl/libros/search?q=TITULO+AUTOR (reemplazando espacios por '+').\n"
            "6. TONO: Amable, culto, entusiasta y honesto. Responde siempre en español."
        )

        if user_info:
            system_prompt += f"\n\nContexto del usuario: {user_info}"

        if contexto_extra:
            system_prompt += f"\n\nCatálogo de referencia para responder con máxima precisión:\n{contexto_extra}"

        respuesta_ia = None

        if api_key:
            try:
                client = Groq(api_key=api_key)
                mensajes_payload = [{"role": "system", "content": system_prompt}]
                
                # Inyectar memoria de la conversación
                for m_hist in historial:
                    rol_llm = "assistant" if m_hist['rol'] in ["assistant", "bot"] else "user"
                    mensajes_payload.append({"role": rol_llm, "content": m_hist['contenido']})
                    
                mensajes_payload.append({"role": "user", "content": user_message})

                modelos_candidatos = [
                    "openai/gpt-oss-120b",
                    "openai/gpt-oss-20b",
                    "groq/compound",
                    "qwen/qwen3.6-27b"
                ]

                for modelo in modelos_candidatos:
                    try:
                        chat_completion = client.chat.completions.create(
                            messages=mensajes_payload,
                            model=modelo,
                            temperature=0.25,  # Temperatura baja para máxima precisión factual y cero alucinaciones
                            max_tokens=1200
                        )
                        raw_resp = chat_completion.choices[0].message.content
                        respuesta_ia = re.sub(r'<think>.*?</think>', '', raw_resp, flags=re.DOTALL).strip()
                        if respuesta_ia:
                            break
                    except Exception as mod_err:
                        logger.warning(f"Modelo {modelo} no respondió: {mod_err}. Probando siguiente...")
            except Exception as groq_err:
                logger.error(f"Error general en Groq API: {groq_err}")

        # Fallback de alta fidelidad si la API externa no responde
        if not respuesta_ia:
            if libros_sugeridos:
                l = libros_sugeridos[0]
                respuesta_ia = (
                    f"¡Te recomiendo con entusiasmo \"{l['titulo']}\" de {l['autor_str']}!\n\n"
                    f"Es una obra destacada del género {l['genero']}. {l['sinopsis'][:280]}...\n\n"
                    f"Puedes encontrarlo y comparar precios desde {l.get('precio_desde', '$14.990 CLP')} aquí:\n"
                    f"{l.get('link_principal')}"
                )
            elif es_saludo:
                respuesta_ia = "¡Hola! Qué gusto saludarte. Soy LitMate, tu compañero de lectura. ¿Buscas alguna novela en específico, un autor favorito o recomendaciones por género?"
            else:
                respuesta_ia = (
                    f"No encontré ese libro exacto de inmediato, pero puedes explorar nuestro catálogo con más de 50 sagas destacadas en:\n\n"
                    f"https://www.buscalibre.cl/libros/search?q={requests.utils.quote(user_message)}"
                )

        # Limpiar cualquier asterisco o numeral
        respuesta_ia = limpiar_simbolos_markdown(respuesta_ia)

        guardar_historial_sesion(request, user_message, respuesta_ia)
        return JsonResponse({'response': respuesta_ia})

    except Exception as e:
        logger.error(f"Error Chatbot: {e}")
        return JsonResponse({'response': "Tuve un pequeño lapso de memoria. ¿Me repites tu consulta sobre libros?"}, status=500)


def quick_search_api(request):
    """
    Endpoint ultrarrápido para el Command Palette / Búsqueda Global (Ctrl+K).
    Retorna atajos de navegación y resultados coincidentes de libros y autores.
    """
    query = request.GET.get('q', '').strip()
    
    # 1. Atajos de navegación rápidos en la plataforma
    shortcuts_all = [
        {'title': 'Explorar Catálogo', 'desc': 'Buscar libros, filtrar por género y comparar precios', 'url': '/libros/', 'icon': 'fa-book-open', 'category': 'Navegación'},
        {'title': 'Asistente IA (Chatbot)', 'desc': 'Conversar con el recomendador inteligente de lecturas', 'url': '/chat/', 'icon': 'fa-robot', 'category': 'Inteligencia Artificial'},
        {'title': 'Planes y Precios', 'desc': 'Conoce las membresías Premium y suscripciones', 'url': '/suscripciones/planes/', 'icon': 'fa-crown', 'category': 'Membresías'},
        {'title': 'Novedades y Artículos', 'desc': 'Explorar el blog y publicaciones literarias', 'url': '/post/', 'icon': 'fa-newspaper', 'category': 'Comunidad'},
        {'title': 'Sobre Nosotros', 'desc': 'Conoce la misión y el equipo detrás de LitMate', 'url': '/about/', 'icon': 'fa-info-circle', 'category': 'Información'},
        {'title': 'Contacto y Soporte', 'desc': 'Envíanos un mensaje o sugerencia', 'url': '/contact/', 'icon': 'fa-envelope', 'category': 'Soporte'},
    ]
    
    if hasattr(request, 'user') and request.user.is_authenticated:
        shortcuts_all.insert(0, {'title': 'Mi Perfil & Favoritos', 'desc': 'Ver tus libros guardados y progreso de lectura', 'url': '/perfil/', 'icon': 'fa-user', 'category': 'Cuenta'})
    else:
        shortcuts_all.append({'title': 'Iniciar Sesión / Registro', 'desc': 'Accede a tu cuenta de lector', 'url': '/login/', 'icon': 'fa-sign-in-alt', 'category': 'Cuenta'})

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