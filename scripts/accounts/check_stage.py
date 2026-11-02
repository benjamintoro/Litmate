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
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Usa una salida nueva.')
    origin = 'http://127.0.0.1:' + str(args.port)
    password = getpass.getpass('Contraseña Basic del servidor de ENSAYO (oculta): ')
    authorization = 'Basic ' + base64.b64encode(('demo:' + password).encode()).decode()
    password = None
    jar = CookieJar()
    opener = build_opener(ProxyHandler({}), SameOriginRedirect(origin), HTTPCookieProcessor(jar))
    report = {'scope': 'isolated real HTTP/SSE pilot, synthetic account', 'public_server_changed': False,
              'checks': {}, 'conversation': []}

    def request(path, data=None, *, form=False):
        headers = {'Authorization': authorization}
        if data is not None:
            headers.update({'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json',
                            'Origin': origin})
            headers['X-CSRFToken'] = next(cookie.value for cookie in jar if cookie.name == 'csrftoken')
        body = urlencode(data).encode() if form else json.dumps(data).encode() if data is not None else None
        try:
            return opener.open(Request(origin+path, headers=headers, data=body), timeout=48)
        except HTTPError as error:
            return error

    def query(message):
        started = time.monotonic()
        with request('/chatbot_query/', {'message': message, 'request_id': secrets.token_hex(16), 'progress': not args.sin_progreso}) as response:
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
        with request('/chat/') as response:
            report['checks']['chat_page'] = response.status == 200
            response.read()
        status, _ = query('Hola')
        report['checks']['guest_first_query'] = status == 200
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
        with request('/api/cuota-ia/') as response:
            before = json.load(response)['cuota']
        report['checks']['model_limit_15_and_one_used'] = before['limite'] == 15 and before['usadas'] == 1
        save()
        print('FASE_ANTES_COMPLETA; esperando reinicio del servidor de ENSAYO, no del público.', flush=True)
        input('Pulsa Enter cuando 8006 vuelva a estar listo: ')
        with request('/api/cuota-ia/') as response:
            after = json.load(response)['cuota']
        report['checks']['same_session_plan_and_quota_after_restart'] = before == after
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
        save()
        print(json.dumps(report['checks']), flush=True)
        return 0 if all(report['checks'].values()) else 1
    finally:
        save()


if __name__ == '__main__':
    raise SystemExit(main())
