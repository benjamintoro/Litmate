"""Envoltorio de transporte/cuota: el motor literario y su auditoría se reutilizan."""
import json
import copy
import re
from types import SimpleNamespace
from django.utils import timezone
from django.db import DatabaseError, transaction
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from core import literary_ai_views
from .models import QueryOperation
from .usage import reserve, finish, UsageError


def error_response(error):
    response = JsonResponse({'error': error.code, 'response': error.text,
        'login_url': '/login/', 'register_url': '/registro/', 'plans_url': '/suscripciones/planes/'}, status=error.status)
    if error.status == 409:
        response['Retry-After'] = '1'
    return response


def replay(op):
    body = op.result
    if op.status == 'failed':
        return JsonResponse(body, status=503)
    events = [{'token': body.get('response', '')}, {'books': body.get('books', [])}]
    response = StreamingHttpResponse(
        ['data: ' + json.dumps(event, ensure_ascii=False) + '\n\n' for event in events] + ['data: [DONE]\n\n'],
        content_type='text/event-stream; charset=utf-8')
    response['Cache-Control'] = 'no-store'
    response['X-LitMate-Idempotent-Replay'] = '1'
    return response


@never_cache
@require_POST
@csrf_protect
def query(request):
    if request.content_type != 'application/json' or len(request.body) > 48000:
        return JsonResponse({'response': 'Envía un mensaje JSON válido.'}, status=400)
    try:
        data = json.loads(request.body)
        message = data.get('message') if isinstance(data, dict) else None
        if not isinstance(message, str) or not message.strip() or len(message) > literary_ai_views.MAX_MESSAGE:
            raise ValueError()
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'response': 'No pude leer el mensaje.'}, status=400)
    if not request.user.is_authenticated and not request.reader_identity_established:
        return error_response(UsageError('visitor_identity_required', 'Abre el chat para establecer tu identidad de visitante.', 409))
    request_id = data.get('request_id')
    if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,64}',request_id):
        return error_response(UsageError('request_id_required','La solicitud necesita un identificador válido.',400))
    try:
        if not QueryOperation.objects.filter(actor=request.reader_actor,request_id=request_id).exists():
            if not literary_ai_views.rate_allowed(request):
                response=error_response(UsageError('resource_limit','Has enviado demasiadas solicitudes. Espera un minuto.'))
                response['Retry-After']='60'
                return response
            request.reader_rate_approved=True
        op, reused = reserve(request.reader_actor, request.user, data.get('request_id'), message)
    except UsageError as error:
        return error_response(error)
    except DatabaseError:
        return JsonResponse({'error': 'storage_unavailable', 'response': 'No fue posible comprobar tu cuota. Inténtalo más tarde.'}, status=503)
    if reused:
        return replay(op)
    # Una petición API no puede esquivar la confirmación de cuota/historial
    # desactivando progress. Los saludos/rechazos locales siguen siendo inmediatos.
    request.reader_force_progress = True
    try:
        response = literary_ai_views.chatbot_query(request)
    except Exception:
        finish(op.pk, {'error': 'technical_failure', 'response': 'No fue posible iniciar la consulta.'}, failed=True)
        raise
    if not response.streaming:
        finish(op.pk, {'error': 'technical_failure', 'response': 'No fue posible completar la consulta.'}, failed=True)
        return response
    original = response.streaming_content

    def stream():
        parts, books, ready, ended = [], [], None, False
        technical_failure = response.get('X-LitMate-Status') == 'unavailable'
        try:
            # El productor actual entrega cada evento SSE completo, sin fragmentar JSON.
            for chunk in original:
                text = chunk.decode('utf-8') if isinstance(chunk, bytes) else chunk
                for line in text.splitlines():
                    if not line.startswith('data: ') or line[6:] == '[DONE]':
                        continue
                    event = json.loads(line[6:])
                    if event.get('error'):
                        technical_failure = True
                    if 'ready' in event:
                        ready = event['ready']
                        QueryOperation.objects.filter(pk=op.pk, status='pending').update(stream_token=ready)
                    if event.get('token'):
                        parts.append(event['token'])
                    if 'books' in event:
                        books = event['books']
                yield chunk
            ended = True
        finally:
            if ready is None:
                has_answer = bool(parts) and not technical_failure
                finish(op.pk, {'response': ''.join(parts), 'books': books,
                              'error': None if has_answer else 'technical_failure'}, failed=not has_answer)
            elif not ended:
                finish(op.pk, {'error': 'stream_interrupted', 'response': 'Se interrumpió la transmisión.'}, failed=True)
    response.streaming_content = stream()
    return response


@never_cache
@require_POST
@csrf_protect
def finalize(request):
    try:
        if len(request.body) > 2048:
            raise ValueError()
        data = json.loads(request.body)
        token = data.get('ready') if isinstance(data, dict) else None
        if not isinstance(token, str) or len(token) > 128:
            raise ValueError()
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'response': 'Solicitud inválida.'}, status=400)
    op = QueryOperation.objects.filter(actor=request.reader_actor, stream_token=token).first()
    if op is None:
        return JsonResponse({'response': 'Esta respuesta no pertenece a tu identidad.'}, status=404)
    if op.status == 'completed':
        return JsonResponse(op.result)
    if op.status != 'pending':
        return JsonResponse({'response': 'La operación caducó. Envía una consulta nueva.'}, status=409)
    if op.expires_at <= timezone.now():
        finish(op.pk, {}, failed=True)
        return JsonResponse({'response': 'La operación caducó. Envía una consulta nueva.'}, status=409)
    class AbortPublication(Exception):
        def __init__(self, response): self.response = response
    before = copy.deepcopy(request.session.get(literary_ai_views.HISTORY_KEY, {}))
    request.reader_operation_id = op.pk
    try:
        with transaction.atomic(using='accounts'):
            response = literary_ai_views.chatbot_finalize(request)
            if response.status_code != 200:
                raise AbortPublication(response)
            result = json.loads(response.content)
            if request.user.is_authenticated:
                from core.models import MensajeIA
                if not MensajeIA.objects.filter(conversacion__usuario=request.user,
                                                 metadata_json__reader_operation=op.pk).exists():
                    # Si el cache de transporte se confirmó pero la transacción
                    # privada anterior se revirtió, reutilizar el resultado ya
                    # auditado: no generar, cobrar dos veces ni perder el historial.
                    from core.ai_stream_jobs import claim_finalization, JobUnavailable, JobBusy, JobStale
                    try:
                        job = claim_finalization(token, literary_ai_views.stable_session_owner(request))
                    except (JobUnavailable, JobBusy, JobStale):
                        raise AbortPublication(JsonResponse({'response':'La respuesta pendiente ya no está disponible.'},status=409))
                    recovered = literary_ai_views.ChatResult(**job['result']['result'])
                    if recovered.remember:
                        state = request.session.get(literary_ai_views.HISTORY_KEY, {})
                        literary_ai_views.persist_turn_records(request, state, job['payload']['message'],
                            recovered, int(recovered.diagnostics.get('elapsed_ms', 0)),
                            SimpleNamespace(**job['result']['client']))
            if not finish(op.pk, result, failed=result.get('status') == 'unavailable'):
                op.refresh_from_db()
                if op.status == 'completed': return JsonResponse(op.result)
                raise AbortPublication(JsonResponse({'response':'La operación caducó antes de confirmarse.'},status=409))
        return response
    except AbortPublication as failure:
        request.session[literary_ai_views.HISTORY_KEY] = before
        return failure.response
    except DatabaseError:
        request.session[literary_ai_views.HISTORY_KEY] = before
        response = JsonResponse({'response':'No fue posible confirmar la respuesta. Reintenta la misma operación.'},status=409)
        response['Retry-After'] = '1'
        return response
