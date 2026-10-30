"""HTTP/SSE local real con MySQL y cookies firmadas, sin crear datos de lectores."""
import json
import threading
import time
from http.cookiejar import CookieJar
from socketserver import ThreadingMixIn
from urllib.request import Request, ProxyHandler, HTTPCookieProcessor, build_opener
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server
from django.core.handlers.wsgi import WSGIHandler
from django.test import override_settings
from .knowledge_models import KBRecord
from .models import Libro


def run_conversation(messages, *, before_turn=None, after_turn=None):
    """Una misma sesión HTTP/SSE real; no escribe usuarios o historial MySQL."""
    class Server(ThreadingMixIn, WSGIServer):
        daemon_threads=True
    class Quiet(WSGIRequestHandler):
        def log_message(self,*args):pass
    results=[]
    with override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies'):
        with make_server('127.0.0.1',0,WSGIHandler(),server_class=Server,handler_class=Quiet) as server:
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            origin='http://127.0.0.1:'+str(server.server_port)
            cookies=CookieJar()
            client=build_opener(ProxyHandler({}),HTTPCookieProcessor(cookies))
            try:
                with client.open(origin+'/chat/',timeout=10) as response:response.read()
                for message in messages:
                    if before_turn:
                        before_turn(message)
                    csrf=next(cookie.value for cookie in cookies if cookie.name=='csrftoken')
                    headers={'Content-Type':'application/json','Origin':origin,'X-CSRFToken':csrf}
                    started=time.monotonic()
                    request=Request(origin+'/chatbot_query/',data=json.dumps({'message':message,'progress':True}).encode(),
                                    headers=headers,method='POST')
                    with client.open(request,timeout=45) as response:stream=response.read().decode()
                    events=[json.loads(line[6:]) for line in stream.splitlines() if line.startswith('data: {')]
                    ready=next((event['ready'] for event in events if 'ready' in event),None)
                    if ready:
                        request=Request(origin+'/chatbot_finalize/',data=json.dumps({'ready':ready}).encode(),
                                        headers=headers,method='POST')
                        with client.open(request,timeout=15) as response:final=json.load(response)
                    else:
                        final={'status':'protocol_error','response':stream}
                    results.append({'question':message,'answer':final.get('response'),
                        'status':final.get('status'),'books':final.get('books',[]),
                        'sources':final.get('sources',[]),
                        'diagnostics':final.get('diagnostics',{}),'seconds':round(time.monotonic()-started,4),
                        'sse_done':'data: [DONE]' in stream})
                    if after_turn:
                        after_turn(results[-1])
            finally:
                server.shutdown();thread.join(timeout=5)
    return results


def run_probe(record_ids=None, *, question=None, require_sql_card=True, must_contain=()):
    from .bibliographic_repository import lookup_sources
    candidates = KBRecord.objects.filter(kind='edition', status='source_metadata')
    if record_ids is not None:
        candidates = candidates.filter(id__in=list(record_ids))
    if question is None:
        candidate = next(record for record in candidates.order_by('id')[:100]
                         if not Libro.objects.filter(titulo__iexact=record.label).exists()
                         and lookup_sources(record.label))
        question = '¿Quién escribió ' + candidate.label + '?'
    class Server(ThreadingMixIn, WSGIServer):
        daemon_threads = True
    class Quiet(WSGIRequestHandler):
        def log_message(self, *args):
            pass
    with override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies'):
        with make_server('127.0.0.1', 0, WSGIHandler(), server_class=Server, handler_class=Quiet) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            origin = 'http://127.0.0.1:' + str(server.server_port)
            cookies = CookieJar()
            client = build_opener(ProxyHandler({}), HTTPCookieProcessor(cookies))
            try:
                with client.open(origin+'/chat/', timeout=10) as response:
                    response.read()
                csrf = next(cookie.value for cookie in cookies if cookie.name == 'csrftoken')
                start = time.monotonic()
                headers = {'Content-Type':'application/json', 'Origin': origin, 'X-CSRFToken': csrf}
                request = Request(origin+'/chatbot_query/', data=json.dumps(
                    {'message':question,'progress':True}).encode(), headers=headers, method='POST')
                with client.open(request, timeout=45) as response:
                    stream = response.read().decode()
                events = [json.loads(line[6:]) for line in stream.splitlines() if line.startswith('data: {')]
                ready = next(event['ready'] for event in events if 'ready' in event)
                request = Request(origin+'/chatbot_finalize/', data=json.dumps({'ready':ready}).encode(),
                                  headers=headers, method='POST')
                with client.open(request, timeout=15) as response:
                    final = json.load(response)
                sql_cards = [card for card in final.get('books', []) if card['id'].startswith('sqlkb:')]
                text = str(final.get('response',''))
                return {'passed': final.get('status') == 'answered' and (bool(sql_cards) or not require_sql_card)
                        and all(value.casefold() in text.casefold() for value in must_contain),
                    'question':question,'answer':final.get('response'),'status':final.get('status'),
                    'not_in_legacy_catalog':True if require_sql_card else None,'sse_done':'data: [DONE]' in stream,
                    'seconds':round(time.monotonic()-start,4),'cards':final.get('books'),
                    'diagnostics':final.get('diagnostics'), 'reader_data_written':False,
                    'sources':final.get('sources', [])}
            finally:
                server.shutdown()
                thread.join(timeout=5)
