"""Restauración y borrado explícito del chat activo, acotados a su propietario."""
import secrets

from django.db import DatabaseError, connections, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from core.literary_ai_views import HISTORY_KEY, STREAM_NONCE_KEY
from core.models import ConversacionIA, MensajeIA
from .models import QueryOperation


def active_conversation(request):
    state = request.session.get(HISTORY_KEY, {})
    if not request.user.is_authenticated or not isinstance(state, dict):
        return None
    if state.get('owner') != 'user:' + str(request.user.pk):
        return None
    return ConversacionIA.objects.filter(
        pk=state.get('conversation_id'), usuario=request.user,
    ).first()


@never_cache
@require_GET
def current(request):
    try:
        conversation = active_conversation(request)
        messages = []
        truncated = False
        if conversation:
            rows = list(conversation.mensajes.order_by('-id')[:201])
            truncated = len(rows) > 200
            for row in reversed(rows[:200]):
                if row.rol in {'user', 'assistant'}:
                    messages.append({'role': row.rol, 'text': row.contenido,
                        'books': row.metadata_json.get('books', []),
                        'status': row.metadata_json.get('delivery_status', 'completed')})
        elif not request.user.is_authenticated:
            state = request.session.get(HISTORY_KEY, {})
            for turn in state.get('turns', []) if isinstance(state, dict) else []:
                messages.extend([{'role': 'user', 'text': turn.get('question', '')},
                    {'role': 'assistant', 'text': turn.get('answer', ''), 'books': turn.get('books', [])}])
        return JsonResponse({'conversation_id': conversation.pk if conversation else None,
            'messages': messages, 'truncated': truncated})
    except DatabaseError:
        return JsonResponse({'response': 'No pudimos recuperar la conversación. Vuelve a intentarlo.'}, status=503)


@never_cache
@require_POST
@csrf_protect
def clear(request):
    if request.POST.get('confirm') != 'delete-current-conversation':
        return JsonResponse({'response': 'Confirma que deseas borrar la conversación actual.'}, status=400)
    try:
        with transaction.atomic(using='accounts'):
            if QueryOperation.objects.filter(actor=request.reader_actor, status='pending',
                                             expires_at__gt=timezone.now()).exists():
                return JsonResponse({'response': 'Espera a que termine la consulta antes de borrar el chat.'}, status=409)
            conversation = active_conversation(request)
            # Una pestaña antigua no debe borrar el chat que otra acaba de abrir.
            expected = request.POST.get('conversation_id', '')
            if expected != (str(conversation.pk) if conversation else ''):
                return JsonResponse({'response': 'El chat cambió en otra pestaña. Recarga antes de borrarlo.'}, status=409)
            if conversation:
                operation_ids = [row.get('reader_operation') for row in
                    conversation.mensajes.values_list('metadata_json', flat=True)]
                QueryOperation.objects.filter(actor=request.reader_actor, pk__in=[
                    value for value in operation_ids if value is not None]).update(
                        result={'response': 'Esta conversación fue eliminada.', 'books': []}, stream_token=None)
                # El Collector de Django también intenta actualizar un log del
                # catálogo que vive en otra base. El borrado privado se limita
                # a estas dos tablas, ambas verificadas por propietario.
                connection = connections['accounts']
                quote = connection.ops.quote_name
                with connection.cursor() as cursor:
                    cursor.execute(f'DELETE FROM {quote(MensajeIA._meta.db_table)} WHERE conversacion_id = %s',
                                   [conversation.pk])
                    cursor.execute(f'DELETE FROM {quote(ConversacionIA._meta.db_table)} WHERE id = %s AND usuario_id = %s',
                                   [conversation.pk, request.user.pk])
        request.session.pop(HISTORY_KEY, None)
        request.session[STREAM_NONCE_KEY] = secrets.token_urlsafe(32)
        request.session.modified = True
        return JsonResponse({'cleared': True})
    except DatabaseError:
        return JsonResponse({'response': 'No pudimos borrar la conversación. Vuelve a intentarlo.'}, status=503)
