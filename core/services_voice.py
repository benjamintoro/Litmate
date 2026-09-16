import os
import re
import hashlib
import asyncio
import edge_tts
from django.conf import settings
import logging

logger = logging.getLogger('litmate')

# Directorio donde se guardarán los audios generados
TTS_CACHE_DIR = os.path.join(settings.MEDIA_ROOT, 'tts_cache')
os.makedirs(TTS_CACHE_DIR, exist_ok=True)

def limpiar_texto_para_voz(texto):
    """Elimina etiquetas de tarjetas, URLs y markdown sin cortar la respuesta."""
    if not texto:
        return ""
    limpio = re.sub(r'\[LIBRO:.*?\]', '', texto, flags=re.IGNORECASE)
    limpio = re.sub(r'https?://\S+', '', limpio)
    limpio = re.sub(r'[*#_~`\[\]()<>]', '', limpio)
    limpio = re.sub(r'\s+', ' ', limpio).strip()
    return limpio[:3500]  # Ampliado a 3500 caracteres (suficiente para análisis literarios completos)

async def generar_audio_edge(texto, output_path):
    """
    Sintetiza la voz usando la red neuronal de Microsoft con entonación Vocaloid/Miku.
    Voz recomendada: es-CL-CatalinaNeural o es-MX-DaliaNeural con pitch alto.
    """
    voz = "es-CL-CatalinaNeural"
    # Moduladores de tono para emular el timbre de Hatsune Miku
    comunicador = edge_tts.Communicate(
        text=texto,
        voice=voz,
        pitch="+45Hz",   # Sube la frecuencia haciéndola dulce y juvenil
        rate="+50%"     # Ligero aumento de ritmo propio de los sintetizadores anime
    )
    await comunicador.save(output_path)

def obtener_audio_miku(texto):
    """
    Punto de entrada principal: genera o recupera el audio desde la caché.
    Retorna la URL relativa para reproducirla en el navegador.
    """
    texto_procesado = limpiar_texto_para_voz(texto)
    if not texto_procesado:
        return None

    # Hash único según el contenido del mensaje
    hash_id = hashlib.md5(texto_procesado.encode('utf-8')).hexdigest()
    nombre_archivo = f"miku_{hash_id}.mp3"
    ruta_absoluta = os.path.join(TTS_CACHE_DIR, nombre_archivo)
    url_relativa = f"{settings.MEDIA_URL}tts_cache/{nombre_archivo}"

    # Si ya existe en disco, lo entregamos de inmediato
    if os.path.exists(ruta_absoluta) and os.path.getsize(ruta_absoluta) > 0:
        return url_relativa

    try:
        # Ejecutar la corrutina asíncrona en el hilo síncrono de Django
        asyncio.run(generar_audio_edge(texto_procesado, ruta_absoluta))
        return url_relativa
    except Exception as e:
        logger.error(f"Error generando audio Miku: {e}")
        return None