# litmate_project/core/views.py

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from .models import HistorialChatbot

import json
import logging
import requests
import re

# Librerías Externas
from huggingface_hub import InferenceClient

# Importación segura de búsqueda
try:
    from googlesearch import search as google_web_search
    HAS_GOOGLE_SEARCH = True
except ImportError:
    HAS_GOOGLE_SEARCH = False

# Logger
logger = logging.getLogger('litmate')

# --- CONFIGURACIÓN DE LA IA ---
REPO_ID = "HuggingFaceH4/zephyr-7b-beta"

# --- HERRAMIENTAS DE BÚSQUEDA ---

def buscar_google_books(query, max_results=3):
    """Busca libros y extrae datos relevantes."""
    try:
        # Busca con mejor precisión
        url = f"https://www.googleapis.com/books/v1/volumes?q={query}&maxResults={max_results}&langRestrict=es"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            libros_info = []
            
            if 'items' in data and data['items']:
                for item in data['items'][:2]:  # Solo los 2 primeros
                    try:
                        info = item.get('volumeInfo', {})
                        titulo = info.get('title', 'Sin título')
                        autores = ', '.join(info.get('authors', ['Autor desconocido']))
                        desc = info.get('description', 'Sin descripción disponible.')[:200]
                        fecha = info.get('publishedDate', 'N/A')
                        link = info.get('infoLink', '')
                        
                        libro_str = f"📚 {titulo} ({fecha}) - {autores}\n{desc}"
                        if link:
                            libro_str += f"\nLink: {link}"
                        
                        libros_info.append(libro_str)
                    except Exception as item_error:
                        logger.warning(f"Error procesando item: {item_error}")
                        continue
            
            if libros_info:
                return "\n\n".join(libros_info)
        else:
            logger.warning(f"API Google Books retornó: {response.status_code}")
    except requests.Timeout:
        logger.warning("Google Books timeout")
    except Exception as e:
        logger.error(f"Error Google Books: {type(e).__name__}: {e}")
    
    return ""

def buscar_google_web(query, num_results=2):
    """Busca información general en la web."""
    if not HAS_GOOGLE_SEARCH: 
        logger.warning("Google Search no disponible")
        return ""
    try:
        # Convertimos generador a lista
        results = list(google_web_search(query, num_results=num_results, lang="es"))
        if results and len(results) > 0: 
            # Retornar solo URLs útiles
            enlaces = " | ".join(results[:2])
            return f"Fuentes: {enlaces}"
        return ""
    except Exception as e:
        logger.warning(f"Error Web Search: {type(e).__name__}: {e}")
        return ""

def limpiar_respuesta(texto):
    """Limpieza agresiva y quirúrgica de la respuesta."""
    # 1. Eliminar TODOS los tokens internos del modelo
    tokens_eliminar = ["<|system|>", "<|user|>", "<|assistant|>", "</s>", "<|end_of_turn|>", "<|im_start|>", "<|im_end|>"]
    for token in tokens_eliminar:
        texto = texto.replace(token, "")
    
    # 2. CORTE AGRESIVO: Si el modelo intenta simular diálogo, cortamos
    marcadores_peligrosos = [
        "[/USER]", "[USER]", "[/LITMATE]", "[LITMATE]",
        "\n\nUser:", "\n\nUsuario:", "\n\nHuman:",
        "\n[", # Cualquier cosa entre corchetes
        "\n\n-", # Guiones de diálogo
    ]
    
    for marcador in marcadores_peligrosos:
        if marcador in texto:
            texto = texto.split(marcador)[0]
    
    # 3. Si hay múltiples párrafos con patrones de pregunta-respuesta, cortamos
    parrafos = texto.split('\n\n')
    if len(parrafos) > 2:
        # Revisamos si los párrafos subsecuentes parecen alucinaciones
        primer_parrafo = parrafos[0]
        segundo_parrafo = parrafos[1] if len(parrafos) > 1 else ""
        
        # Si el segundo párrafo empieza con patrones de pregunta, lo ignoramos
        if any(segundo_parrafo.lower().strip().startswith(x) for x in ["me gustaría", "sí,", "sí ", "gracias", "hola,"]):
            texto = primer_parrafo
        else:
            # Mantener máximo 2 párrafos
            texto = "\n\n".join(parrafos[:2])
    
    # 4. Limitar longitud: Si la respuesta > 500 caracteres, probablemente sea alucinación
    if len(texto) > 500:
        # Cortamos por oración
        oraciones = texto.split('. ')
        texto_limitado = ""
        for oracion in oraciones:
            if len(texto_limitado) + len(oracion) > 400:
                break
            texto_limitado += oracion + ". "
        texto = texto_limitado
    
    # 5. Eliminar prefijos innecesarios
    prefijos_eliminar = ["respuesta:", "respuesta ", "[respuesta]"]
    for prefijo in prefijos_eliminar:
        if texto.lower().startswith(prefijo):
            texto = texto[len(prefijo):]
    
    # 6. Limpiar espacios en blanco múltiples
    texto = ' '.join(texto.split())
    
    # 6b. Detectar y evitar repeticiones simples
    palabras = texto.split()
    if len(palabras) > 3:
        # Si más del 40% de palabras se repite, probablemente sea alucinación
        palabras_unicas = set(palabras)
        ratio_unicidad = len(palabras_unicas) / len(palabras) if len(palabras) > 0 else 1
        if ratio_unicidad < 0.4:
            logger.warning(f"Respuesta repetitiva detectada: {ratio_unicidad:.2%}, truncando")
            # Tomar solo las primeras 2 oraciones
            oraciones = texto.split('. ')
            texto = oraciones[0] + ('.' if oraciones[0] else '')
    
    # 6c. ELIMINAR PREGUNTAS AL FINAL (el modelo tiende a hacer preguntas)
    # Patrones de preguntas que NO queremos
    patrones_preguntas = [
        r'\?$',  # Termina con ?
        r'¿.*\?$',  # Pregunta al final
        r'\s*¿.*$',  # Pregunta al final sin cerrar
    ]
    
    for patron in patrones_preguntas:
        if re.search(patron, texto):
            # Si hay pregunta, cortar en el último punto
            partes = texto.split('.')
            if len(partes) > 1:
                texto = '.'.join(partes[:-1]) + '.'
                logger.warning(f"Pregunta detectada al final, truncada")
            break
    
    # 7. Si la respuesta está vacía o solo contiene símbolos raros, retornar algo genérico
    texto_limpio = texto.strip()
    if not texto_limpio or len(texto_limpio) < 3 or all(c in ".,;:!?¿ " for c in texto_limpio):
        return "¿En qué puedo ayudarte?"
    
    return texto_limpio

def generar_respuesta_ia(mensaje_usuario, historial_previo=[], contexto_extra=""):
    """
    Genera respuesta usando Zephyr con parámetros estrictos.
    """
    if not settings.HUGGINGFACE_API_KEY or "tu_clave" in settings.HUGGINGFACE_API_KEY.lower():
        return "⚠️ Error: Configura tu API Key en settings.py."

    client = InferenceClient(model=REPO_ID, token=settings.HUGGINGFACE_API_KEY)

    # 1. PROMPT DE SISTEMA (SIMPLE Y DIRECTO - SIN HACER PREGUNTAS)
    system_instruction = (
        "Eres LitMate, asistente experto de libros. Tu único trabajo es RESPONDER preguntas.\n"
        "REGLA MÁS IMPORTANTE: NUNCA hagas preguntas al usuario. Solo proporciona información.\n"
        "Instrucciones:\n"
        "1. Responde en máximo 2 oraciones claras.\n"
        "2. Si hay información en [CONTEXTO], úsala.\n"
        "3. Sé directo y conciso, sin rodeos.\n"
        "4. NUNCA termines tu respuesta con '?' o preguntas.\n"
        "5. Si no conoces algo, di 'No tengo esa información'.\n"
        "6. Ejemplos:\n"
        "   - Usuario: '¿Quién escribió Harry Potter?' → TÚ: 'J.K. Rowling escribió la saga.'\n"
        "   - Usuario: 'Hola' → TÚ: 'Hola, ¿en qué te puedo ayudar con libros?'\n"
        "   - Usuario: 'Cuéntame sobre Narnia' → TÚ: 'Las Crónicas de Narnia es una serie fantástica de C.S. Lewis.'"
    )

    messages = [{"role": "system", "content": system_instruction}]

    # 2. HISTORIAL (Solo el último intercambio para máxima claridad)
    if historial_previo and len(historial_previo) > 0:
        # Usamos solo el 1 último intercambio para mantener claridad sin confusión
        ultimo = historial_previo[-1]
        messages.append({"role": "user", "content": ultimo['usuario']})
        messages.append({"role": "assistant", "content": ultimo['bot']})

    # 3. MENSAJE ACTUAL + CONTEXTO
    contenido_final = mensaje_usuario
    if contexto_extra:
        contenido_final += f"\n\n[CONTEXTO]:\n{contexto_extra}"
    
    messages.append({"role": "user", "content": contenido_final})

    try:
        response = client.chat_completion(
            messages=messages,
            max_tokens=160,
            temperature=0.2,  # Más bajo = menos preguntas innecesarias
            top_p=0.75,
            # STOP SEQUENCES: Cortamos intentos de diálogo y preguntas
            stop=["<|user|>", "User:", "Usuario:", "\n\nHuman:", "[USER]", "[/USER]", "[LITMATE]", "¿", "?", "Necesito", "---"] 
        )
        
        raw_text = response.choices[0].message.content
        return limpiar_respuesta(raw_text)

    except Exception as e:
        logger.error(f"Error API crítico: {type(e).__name__}: {str(e)}")
        logger.error(f"Mensajes enviados: {[m.get('role') for m in messages]}")
        # Retornar algo útil en lugar de error
        if historial_previo:
            # Si hay historial, responde genéricamente pero relevante
            return "Disculpa, tuve un problema. ¿Qué necesitas saber del tema anterior?"
        else:
            return "Disculpa, hubo un error. ¿Cuál es tu pregunta?"

# --- VISTAS STANDARD ---
def index(request): return render(request, 'index.html')
def about(request): return render(request, 'about.html')
def post(request): return render(request, 'post.html')
def contact(request): return render(request, 'contact.html')
def chatbot_page(request): return render(request, 'chatbot.html')

def buscar_libros(request):
    query = request.GET.get('q', 'best sellers')
    libros = []
    try:
        url = f"https://www.googleapis.com/books/v1/volumes?q={query}&maxResults=12"
        data = requests.get(url, timeout=3).json()
        if 'items' in data:
            for item in data['items']:
                info = item.get('volumeInfo', {})
                libros.append({
                    'id': item.get('id'),
                    'titulo': info.get('title', 'Sin título'),
                    'autores': info.get('authors', ['Anónimo']),
                    'imagen': info.get('imageLinks', {}).get('thumbnail', ''),
                    'link_google': info.get('infoLink', '#'),
                })
    except Exception: pass
    return render(request, 'buscar_libros.html', {'libros': libros})

# --- CONTROLADOR PRINCIPAL DEL CHATBOT ---

@csrf_exempt
def chatbot_query(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    try:
        data = json.loads(request.body)
        user_message = data.get('message', '').strip()
        
        if not user_message:
            return JsonResponse({'response': "Estoy aquí, dime."})

        # --- 1. HISTORIAL (en sesión para usuarios anónimos, en BD para autenticados) ---
        historial_para_ia = []
        
        if request.user.is_authenticated:
            # USUARIOS AUTENTICADOS: Traer historial de BD
            historial_db = HistorialChatbot.objects.filter(usuario=request.user).order_by('-fecha_interaccion')[:6]
            for h in reversed(historial_db):
                historial_para_ia.append({'usuario': h.mensaje_usuario, 'bot': h.respuesta_chatbot})
            logger.info(f"Historial BD cargado: {len(historial_para_ia)} intercambios para {request.user.username}")
        else:
            # USUARIOS ANÓNIMOS: Traer historial de sesión
            if 'chat_history' not in request.session:
                request.session['chat_history'] = []
            
            historial_para_ia = request.session.get('chat_history', [])
            logger.info(f"Historial sesión cargado: {len(historial_para_ia)} intercambios (usuario anónimo)")

        # --- 2. BÚSQUEDA INTELIGENTE (CON DETECCIÓN DE SEGUIMIENTO) ---
        msg_lower = user_message.lower()
        contexto = ""
        
        # Detectar si es pregunta de SEGUIMIENTO o SALUDO (no debe buscar de nuevo)
        patrones_seguimiento = [
            r'^¿?hola',        # hola
            r'^¿?como\s*est',  # cómo estás
            r'^¿?que\s*tal',   # qué tal
            r'^¿?quien',       # quién es
            r'^¿?donde',       # dónde está
            r'^¿?cual',        # cuál es
            r'^¿?que es',      # qué es
            r'^¿?si$',         # solo "si"
            r'^¿?no$',         # solo "no"
            r'^ok',            # ok
            r'^¿?es\s',        # es...
            r'^¿?esta',        # está
            r'^gracias',       # gracias
            r'^buenas',        # buenos días, buenas tardes
        ]
        
        es_seguimiento = (
            len(user_message.split()) <= 5 and 
            any(re.search(patron, msg_lower) for patron in patrones_seguimiento)
        )
        
        # Solo buscar si NO es pregunta de seguimiento
        if not es_seguimiento:
            # Palabras clave para detectar búsquedas
            activadores_libro = [
                'libro', 'autor', 'novela', 'leer', 'sinopsis', 'trata', 'recomienda', 'escrito', 'saga',
                'trama', 'personajes', 'protagonista', 'capitulo', 'genero', 'genero literario',
                'resumen', 'argumento', 'historia', 'obra', 'publicado', 'editorial',
                'reseña', 'opinión', 'recomendacion', 'consejo', 'lectura', 'bestseller', 'necesito'
            ]
            
            activadores_web = [
                'busca', 'google', 'precio', 'donde', 'quien', 'serie', 'pelicula', 'arcane',
                'buscar', 'encuentra', 'quiero saber', 'dime', 'cuéntame',
                'informacion', 'información', 'detalles', 'explica', 'explícame'
            ]

            # BÚSQUEDA DE LIBROS (prioridad)
            tiene_activador_libro = any(w in msg_lower for w in activadores_libro)
            if tiene_activador_libro:
                datos = buscar_google_books(user_message)
                if datos: 
                    contexto += f"{datos}\n"
                    logger.info(f"Búsqueda Google Books ejecutada para: {user_message}")

            # BÚSQUEDA WEB (si no encontró en libros o es pregunta general)
            tiene_activador_web = any(w in msg_lower for w in activadores_web)
            if tiene_activador_web and not contexto:
                datos = buscar_google_web(user_message)
                if datos: 
                    contexto += f"{datos}\n"
                    logger.info(f"Búsqueda Web ejecutada para: {user_message}")
            
            # Fallback: Si NO hay contexto y la pregunta es compleja
            if not contexto and len(user_message.split()) > 2:
                datos = buscar_google_web(user_message)
                if datos:
                    contexto += f"{datos}\n"
        else:
            logger.info(f"Pregunta de seguimiento detectada, sin búsqueda: {user_message}")
        
        # Si la pregunta es completamente off-topic (no contiene palabras de libros ni es seguimiento)
        palabras_libro = ['libro', 'leer', 'autor', 'trama', 'novela', 'personaje', 'narnia', 'harry', 'juego', 'tronos', 'arcane']
        es_off_topic = not any(w in msg_lower for w in palabras_libro) and not es_seguimiento
        if es_off_topic and len(user_message.split()) > 3:
            # Agregar hint amigable para refocusear en libros
            contexto += "[NOTA: La pregunta no es sobre libros. Responde brevemente pero luego sugiere un libro.]"

        # --- 3. RESPUESTA IA ---
        respuesta_ia = generar_respuesta_ia(user_message, historial_para_ia, contexto)
        logger.info(f"Respuesta IA generada: {respuesta_ia[:100]}...")
        
        # --- 4. GUARDAR HISTORIAL (BD o Sesión) ---
        try:
            if request.user.is_authenticated:
                # Guardar en BD para usuarios autenticados
                historial = HistorialChatbot.objects.create(
                    usuario=request.user,
                    mensaje_usuario=user_message,
                    respuesta_chatbot=respuesta_ia
                )
                logger.info(f"Interacción guardada en BD: ID={historial.id}")
            else:
                # Guardar en sesión para usuarios anónimos
                if 'chat_history' not in request.session:
                    request.session['chat_history'] = []
                
                # Agregar el nuevo intercambio al historial de sesión
                request.session['chat_history'].append({
                    'usuario': user_message,
                    'bot': respuesta_ia
                })
                
                # Limitar historial de sesión a 20 intercambios para no saturar
                if len(request.session['chat_history']) > 20:
                    request.session['chat_history'] = request.session['chat_history'][-20:]
                
                request.session.modified = True
                logger.info(f"Interacción guardada en sesión: {len(request.session['chat_history'])} intercambios")
        except Exception as e:
            logger.error(f"Error al guardar historial: {e}")

        return JsonResponse({'response': respuesta_ia})

    except Exception as e:
        logger.error(f"Error crítico view: {e}")
        return JsonResponse({'response': "Error interno del servidor."})