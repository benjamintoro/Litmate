"""Diez consultas HTTP/SSE secuenciales, cada una con sesión de ensayo nueva."""
import base64
import getpass
import hashlib
from http.cookiejar import CookieJar
import json
from pathlib import Path
import sqlite3
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPCookieProcessor, ProxyHandler, Request, urlopen
from core.bibliographic_http_probe import read_sse

ORIGIN = 'http://127.0.0.1:8007'
FOLDER = Path('.testtmp/recall-final-http-20261031').resolve()
OUTPUT = Path('reports/recuerdos_opencode_20261031/http_final_10.json')
CASES = [
    ('El principito', 'Un niño que vivía en un planeta diminuto, cuidaba una rosa y conoció a un zorro'),
    ('La metamorfosis', 'Alguien despierta convertido en un insecto horrible y su familia lo rechaza'),
    ('Fahrenheit 451', 'Una sociedad donde se prohíben los libros y los queman'),
    ('1984', 'Una historia sobre vigilancia constante y ausencia de libertad'),
    ('Don Quijote', 'Recuerdo un caballero que confunde molinos de viento con gigantes y viaja con su escudero'),
    ('Alicia o aclaración', 'Recuerdo una niña que sigue a un conejo blanco y cae por una madriguera'),
    ('Los juegos del hambre o aclaración', 'Recuerdo una muchacha que se ofrece voluntaria para una competición mortal televisada organizada por un régimen autoritario'),
    ('Moby Dick o aclaración', 'Recuerdo a un marinero obsesionado con perseguir una enorme ballena blanca'),
    ('Vaga: pedir pistas', 'Recuerdo una novela en la que dos amigos viajan y cambian su forma de ver la vida'),
    ('Abstracta: no identificar con certeza', 'Busco un libro sobre el deseo de pertenecer y el miedo a ser diferente'),
]


def main():
    if OUTPUT.exists():
        raise RuntimeError('No se sobrescribe el informe.')
    password = getpass.getpass('Clave del ensayo local8007 (oculta): ')
    authorization = 'Basic '+base64.b64encode(('demo:'+password).encode()).decode()
    report = {'scope':'real isolated HTTP/SSE, ten independent anonymous test sessions',
              'public_server_changed':False,'rows':[]}
    checked_covers = {}
    for expected, message in CASES:
        jar = CookieJar()
        opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(jar))
        def request(path, payload=None):
            headers = {'Authorization':authorization}
            if payload is not None:
                csrf = next(cookie.value for cookie in jar if cookie.name=='csrftoken')
                headers.update({'Content-Type':'application/json','Origin':ORIGIN,'X-CSRFToken':csrf})
            return opener.open(Request(ORIGIN+path, headers=headers,
                data=json.dumps(payload).encode() if payload is not None else None), timeout=55)
        row = {'expected':expected,'question':message,'errors':[]}
        try:
            with request('/chat/') as response:
                row['chat_html_ok'] = response.status==200 and b'chat-body-page' in response.read()
            started = time.monotonic()
            with request('/chatbot_query/',{'message':message,'progress':True}) as response:
                row['content_type'] = response.headers.get('Content-Type')
                stream, events, metrics = read_sse(response, started)
            ready = next((event.get('ready') for event in events if event.get('ready')),None)
            if ready:
                with request('/chatbot_finalize/',{'ready':ready}) as response:
                    final = json.load(response)
                with sqlite3.connect((FOLDER/'litmate_ai_stream_db.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
                    record = db.execute('SELECT result FROM stream_jobs WHERE key=?',
                                        (hashlib.sha256(ready.encode('ascii')).hexdigest(),)).fetchone()
                if record and record[0]:
                    internal = json.loads(record[0])
                    row['evidence'] = internal.get('result',{}).get('sources',[])
                    row['internal_diagnostics'] = internal.get('result',{}).get('diagnostics',{})
                    row['model_calls'] = internal.get('client',{}).get('calls')
            else:
                final = {'response': ''.join(event.get('token','') for event in events),
                         'books':next((e['books'] for e in events if 'books' in e),[])}
            row.update(final=final,seconds=round(time.monotonic()-started,3),timing=metrics,
                       sse_done='data: [DONE]' in stream)
            row['covers'] = []
            for card in final.get('books',[]):
                image = card.get('image_url')
                if not image:
                    row['covers'].append({'title':card.get('title'),'status':'absent'})
                elif image not in checked_covers:
                    entry = {'url':image}
                    if urlsplit(image).hostname in {'covers.openlibrary.org','books.google.com','books.googleusercontent.com'}:
                        try:
                            # Jamás enviar credenciales Basic a las portadas externas.
                            with urlopen(image,timeout=6) as response:
                                entry.update(status=response.status,content_type=response.headers.get('Content-Type'),
                                             bytes=len(response.read(1500000)))
                        except Exception as error:
                            entry['error'] = type(error).__name__
                    else:
                        entry['status'] = 'not_fetched_unknown_host'
                    checked_covers[image] = entry
                    row['covers'].append(entry)
                else:
                    row['covers'].append(checked_covers[image])
        except Exception as error:
            row['errors'].append(type(error).__name__)
        report['rows'].append(row)
        OUTPUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({'expected':expected,'seconds':row.get('seconds'),
            'status':row.get('final',{}).get('status'),'answer':row.get('final',{}).get('response'),
            'titles':[b.get('title') for b in row.get('final',{}).get('books',[])],
            'model_calls':row.get('model_calls'),'errors':row['errors']},ensure_ascii=True),flush=True)


if __name__=='__main__':
    main()
