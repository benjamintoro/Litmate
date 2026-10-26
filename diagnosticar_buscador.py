"""Diagnostico real y de solo lectura de Docker, SearXNG JSON y su adaptador.

No carga settings de produccion, no abre su base ni imprime variables de entorno.
Los resultados son candidatos: la salud del contenedor no verifica hechos.
"""
import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener


QUERIES = ('Papelucho y el marciano', 'El nombre de la rosa',
           'El se\u00f1or de los anillos')
ORIGIN = 'http://127.0.0.1:8080'


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def summarize_payload(data):
    """Preserva resultados, fallos y la distincion lista/infobox sin contenido."""
    if not isinstance(data, dict) or not isinstance(data.get('results'), list):
        return {'status': 'invalid_response', 'results_count': 0}
    results = [row for row in data['results'] if isinstance(row, dict)]
    failures = data.get('unresponsive_engines')
    if not isinstance(failures, list):
        return {'status': 'invalid_response', 'results_count': 0}
    return {
        'status': ('partial' if results else 'unavailable') if failures
                  else ('ok' if results else 'empty'),
        'results_count': len(results),
        'infoboxes_count': len(data.get('infoboxes') or []),
        'unresponsive_engines': [item[:2] for item in failures
                                if isinstance(item, list) and len(item) >= 2],
        'results': [{'title': item.get('title'), 'url': item.get('url'),
                     'engines': item.get('engines'),
                     'has_content': bool(item.get('content'))}
                    for item in results[:8]],
    }


def probe_json(query, timeout=9):
    started = time.monotonic()
    row = {'query': query}
    params = {'q': query, 'format': 'json', 'language': 'es', 'safesearch': 1,
              'engines': 'wikipedia,openlibrary,mwmbl'}
    opener = build_opener(ProxyHandler({}), NoRedirects())
    try:
        with opener.open(ORIGIN + '/search?' + urlencode(params), timeout=timeout) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError('response_too_large')
            row.update(summarize_payload(json.loads(raw)))
            row['http_status'] = response.status
    except (OSError, ValueError, URLError) as exc:
        # Ni URLs con credenciales, ni cuerpos remotos, ni mensajes libres.
        row.update(status='unavailable', error=type(exc).__name__)
    row['seconds'] = round(time.monotonic() - started, 3)
    return row


def _docker(*args):
    try:
        result = subprocess.run(['docker', *args], capture_output=True, text=True,
                                check=False, timeout=12)
        if result.returncode:
            return {'status': 'unavailable', 'exit_code': result.returncode}
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {'status': 'unavailable', 'error': type(exc).__name__}


def probe_docker():
    # Se seleccionan campos: nunca docker inspect completo ni Config.Env.
    return {
        'version': _docker('version', '--format', '{{json .}}'),
        'container_state': _docker('inspect', '--format', '{{json .State}}',
                                   'litmate-searxng-1'),
        'published_ports': _docker('inspect', '--format', '{{json .NetworkSettings.Ports}}',
                                   'litmate-searxng-1'),
    }


def probe_adapter():
    """Usa Django real con SQLite en memoria; rechaza settings ya configurados."""
    from django.conf import settings
    if settings.configured:
        raise RuntimeError('Ejecuta el diagnostico en un proceso aislado')
    os.environ.pop('DJANGO_SETTINGS_MODULE', None)
    settings.configure(
        SECRET_KEY='litmate-search-diagnostic-only',
        INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes',
                        'core', 'suscripciones'],
        DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
        CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
        BASE_DIR=Path(__file__).resolve().parent,
        LITMATE_AI_USE_SEARXNG=True, LITMATE_SEARXNG_URL=ORIGIN,
        LITMATE_SEARXNG_ENGINES=('wikipedia', 'openlibrary', 'mwmbl'))
    import django
    django.setup()
    from core.literary_search import search_searx
    from core.literary_sources import research_scope, research_snapshot
    rows = []
    for query in QUERIES:
        started = time.monotonic()
        with research_scope():
            found = search_searx(query)
            row = {'query': query, 'status': getattr(found, 'status', 'unknown'),
                   'results_count': len(found), 'providers': getattr(found, 'providers', {}),
                   'results': [{'title': item.get('title'), 'url': item.get('url'),
                                'source': item.get('source')} for item in found],
                   'research': research_snapshot()}
        row['seconds'] = round(time.monotonic() - started, 3)
        rows.append(row)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--skip-adapter', action='store_true')
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error('El informe ya existe; usa otra ruta para conservar la evidencia anterior.')
    report = {'recorded_at': datetime.now(timezone.utc).isoformat(),
              'executed_real_services': True, 'docker': probe_docker(),
              'api_json': [probe_json(query) for query in QUERIES],
              'django_adapter': [] if args.skip_adapter else probe_adapter(),
              'notes': ['Container health is not proof of relevant search results.',
                        'Search hits are candidates, not factual verification.',
                        'No production Django settings/database or secret files loaded.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'api_json': report['api_json'],
                      'django_adapter': report['django_adapter']}, ensure_ascii=True))
    return 0 if any(item.get('results_count') for item in report['api_json']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
