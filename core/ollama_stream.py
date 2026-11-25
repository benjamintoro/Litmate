"""NDJSON local acotado: mide inferencia sin publicar borradores sin auditoría."""
import http.client
import json
import ssl
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from .ai_http import local_origin
from .ai_budget import budget_timeout,check_budget,BudgetExpired


class InferenceTransportTimeout(TimeoutError):
    def __init__(self,phase):
        self.phase=phase
        super().__init__('local_inference_'+phase+'_timeout')


def read_chat_stream(base_url,payload,*,timeout,metrics):
    """No sigue redirects, no usa proxies y nunca devuelve pensamientos al chat."""
    origin=local_origin(base_url);parsed=urlsplit(origin)
    started=time.monotonic();deadline=started+budget_timeout(timeout)
    connection=(http.client.HTTPSConnection(parsed.hostname,parsed.port,timeout=budget_timeout(timeout),context=ssl.create_default_context())
                if parsed.scheme=='https' else http.client.HTTPConnection(parsed.hostname,parsed.port,timeout=budget_timeout(timeout)))
    phase='connect';response=None;parts=[];total=0;final={};thinking_chars=0
    def remaining():
        check_budget()
        value=deadline-time.monotonic()
        if value<=0:raise InferenceTransportTimeout(phase)
        return budget_timeout(value)
    try:
        connection.connect();metrics['connect_ms']=round((time.monotonic()-started)*1000,3)
        phase='headers'
        connection.sock.settimeout(remaining())
        body=json.dumps(payload,ensure_ascii=False).encode('utf8')
        connection.request('POST','/api/chat',body=body,headers={'Content-Type':'application/json'})
        headers_started=time.monotonic();response=connection.getresponse()
        metrics['headers_wait_ms']=round((time.monotonic()-headers_started)*1000,3)
        if response.status!=200:raise HTTPError(origin+'/api/chat',response.status,'local_provider_http_error',response.headers,None)
        phase='body'
        while True:
            # http.client puede retirar connection.sock cuando el servidor cierra
            # la conexión. La referencia del stream sigue siendo la autorizada.
            sock=connection.sock
            if sock is not None:sock.settimeout(remaining())
            line=response.readline(65537)
            check_budget()
            if not line:break
            total+=len(line)
            if len(line)>65536 or total>2_000_000:raise ValueError('stream_local_demasiado_grande')
            if not line.strip():continue
            event=json.loads(line)
            if not isinstance(event,dict) or event.get('error'):raise ValueError('stream_local_invalido')
            metrics.setdefault('first_event_ms',round((time.monotonic()-started)*1000,3))
            message=event.get('message') or {}
            if not isinstance(message,dict):raise ValueError('mensaje_local_invalido')
            content=message.get('content','')
            if not isinstance(content,str):raise ValueError('contenido_local_invalido')
            if content:
                metrics.setdefault('first_content_ms',round((time.monotonic()-started)*1000,3))
                parts.append(content)
            thinking=message.get('thinking','')
            if isinstance(thinking,str):thinking_chars+=len(thinking)
            if event.get('done') is True:
                final=event;break
        metrics['response_bytes']=total
        metrics['thinking_chars']=thinking_chars
        result={**final,'done':final.get('done') is True,'message':{'role':'assistant','content':''.join(parts)}}
        return result
    except BudgetExpired:
        metrics['timeout_phase']='budget_or_cancellation'
        raise
    except TimeoutError as error:
        metrics['timeout_phase']=phase
        raise InferenceTransportTimeout(phase) from error
    finally:
        metrics['http_elapsed_ms']=round((time.monotonic()-started)*1000,3)
        if response is not None:response.close()
        connection.close()
