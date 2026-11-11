"""Dos peticiones HTTP reales de la MISMA identidad sintética, sólo loopback."""
import argparse
import base64
import concurrent.futures
import getpass
import json
from pathlib import Path
import secrets
import time
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPCookieProcessor, ProxyHandler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8006)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.port not in (8006, 8007) or args.output.exists():
        parser.error('Usa un puerto de ensayo y un informe nuevo.')
    origin = 'http://127.0.0.1:' + str(args.port)
    password = getpass.getpass('Contraseña Basic del ENSAYO (oculta): ')
    auth = 'Basic ' + base64.b64encode(('demo:'+password).encode()).decode()
    password = None
    jar = CookieJar()
    browser = build_opener(ProxyHandler({}), HTTPCookieProcessor(jar))
    with browser.open(Request(origin+'/chat/', headers={'Authorization': auth}), timeout=15) as response:
        response.read()
    headers = {'Authorization': auth, 'Cookie': '; '.join(c.name+'='+c.value for c in jar),
               'Content-Type': 'application/json', 'Origin': origin,
               'X-CSRFToken': next(c.value for c in jar if c.name == 'csrftoken')}
    import threading
    barrier = threading.Barrier(2)
    def work(index):
        client = build_opener(ProxyHandler({}))
        body = json.dumps({'message': 'Hola', 'request_id': secrets.token_hex(16)}).encode()
        barrier.wait(timeout=5)
        started = time.monotonic()
        try:
            result = client.open(Request(origin+'/chatbot_query/', data=body, headers=headers), timeout=20)
        except HTTPError as error:
            result = error
        with result:
            result.read()
            return {'status': result.status, 'seconds': round(time.monotonic()-started, 4)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(work, range(2)))
    with browser.open(Request(origin+'/api/cuota-ia/', headers={'Authorization': auth}), timeout=15) as response:
        quota = json.load(response)['cuota']
    report = {'results': results, 'quota_used': quota['usadas'], 'production_used': False,
              'passed': sorted(r['status'] for r in results) == [200, 429] and quota['usadas'] == 1}
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
