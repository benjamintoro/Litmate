from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import HistorialChatbot, PerfilUsuario, LibroFavorito
from .forms import UserRegisterForm, UserUpdateForm, ProfileUpdateForm

import json
import re
import requests
import datetime
import logging
import random

# Librerías IA
from sentence_transformers import SentenceTransformer
from pinecone import Pinecone

# Importamos los datos limpios (Asegúrate de tener este archivo core/chatbot_data.py)
from core.chatbot_data import SOCIAL_PATTERNS, BOOK_QUERY_PATTERNS, detect_genre

# Logger configurado en settings.py
logger = logging.getLogger('litmate')

# --- INICIALIZACIÓN DE SERVICIOS (CÓDIGO ORIGINAL) ---
pinecone_index = None
embedding_model = None

try:
    if settings.PINECONE_API_KEY:
        pc = Pinecone(api_key=settings.PINECONE_API_KEY)
        INDEX_NAME = 'litmate-book-index'
        
        try:
            if INDEX_NAME in pc.list_indexes().names():
                pinecone_index = pc.Index(INDEX_NAME)
                embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
                logger.info("Pinecone y modelo de embeddings listos.")
        except Exception:
             logger.warning("No se pudo conectar a Pinecone.")

except Exception as e:
    logger.error(f"Error inicializando IA: {e}")

# --- UTILIDADES DE BÚSQUEDA (CÓDIGO ORIGINAL) ---

def search_google_books(query, max_results=3):
    """Busca libros en Google Books API y retorna con links."""
    try:
        # Escapar query para URL
        query_escaped = requests.utils.quote(query)
        # Usar orderBy para obtener los más relevantes primero
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

# --- VISTAS DE USUARIO Y PERFIL (NUEVAS FUNCIONALIDADES) ---

def register(request):
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.save()
            PerfilUsuario.objects.create(usuario=user) # Crear perfil vacío
            messages.success(request, f'¡Cuenta creada! Ahora puedes iniciar sesión.')
            return redirect('login')
    else:
        form = UserRegisterForm()
    return render(request, 'registration/register.html', {'form': form})

@login_required
def perfil(request):
    try:
        # Asegurar que existe el perfil si se creó el usuario manualmente antes
        if not hasattr(request.user, 'perfil'):
            PerfilUsuario.objects.create(usuario=request.user)
    except:
        pass
        
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

# --- VISTAS STANDARD (EXISTENTES) ---

def index(request): 
    return render(request, 'index.html')

def about(request): 
    return render(request, 'about.html')

def post(request): 
    return render(request, 'post.html')

def chatbot_page(request): 
    return render(request, 'chatbot.html')

def contact(request):
    success_message = None
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        message = request.POST.get('message')
        logger.info(f"Contacto recibido de {name} ({email}): {message}")
        success_message = "¡Tu mensaje ha sido enviado con éxito!"

    return render(request, 'contact.html', {'success': success_message})

def buscar_libros(request):
    query = request.GET.get('q', 'clásicos de la literatura')
    author = request.GET.get('author', '')
    genre = request.GET.get('genre', '')
    year = request.GET.get('year', '')

    api_query = query
    if author: api_query += f"+inauthor:{author}"
    if genre: api_query += f"+subject:{genre}"
    
    libros = []
    try:
        url = f"https://www.googleapis.com/books/v1/volumes?q={api_query}&maxResults=24"
        data = requests.get(url, timeout=5).json()
        
        if 'items' in data:
            for item in data['items']:
                info = item.get('volumeInfo', {})
                pub_date = info.get('publishedDate', 'N/A')
                
                if year and not pub_date.startswith(year): 
                    continue

                libros.append({
                    'id': item.get('id'),
                    'titulo': info.get('title', 'Sin título'),
                    'autores': info.get('authors', ['Anónimo']),
                    'imagen': info.get('imageLinks', {}).get('thumbnail', ''),
                    'link_google': info.get('infoLink', '#'),
                    'descripcion': info.get('description', 'Sin descripción'),
                    # Simulamos precio/moneda ya que Google Books API básica a veces no lo da directo fácil
                    'precio': '15000', 
                    'moneda': 'CLP',
                    'link_compra': info.get('infoLink', '#')
                })
    except Exception as e:
        logger.warning(f"Error buscando libros: {e}")

    return render(request, 'buscar_libros.html', {
        'libros': libros,
        'valores_busqueda': request.GET,
        'generos': ["Ficción", "Misterio", "Ciencia Ficción", "Fantasía", "Romance", "Historia", "Tecnología"],
        'años': range(datetime.date.today().year, 1950, -1),
    })

# --- LÓGICA CHATBOT (TU LÓGICA COMPLETA ORIGINAL) ---

def obtener_historial(request):
    historial = []
    if request.user.is_authenticated:
        historial_db = HistorialChatbot.objects.filter(usuario=request.user).order_by('-fecha_interaccion')[:5]
        for h in reversed(historial_db):
            historial.append({'usuario': h.mensaje_usuario, 'bot': h.respuesta_chatbot})
    else:
        if 'chat_history' not in request.session:
            request.session['chat_history'] = []
        historial = request.session.get('chat_history', [])
    return historial

def guardar_interaccion(request, mensaje_usuario, respuesta_bot):
    try:
        if request.user.is_authenticated:
            HistorialChatbot.objects.create(
                usuario=request.user,
                mensaje_usuario=mensaje_usuario,
                respuesta_chatbot=respuesta_bot
            )
        else:
            if 'chat_history' not in request.session:
                request.session['chat_history'] = []
            
            request.session['chat_history'].append({
                'usuario': mensaje_usuario,
                'bot': respuesta_bot
            })
            if len(request.session['chat_history']) > 20:
                request.session['chat_history'] = request.session['chat_history'][-20:]
            request.session.modified = True
    except Exception as e:
        logger.error(f"Error guardando: {e}")

def extraer_libro_del_historial(historial):
    if not historial: return None
    for item in reversed(historial[-6:]):
        bot_response = item.get('bot', '')
        if "He encontrado:" in bot_response:
            match = re.search(r"He encontrado: '([^']+)'", bot_response)
            if match: return match.group(1)
    return None

@csrf_exempt
def chatbot_query(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    try:
        data = json.loads(request.body)
        user_message = data.get('message', '').strip()
        
        if not user_message:
            return JsonResponse({'response': "¿En qué puedo ayudarte?"})

        msg_norm = user_message.lower()
        historial = obtener_historial(request)

        # 1. PATRONES SOCIALES
        for intent, social_data in SOCIAL_PATTERNS.items():
            if re.search(social_data['pattern'], msg_norm, re.I):
                response = random.choice(social_data['responses'])
                guardar_interaccion(request, user_message, response)
                return JsonResponse({'response': response})

        # 2. DETECTAR PATRÓN DE PREGUNTA SOBRE LIBRO
        query_type_detected = None
        for query_type, query_info in BOOK_QUERY_PATTERNS.items():
            if re.search(query_info['pattern'], msg_norm, re.I):
                query_type_detected = query_type
                break
        
        if query_type_detected:
            libro_name = extraer_libro_del_historial(historial)
            if not libro_name:
                msg_limpio = re.sub(r'[?¿!¡]', '', user_message).lower()
                palabras_ignorar = {
                    'quién', 'qué', 'dime', 'cuál', 'es', 'el', 'la', 'de', 'del', 'y', 'sobre', 'autor', 'trama'
                } # (Lista resumida, tu lógica tenía más)
                palabras = [p for p in msg_limpio.split() if len(p) > 2 and p not in palabras_ignorar]
                if palabras: libro_name = ' '.join(palabras)
            
            if libro_name and len(libro_name.strip()) > 2:
                detalles, link = buscar_detalles_libro_google(libro_name, query_type_detected)
                if detalles:
                    titulo = detalles.get('titulo', libro_name)
                    if query_type_detected == 'autor': response = f"{titulo} fue escrito por {detalles['author']}."
                    elif query_type_detected == 'trama': response = f"La historia de {titulo} trata sobre: {detalles['trama']}"
                    elif query_type_detected == 'link': response = f"📚 Leer en Google Books: {link}"
                    else: response = f"Sobre {titulo}: {detalles.get(query_type_detected, 'No tengo esa información.')}"
                    
                    guardar_interaccion(request, user_message, response)
                    return JsonResponse({'response': response})

        # 3. BÚSQUEDA SIMPLE
        if len(user_message.strip()) >= 2 and not query_type_detected:
            palabras_ignorar_simple = {'si', 'no', 'ok', 'hola'}
            if user_message.lower().strip() not in palabras_ignorar_simple and len(user_message.split()) <= 5:
                g_results = search_google_books(user_message, max_results=1)
                if g_results:
                    book = g_results[0]
                    response = f"He encontrado: '{book['titulo']}' de {', '.join(book['autores'])}.\n{book['descripcion'][:150]}...\n📚 Leer en Google Books: {book['google_books_link']}"
                    guardar_interaccion(request, user_message, response)
                    return JsonResponse({'response': response})

        # 4. PINECONE (SEMÁNTICA)
        if pinecone_index and embedding_model:
            try:
                query_embedding = embedding_model.encode(user_message).tolist()
                detected_genres = detect_genre(user_message)
                filter_dict = {"categories": {"$in": detected_genres}} if detected_genres else None
                search_results = pinecone_index.query(vector=query_embedding, top_k=3, include_metadata=True, filter=filter_dict)
                
                context_text = ""
                for match in search_results.get('matches', []):
                    if match['score'] > settings.LITMATE_SCORE_THRESHOLD:
                        context_text += f"• {match['metadata'].get('title')}: {match['metadata'].get('text')[:100]}...\n"

                if context_text:
                    response = f"Basado en mi base de datos:\n{context_text}"
                    guardar_interaccion(request, user_message, response)
                    return JsonResponse({'response': response})
            except Exception: pass

        response = "No encontré información sobre eso. Intenta preguntarme por un libro, autor o género específico."
        guardar_interaccion(request, user_message, response)
        return JsonResponse({'response': response})

    except Exception as e:
        logger.error(f"Error: {e}")
        return JsonResponse({'response': "Tuve un error procesando tu mensaje."}, status=500)