"""Precarga explícita y opcional del modelo ya instalado, sin generar texto.

Ollama documenta la petición vacía y keep_alive en https://docs.ollama.com/faq
(How can I preload a model into Ollama to get faster response times?). No se
descargan modelos, consultan fuentes ni abren bases de datos desde este comando.
"""
import re
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.ai_http import local_origin, read_json_url
from core.literary_ai import ProviderUnavailable
from core.local_llm import OllamaJSON


def _keep_alive(value):
    if (not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,2}m', value)
            or not 5 <= int(value[:-1]) <= 120):
        raise CommandError('--keep-alive debe indicar entre 5m y 120m.')
    return value


def _timeout(value):
    if type(value) is not int or not 30 <= value <= 600:
        raise CommandError('--timeout debe indicar entre 30 y 600 segundos.')
    return value


def _loaded_without_generation(response):
    if (not isinstance(response, dict) or response.get('done') is not True
            or response.get('response') != '' or response.get('error')
            or response.get('thinking') or response.get('done_reason') == 'unload'):
        return False
    for field in ('eval_count', 'prompt_eval_count'):
        if field in response and (type(response[field]) is not int or response[field] != 0):
            return False
    return True


class Command(BaseCommand):
    help = ('Precarga el modelo local actual sin generar texto ni descargar archivos. '
            'Ejecutar voluntariamente antes de usar el chat; puede ocupar RAM y VRAM.')
    requires_system_checks = []
    requires_migrations_checks = False

    def add_arguments(self, parser):
        parser.add_argument('--keep-alive', default='30m',
                            help='Permanencia solicitada en memoria: de 5m a 120m (30m).')
        parser.add_argument('--timeout', type=int, default=300,
                            help='Espera máxima de precarga: de 30 a 600 segundos (300).')

    def handle(self, *args, **options):
        keep_alive = _keep_alive(options['keep_alive'])
        timeout = _timeout(options['timeout'])
        started = time.monotonic()
        try:
            origin = local_origin(getattr(settings, 'LITMATE_OLLAMA_URL',
                                          'http://127.0.0.1:11434'))
            model = getattr(settings, 'LITMATE_LOCAL_MODEL', 'qwen3.5:9b-q4_K_M')
            client = OllamaJSON(origin, timeout=timeout, total_timeout=timeout,
                                context=getattr(settings, 'LITMATE_LOCAL_CONTEXT', 16384))
            # /api/show acredita un GGUF descargado y rechaza modelos remotos/cloud.
            # No existe fallback, /api/pull ni selección de otro modelo.
            client.inspect_model(model)
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError()
            response = read_json_url(origin + '/api/generate',
                payload={'model': model, 'prompt': '', 'stream': False,
                         'keep_alive': keep_alive, 'options': {'num_ctx': client.context}},
                headers={'Content-Type': 'application/json'}, timeout=remaining, local=True)
        except ProviderUnavailable as exc:
            messages = {
                'modelo_no_descargado': 'El modelo configurado no está descargado; no se descargó nada.',
                'modelo_local_invalido': 'La configuración debe indicar un modelo local válido.',
                'se_requiere_modelo_descargado_localmente':
                    'Solo se permite precargar un modelo ya descargado y sin proveedor remoto.',
                'modelo_sin_chat': 'El modelo configurado no admite conversación.',
            }
            raise CommandError(messages.get(exc.code,
                'No se pudo comprobar el modelo local. Comprueba que Ollama esté abierto.')) from None
        except (ValueError, TypeError, OverflowError):
            raise CommandError('Configuración o respuesta local inválida; no se cambió la configuración.') from None
        except Exception:
            # Excepciones HTTP pueden incluir URLs, cabeceras o cuerpos del servidor.
            raise CommandError('No se pudo completar la precarga local dentro del tiempo permitido. '
                               'Comprueba que Ollama esté abierto e inténtalo de nuevo.') from None
        if not _loaded_without_generation(response):
            raise CommandError('Ollama no confirmó una precarga sin generación; no se publica su respuesta.')
        elapsed = max(0.0, time.monotonic() - started)
        self.stdout.write(f'Modelo local preparado: {model}; contexto: {client.context}; '
                          f'keep_alive: {keep_alive}; duración: {elapsed:.3f} s.')
        load_duration = response.get('load_duration')
        if type(load_duration) is int and 0 <= load_duration <= 2 ** 63 - 1:
            self.stdout.write(f'load_ms: {load_duration / 1_000_000:.3f}')
        self.stdout.write('Precarga confirmada sin generar texto ni tokens de respuesta; '
                          'sin descargas ni cambios de configuración.')
