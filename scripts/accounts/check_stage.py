"""HTTP/SSE real del piloto; sólo localhost, cuentas sintéticas y sin pagos."""
import argparse
import base64
import getpass
from http.cookiejar import CookieJar
import json
from pathlib import Path
import secrets
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler, HTTPCookieProcessor
from scripts.demo.check_demo import SameOriginRedirect
from core.bibliographic_http_probe import read_sse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8006)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sin-progreso', action='store_true', help='Comprueba que el cliente no pueda evitar la finalización protegida.')
    parser.add_argument('--integral', action='store_true', help='Verifica replay, navegación, historial y el límite gratuito completo.')
    parser.add_argument('--web-completa', action='store_true', help='Comprueba páginas, enlaces y recursos sin escribir en el catálogo.')
    parser.add_argument('--personal', action='store_true', help='Favoritos, listas y perfil sintéticos con persistencia tras reinicio.')
    parser.add_argument('--solo-seguridad', action='store_true', help='Sólo lecturas y rechazo de rutas/métodos; no crea cuentas ni consume consultas.')
    parser.add_argument('--perfil-https', action='store_true', help='Ensaya el backend HTTPS en loopback, sin publicar ni activar Funnel.')
    parser.add_argument('--host', default='xato.taila70665.ts.net')
    args = parser.parse_args()
    if args.port == 8003:
        parser.error('8003 corresponde a la publicación. Este piloto sólo debe crear cuentas sintéticas en un ensayo.')
    if args.output.exists():
        parser.error('Usa una salida nueva.')
    origin = 'http://127.0.0.1:' + str(args.port)
    logical_origin = 'https://' + args.host if args.perfil_https else origin
    password = getpass.getpass('Contraseña Basic del servidor de ENSAYO (oculta): ')
    authorization = 'Basic ' + base64.b64encode(('demo:' + password).encode()).decode()
    password = None
    jar = CookieJar()
    opener = build_opener(ProxyHandler({}), SameOriginRedirect(origin), HTTPCookieProcessor(jar))
    report = {'scope': 'isolated real HTTP/SSE pilot, synthetic account', 'public_server_changed': False,
              'checks': {}, 'conversation': []}
    report['https_backend'] = args.perfil_https
    report['public_https_tested'] = False

    def request(path, data=None, *, form=False, authenticated=True, extra_headers=None):
        headers = {'Authorization': authorization} if authenticated else {}
        if args.perfil_https:
            # Sólo el comprobador del backend: no se rebaja la cookie de la app.
            headers.update(Host=args.host, Cookie='; '.join(cookie.name+'='+cookie.value for cookie in jar))
        if extra_headers:
            headers.update(extra_headers)
        if data is not None:
            headers.update({'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json',
                            'Origin': logical_origin})
            headers['X-CSRFToken'] = next(cookie.value for cookie in jar if cookie.name == 'csrftoken')
        body = urlencode(data).encode() if form else json.dumps(data).encode() if data is not None else None
        try:
            return opener.open(Request(origin+path, headers=headers, data=body), timeout=48)
        except HTTPError as error:
            return error

    def query(message, operation_id=None):
        started = time.monotonic()
        with request('/chatbot_query/', {'message': message, 'request_id': operation_id or secrets.token_hex(16), 'progress': not args.sin_progreso}) as response:
            if response.status != 200:
                return response.status, json.load(response)
            stream, events, metrics = read_sse(response, started)
        ready = next((event['ready'] for event in events if 'ready' in event), None)
        if ready:
            for attempt in range(3):
                with request('/chatbot_finalize/', {'ready': ready}) as final:
                    data, status = json.load(final), final.status
                if status != 409:
                    break
                time.sleep(1)
        else:
            data = {'response': ''.join(event.get('token', '') for event in events), 'status': 'direct',
                    'books': next((event['books'] for event in events if 'books' in event), [])}
            status = 200
        report['conversation'].append({'question': message, 'http_status': status, 'answer': data.get('response'),
            'status': data.get('status'), 'books': data.get('books', []), 'seconds': time.monotonic()-started,
            'sse_done': 'data: [DONE]' in stream, 'timing': metrics})
        if message != 'Hola':
            report['checks']['guarded_finalization_despite_client_option'] = ready is not None
        return status, data

    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding='utf-8')

    try:
        if args.solo_seguridad:
            for path in ('/chat/', '/static/js/chatbot.js'):
                with request(path, authenticated=False) as response:
                    report['checks']['basic_required:' + path] = response.status == 401
                    response.read()
            for path in ('/.env', '/admin/', '/admin/login/', '/backups/', '/data/accounts/users.sqlite3',
                         '/data/accounts/users.sqlite3.signing.dpapi', '/media/profile_pics/private.jpg',
                         '/suscripciones/iniciar-pago/'):
                with request(path) as response:
                    report['checks']['private_blocked:' + path] = response.status == 404
                    response.read()
            with request('/chat/', extra_headers={'Host': 'invalid.example'}) as response:
                report['checks']['host_rejected'] = response.status == 400
                response.read()
            with request('/favoritos/agregar/') as response:
                report['checks']['mutations_require_post'] = response.status == 405
                response.read()
            with request('/api/listas/obtener/') as response:
                report['checks']['library_requires_account'] = response.status == 401
                response.read()
            save()
            print(json.dumps(report['checks']))
            return 0 if all(report['checks'].values()) else 1
        with request('/chat/') as response:
            report['checks']['chat_page'] = response.status == 200
            response.read()
        if args.web_completa:
            from scripts.demo.frontend_checks import verify_frontend
            report['frontend'] = verify_frontend(request, reader_accounts=True)
            report['checks']['frontend_complete'] = all(report['frontend']['checks'].values())
        guest_operation = secrets.token_hex(16)
        status, _ = query('Hola', guest_operation)
        report['checks']['guest_first_query'] = status == 200
        if args.integral:
            status, _ = query('Hola', guest_operation)
            report['checks']['guest_retry_replays_without_new_unit'] = status == 200
            for path in ('/about/', '/suscripciones/planes/', '/chat/'):
                with request(path) as response:
                    response.read()
        with request('/chatbot_query/', {'message': 'Segunda consulta', 'request_id': secrets.token_hex(16)}) as response:
            report['checks']['guest_second_rejected'] = response.status == 429 and json.load(response).get('error') == 'guest_limit'
        username = 'piloto_' + secrets.token_hex(5)
        account_password = secrets.token_urlsafe(28)
        with request('/registro/', {'username': username, 'email': username+'@example.invalid',
                     'password': account_password, 'password_confirm': account_password}, form=True) as response:
            report['checks']['register_to_plans'] = response.status == 200 and response.url.endswith('/suscripciones/planes/')
            response.read()
        with request('/cuenta/activar-gratis/', {'plan': 'gratis'}, form=True) as response:
            report['checks']['free_to_chat_without_payment'] = response.status == 200 and response.url.endswith('/chat/')
            response.read()
        status, data = query('Recomiéndame dos novelas de fantasía en español')
        report['checks']['real_recommendations'] = status == 200 and len(data.get('books', [])) == 2
        personal_ids = {}
        if args.personal:
            book = {'google_id': 'fixture-http-personal', 'titulo': 'Libro de ensayo personal', 'autores': 'Autora sintética',
                    'imagen_url': 'https://covers.openlibrary.org/b/id/1-M.jpg'}
            with request('/favoritos/agregar/', book) as response:
                item = json.load(response)
                personal_ids['favorite'] = item.get('id')
                report['checks']['favorite_add'] = response.status == 200 and item.get('status') == 'ok'
            with request('/favoritos/agregar/', book) as response:
                report['checks']['favorite_idempotent'] = json.load(response).get('status') == 'exists'
            with request('/api/listas/crear/', {'nombre': 'Lista de ensayo HTTP'}) as response:
                personal_ids['list'] = json.load(response).get('id')
                report['checks']['private_list_created'] = response.status == 200 and bool(personal_ids['list'])
            with request('/api/listas/agregar-libro/', {**book, 'lista_id': personal_ids['list']}) as response:
                personal_ids['item'] = json.load(response).get('id')
                report['checks']['list_book_added'] = response.status == 200 and bool(personal_ids['item'])
            with request(f'/cuenta/listas/{personal_ids["list"]}/editar/', {'nombre': 'Lista renombrada HTTP'}, form=True) as response:
                report['checks']['list_renamed'] = response.status == 200 and 'Lista renombrada HTTP' in response.read().decode()
            with request('/perfil/editar/', {'nombre': 'Lector sintético HTTP', 'apellido': 'Ensayo', 'pais': 'Chile',
                         'meta_anual_libros': 24, 'biografia': 'Biografía de prueba aislada'}, form=True) as response:
                report['checks']['profile_edit'] = response.status == 200 and 'Lector sintético HTTP' in response.read().decode()
        with request('/api/cuota-ia/') as response:
            before = json.load(response)['cuota']
        report['checks']['model_limit_15_and_one_used'] = before['limite'] == 15 and before['usadas'] == 1
        if args.perfil_https:
            private_cookies = {cookie.name: cookie.secure for cookie in jar if cookie.name in {
                'csrftoken', 'litmate_visitor_v1', 'litmate_reader_sessionid'}}
            report['checks']['https_secure_cookies'] = len(private_cookies) == 3 and all(private_cookies.values())
        save()
        print('FASE_ANTES_COMPLETA; esperando reinicio del servidor de ENSAYO, no del público.', flush=True)
        input(f'Pulsa Enter cuando {args.port} vuelva a estar listo: ')
        with request('/api/cuota-ia/') as response:
            after = json.load(response)['cuota']
        report['checks']['same_session_plan_and_quota_after_restart'] = before == after
        if args.personal:
            with request('/cuenta/biblioteca/') as response:
                body = response.read().decode()
                report['checks']['personal_data_after_restart'] = response.status == 200 and all(
                    text in body for text in ('Libro de ensayo personal', 'Lista renombrada HTTP'))
            with request('/perfil/editar/') as response:
                report['checks']['profile_after_restart'] = 'Biografía de prueba aislada' in response.read().decode()
            with request(f'/favoritos/eliminar/{personal_ids["favorite"]}/', {}, form=True) as response:
                report['checks']['favorite_remove'] = response.status == 200
                response.read()
            with request(f'/api/listas/quitar-libro/{personal_ids["item"]}/', {}, form=True) as response:
                report['checks']['list_book_removed'] = response.status == 200
                response.read()
            with request(f'/api/listas/eliminar/{personal_ids["list"]}/', {'confirmar': 'si'}, form=True) as response:
                body = response.read().decode()
                report['checks']['list_deleted_with_confirmation'] = response.status == 200 and 'Lista renombrada HTTP' not in body
        status, data = query('Cuéntame más del segundo')
        second_title = report['conversation'][-2]['books'][1]['title'] if report['checks']['real_recommendations'] else ''
        report['checks']['followup_after_restart'] = status == 200 and bool(second_title) and second_title.casefold() in data.get('response', '').casefold()
        with request('/logout/', {}, form=True) as response:
            response.read()
        with request('/login/', {'username_or_email': username, 'password': account_password}, form=True) as response:
            report['checks']['login_to_plans_after_restart'] = response.status == 200 and response.url.endswith('/suscripciones/planes/')
            response.read()
        with request('/api/cuota-ia/') as response:
            quota = json.load(response)['cuota']
        report['checks']['logout_login_does_not_reset_quota'] = quota['usadas'] == 2 and quota['limite'] == 15
        if args.integral:
            with request('/perfil/') as response:
                report['checks']['private_history_page'] = response.status == 200 and 'Mis conversaciones' in response.read().decode()
            for _ in range(13):
                status, _ = query('Hola')
                if status != 200:
                    break
            with request('/api/cuota-ia/') as response:
                quota = json.load(response)['cuota']
            report['checks']['free_15_allowed_and_persistent'] = status == 200 and quota['usadas'] == 15 and quota['restantes'] == 0
            status, rejected = query('Consulta 16')
            report['checks']['free_16_rejected'] = status == 429 and rejected.get('error') == 'quota_exceeded'
        save()
        print(json.dumps(report['checks']), flush=True)
        return 0 if all(report['checks'].values()) else 1
    finally:
        save()


if __name__ == '__main__':
    raise SystemExit(main())
