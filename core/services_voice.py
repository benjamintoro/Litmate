"""Síntesis de voz opcional mediante Microsoft Edge TTS.

La inferencia literaria local no utiliza este proveedor. Importar el módulo no
crea archivos, abre conexiones ni exige instalar edge-tts.
"""
import asyncio
from contextlib import contextmanager
import hashlib
import logging
import os
from pathlib import Path
import re
import tempfile
import threading
import time

from django.conf import settings

logger = logging.getLogger('litmate')
MAX_TEXT_LENGTH = 3500
_GENERATION_LOCK = threading.Lock()


class VoiceInputError(ValueError):
    pass


class VoiceUnavailable(RuntimeError):
    pass


class VoiceBusy(RuntimeError):
    pass


class VoiceServiceError(RuntimeError):
    pass


def limpiar_texto_para_voz(texto):
    """Elimina tarjetas y marcas visuales, conservando sólo texto para la voz."""
    if not isinstance(texto, str) or not texto.strip() or len(texto) > MAX_TEXT_LENGTH:
        raise VoiceInputError('Proporciona un texto de entre 1 y 3500 caracteres.')
    limpio = re.sub(r'\[LIBRO:.*?\]', '', texto, flags=re.IGNORECASE | re.DOTALL)
    limpio = re.sub(r'<[^>]*>', '', limpio)
    limpio = re.sub(r'https?://\S+', '', limpio)
    limpio = re.sub(r'[*#_~`\[\]()<>]', '', limpio)
    limpio = re.sub(r'\s+', ' ', limpio).strip()
    if not limpio:
        raise VoiceInputError('El mensaje no contiene texto para reproducir.')
    return limpio


def _positive_setting(name, default):
    try:
        return max(1, int(getattr(settings, name, default)))
    except (ValueError, TypeError):
        return default


def _voice_options():
    return {
        'voice': str(getattr(settings, 'LITMATE_TTS_VOICE', 'es-CL-CatalinaNeural')),
        'pitch': str(getattr(settings, 'LITMATE_TTS_PITCH', '+45Hz')),
        'rate': str(getattr(settings, 'LITMATE_TTS_RATE', '+50%')),
    }


async def generar_audio_edge(texto, output_path):
    """Único punto de conexión externa; se invoca sólo con la voz habilitada."""
    if not getattr(settings, 'LITMATE_TTS_ENABLED', False):
        raise VoiceUnavailable('La voz externa está desactivada.')
    try:
        import edge_tts
    except ImportError as error:
        raise VoiceUnavailable('Instala la dependencia opcional edge-tts para habilitar la voz.') from error
    communicator = edge_tts.Communicate(text=texto, **_voice_options())
    maximum_bytes = min(_positive_setting('LITMATE_TTS_MAX_AUDIO_BYTES', 5 * 1024 * 1024),
                        _positive_setting('LITMATE_TTS_CACHE_MAX_BYTES', 64 * 1024 * 1024))
    size = 0
    with Path(output_path).open('wb') as audio:
        async for message in communicator.stream():
            if message.get('type') != 'audio':
                continue
            chunk = message.get('data')
            if not isinstance(chunk, bytes) or size + len(chunk) > maximum_bytes:
                raise VoiceServiceError('El audio generado supera el tamaño permitido.')
            audio.write(chunk)
            size += len(chunk)


async def _generate_with_timeout(text, path):
    seconds = min(60, _positive_setting('LITMATE_TTS_TIMEOUT_SECONDS', 20))
    await asyncio.wait_for(generar_audio_edge(text, path), timeout=seconds)


@contextmanager
def _cache_lock(directory):
    """Bloqueo de proceso e hilo; el sistema operativo lo libera al terminar."""
    if not _GENERATION_LOCK.acquire(blocking=False):
        raise VoiceBusy('La voz está generando otro audio. Inténtalo nuevamente en unos segundos.')
    handle = None
    locked = False
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handle = (directory / 'cache.lock').open('a+b')
        if os.name == 'nt':
            import msvcrt
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise VoiceBusy('La voz está generando otro audio. Inténtalo nuevamente en unos segundos.') from error
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise VoiceBusy('La voz está generando otro audio. Inténtalo nuevamente en unos segundos.') from error
        locked = True
        yield
    finally:
        if handle is not None:
            try:
                if locked:
                    if os.name == 'nt':
                        import msvcrt
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
        _GENERATION_LOCK.release()


def _valid_audio(path, max_bytes):
    try:
        if path.is_symlink() or not path.is_file() or not 32 <= path.stat().st_size <= max_bytes:
            return False
        with path.open('rb') as audio:
            header = audio.read(3)
        return header == b'ID3' or (len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0)
    except OSError:
        return False


def _fresh_audio(path, max_bytes, ttl):
    try:
        return _valid_audio(path, max_bytes) and time.time() - path.stat().st_mtime < ttl
    except OSError:
        return False


def _prune_cache(directory, keep=None):
    """Aplica antigüedad, cantidad y tamaño sólo a archivos de esta caché."""
    maximum_files = _positive_setting('LITMATE_TTS_CACHE_MAX_FILES', 128)
    maximum_bytes = _positive_setting('LITMATE_TTS_CACHE_MAX_BYTES', 64 * 1024 * 1024)
    ttl = _positive_setting('LITMATE_TTS_CACHE_TTL_SECONDS', 7 * 86400)
    now = time.time()
    files = []
    for path in directory.glob('miku_*.mp3'):
        if path.is_symlink() or not path.is_file():
            continue
        stat = path.stat()
        if now - stat.st_mtime >= ttl and path != keep:
            path.unlink(missing_ok=True)
        else:
            files.append((path, stat.st_mtime, stat.st_size))
    files.sort(key=lambda item: (item[0] == keep, item[1]), reverse=True)
    total = 0
    for index, (path, _, size) in enumerate(files):
        if index >= maximum_files or total + size > maximum_bytes:
            path.unlink(missing_ok=True)
        else:
            total += size
    # Archivos interrumpidos de procesos anteriores nunca se publican como audio.
    for path in directory.glob('.miku_*.part'):
        if not path.is_symlink() and now - path.stat().st_mtime >= ttl:
            path.unlink(missing_ok=True)


def obtener_audio_miku(texto):
    """Genera o recupera un MP3 completo con límite de tiempo y caché acotada."""
    text = limpiar_texto_para_voz(texto)
    if not getattr(settings, 'LITMATE_TTS_ENABLED', False):
        raise VoiceUnavailable('La voz está desactivada. Al habilitarla, el texto se envía a Microsoft para sintetizar audio.')
    options = _voice_options()
    cache_key = hashlib.sha256(('voice-v2\0' + repr(sorted(options.items())) + '\0' + text).encode('utf-8')).hexdigest()
    name = f'miku_{cache_key}.mp3'
    directory = Path(settings.MEDIA_ROOT).resolve() / 'tts_cache'
    if directory.is_symlink():
        raise VoiceServiceError('No se pudo preparar la caché de audio.')
    path = directory / name
    maximum_bytes = min(_positive_setting('LITMATE_TTS_MAX_AUDIO_BYTES', 5 * 1024 * 1024),
                        _positive_setting('LITMATE_TTS_CACHE_MAX_BYTES', 64 * 1024 * 1024))
    media_url = str(settings.MEDIA_URL)
    if media_url.startswith(('http:', 'https:', '//')):
        raise VoiceUnavailable('La voz requiere una ruta local para servir el audio.')
    url = '/' + media_url.strip('/') + '/tts_cache/' + name
    ttl = _positive_setting('LITMATE_TTS_CACHE_TTL_SECONDS', 7 * 86400)
    if _fresh_audio(path, maximum_bytes, ttl):
        return url
    temporary = None
    try:
        with _cache_lock(directory):
            _prune_cache(directory)
            if _valid_audio(path, maximum_bytes):
                return url
            with tempfile.NamedTemporaryFile(prefix='.miku_', suffix='.part', dir=directory, delete=False) as file:
                temporary = Path(file.name)
            asyncio.run(_generate_with_timeout(text, temporary))
            if not _valid_audio(temporary, maximum_bytes):
                raise VoiceServiceError('El proveedor no entregó un archivo de audio válido.')
            os.replace(temporary, path)
            temporary = None
            _prune_cache(directory, keep=path)
            return url
    except (VoiceUnavailable, VoiceBusy, VoiceServiceError):
        raise
    except Exception as error:
        logger.warning('Falló la síntesis de voz externa: %s.', type(error).__name__)
        raise VoiceServiceError('No se pudo sintetizar el audio. Inténtalo nuevamente más tarde.') from error
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                logger.warning('No se pudo retirar un archivo temporal de voz; se limpiará al expirar.')
