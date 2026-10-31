"""HTTP/SSE contra Waitress en localhost. No configura túneles ni modifica MySQL."""
import argparse
import base64
import getpass
from http.cookies import SimpleCookie
import json
import re
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


class SameOriginRedirect(HTTPRedirectHandler):
    """Nunca reenvía la clave Basic a otro dominio ni degrada HTTPS a HTTP."""
    def __init__(self, origin):
        self.origin = self.identity(urlsplit(origin))

    @staticmethod
    def identity(parts):
        return parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urlsplit(newurl)
        if parts.username or parts.password or self.identity(parts) != self.origin:
            raise URLError('cross_origin_redirect_rejected')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--puerto', type=int, default=8002)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--perfil-https', action='store_true', help='Prueba el backend tras terminación TLS; no demuestra HTTPS externo.')
    parser.add_argument('--publico', action='store_true',
                        help='Usa HTTPS 443 con validación TLS; requiere --host del dispositivo Tailscale.')
    parser.add_argument('--question', action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seguridad-ampliada', action='store_true')
    parser.add_argument('--web-completa', action='store_true', help='Recorre páginas, navegación, catálogo y recursos antes del SSE.')
    args = parser.parse_args()
    if args.publico:
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.[a-z0-9-]+\.ts\.net', args.host):
            parser.error('Indica el DNS exacto de tu dispositivo, sin URL, credenciales ni puerto.')
        args.puerto = 443
        args.perfil_https = True
    if args.output.exists():
        parser.error('Usa una salida nueva.')
    password = getpass.getpass('Contraseña de acceso demo (oculta): ')
    authorization = 'Basic ' + base64.b64encode(('demo:' + password).encode()).decode()
    password = None
    cookies = {}
    cookie_flags = {}
    origin = 'https://' + args.host if args.publico else 'http://127.0.0.1:' + str(args.puerto)
    public_origin = 'https://' + args.host if args.perfil_https else origin
    opener = build_opener(ProxyHandler({}), SameOriginRedirect(origin))
    def request(path, data=None, *, authenticated=True, csrf=True, host=None, extra_headers=None):
        headers = {'Host': host or (args.host if args.perfil_https else args.host + ':' + str(args.puerto))}
        if authenticated:
            headers['Authorization'] = authorization
        if cookies:
            headers['Cookie'] = '; '.join(key + '=' + value for key, value in cookies.items())
        if data is not None:
            headers.update({'Content-Type': 'application/json', 'Origin': public_origin})
            if csrf and 'csrftoken' in cookies:
                headers['X-CSRFToken'] = cookies['csrftoken']
        headers.update(extra_headers or {})
        query = Request(origin + path, headers=headers,
                        data=json.dumps(data).encode() if data is not None else None)
        try:
            response = opener.open(query, timeout=48)
        except HTTPError as error:
            response = error
        for value in response.headers.get_all('Set-Cookie', []):
            parsed = SimpleCookie()
            parsed.load(value)
            cookies.update({key: morsel.value for key, morsel in parsed.items()})
            cookie_flags.update({key: {'secure': bool(morsel['secure']),
                'httponly': bool(morsel['httponly']), 'samesite': morsel['samesite']}
                for key, morsel in parsed.items()})
        return response
    from core.bibliographic_http_probe import read_sse
    checks = {}
    for path, key in [('/chat/', 'chat_auth_required'), ('/static/js/chatbot.js', 'static_auth_required')]:
        with request(path, authenticated=False) as response:
            # Tras varios ensayos, el gateway puede responder 429 en lugar de
            # otro desafío 401: ambos impiden acceder sin credenciales.
            checks[key] = response.status in {401, 429}
            checks[key + '_http_status'] = response.status
    with request('/admin/') as response:
        checks['admin_blocked'] = response.status == 404
    with request('/chat/', host='invalid.example') as response:
        checks['unknown_host_blocked'] = response.status == 400
    with request('/chat/') as response:
        html = response.read().decode('utf-8')
        checks['chat_html'] = response.status == 200 and 'chat-character-page' in html
        checks['frame_denied'] = response.headers.get('X-Frame-Options') == 'DENY'
        checks['csrf_cookie_present'] = 'csrftoken' in cookies
        if args.perfil_https:
            checks['csrf_secure_flag'] = any('Secure' in value for value in response.headers.get_all('Set-Cookie', []))
            checks['hsts_present'] = bool(response.headers.get('Strict-Transport-Security'))
    for path, key in [('/static/js/chatbot.js', 'javascript'),
                      ('/static/assets/img/avatar/cuerpo.jpg', 'avatar')]:
        with request(path) as response:
            checks[key] = response.status == 200 and len(response.read()) > 100
    with request('/chatbot_query/', {'message': 'Hola'}, csrf=False) as response:
        checks['csrf_enforced'] = response.status == 403
    if args.seguridad_ampliada:
        with request('/') as response:
            checks['homepage_real_frontend'] = response.status == 200 and 'coverflowStage' in response.read().decode()
        for path in ('/.env', '/backups/', '/admin/login/', '/perfil/', '/test-error/500/',
                     '/suscripciones/iniciar-pago/', '/media/private.pdf', '/static/.env', '/static/../.env'):
            with request(path) as response:
                checks['blocked:' + path] = response.status in {400, 404}
        with request('/chat/', extra_headers={'Authorization': 'Basic ZGVtbzppbnZhbGlk'}) as response:
            checks['invalid_password_rejected'] = response.status in {401, 429}
        with request('/chat/', host='invalid.example', extra_headers={
                'X-Forwarded-Host': args.host, 'X-Forwarded-Proto': 'https'}) as response:
            checks['forwarded_headers_do_not_override_host'] = response.status == 400
        with request('/chatbot_query/', {'message': 'Hola'}, extra_headers={'Origin': 'https://invalid.example'}) as response:
            checks['foreign_origin_rejected'] = response.status == 403
        for message in (None, 'x' * 6001):
            with request('/chatbot_query/', {'message': message}) as response:
                checks['invalid_message:' + ('null' if message is None else 'too_long')] = response.status == 400
        with request('/chatbot_query/') as response:
            checks['query_requires_post'] = response.status == 405
        for path in ('/static/css/chat-books.css', '/static/js/litmate_safe.js?v=chat-v9'):
            with request(path) as response:
                body = response.read()
                checks['asset:' + path] = response.status == 200 and len(body) > 100
                if 'litmate_safe' in path:
                    checks['current_finalize_client'] = b'finalizeOptions' in body and b'Retry-After' in body
    frontend = None
    if args.web_completa:
        from scripts.demo.frontend_checks import verify_frontend
        frontend = verify_frontend(request)
        checks.update(frontend['checks'])
    report = {'scope': ('HTTPS URL from server; not an independent mobile-network test' if args.publico else
              'loopback backend after TLS termination' if args.perfil_https else 'local HTTP'),
              'public_https_tested': args.publico,
              'external_network_tested': False, 'checks': checks, 'frontend': frontend, 'conversation': []}
    for message in args.question or ['Hola']:
        started = time.monotonic()
        with request('/chatbot_query/', {'message': message, 'progress': True}) as response:
            content_type = response.headers.get('Content-Type', '')
            if response.status != 200 or 'text/event-stream' not in content_type:
                raise RuntimeError('La consulta no devolvió HTTP 200 y text/event-stream: ' + str(response.status))
            stream, events, metrics = read_sse(response, started)
        ready = next((event['ready'] for event in events if 'ready' in event), None)
        if ready is None:
            # Saludos y respuestas inmediatas ya finalizadas usan el protocolo
            # token existente. Conservar también errores reales del SSE.
            error = next((event for event in events if event.get('error')), {})
            final = {'response': error.get('response') or ''.join(
                event.get('token', '') for event in events),
                'status': error.get('error') or response.headers.get('X-LitMate-Status', 'unknown'),
                'books': next((event['books'] for event in events if 'books' in event), []),
                'diagnostics': {'direct_stream': not bool(error)}}
        else:
            with request('/chatbot_finalize/', {'ready': ready}) as response:
                final = json.load(response)
        report['conversation'].append({'question': message, 'status': final.get('status'),
            'answer': final.get('response'), 'books': final.get('books', []),
            'diagnostics': final.get('diagnostics', {}), 'sse_done': 'data: [DONE]' in stream,
            'seconds': round(time.monotonic() - started, 4), 'http_timing': metrics,
            'progress_before_ready': (metrics['first_progress_seconds'] is not None
                and metrics['verified_ready_seconds'] is not None
                and metrics['first_progress_seconds'] < metrics['verified_ready_seconds']),
            'progress_events': [{key: value for key, value in event.items()
                if key in {'stage', 'phase', 'elapsed_ms'}} for event in events
                if any(key in event for key in ('stage', 'phase'))]})
        report['cookie_flags'] = cookie_flags
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding='utf-8')
        print(json.dumps({key: report['conversation'][-1][key] for key in ('question','status','seconds')}, ensure_ascii=True), flush=True)
    print(json.dumps({'checks': checks, 'external_network_tested': False}), flush=True)
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
