"""Registro del mensaje recibido antes de la generación, con propietario."""
import re

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from core.models import ConversacionIA, MensajeIA


def contains_secret(message):
    return bool(re.search(
        r'\b(?:contrase[ñn]a|password|api[_ -]?key|access[_ -]?token|'
        r'session[_ -]?(?:id|key)|csrf[_ -]?token)\s*(?:es\s+|[:=]\s*)\S+'
        r'|\bBearer\s+[A-Za-z0-9._~+/-]{12,}',
        message, re.IGNORECASE,
    ))


def record_input(request, operation, message):
    if not request.user.is_authenticated:
        return
    from core.literary_ai_views import HISTORY_KEY
    owner = 'user:' + str(request.user.pk)
    state = request.session.get(HISTORY_KEY, {})
    if not isinstance(state, dict) or state.get('owner') != owner:
        state = {'owner': owner, 'turns': []}
    with transaction.atomic(using='accounts'):
        existing = MensajeIA.objects.filter(
            conversacion__usuario=request.user, rol='user',
            metadata_json__reader_operation=operation.pk,
        ).first()
        if existing:
            state['conversation_id'] = existing.conversacion_id
        else:
            conversation = ConversacionIA.objects.filter(
                pk=state.get('conversation_id'), usuario=request.user,
            ).first()
            if conversation is None:
                conversation = ConversacionIA.objects.create(
                    usuario=request.user, titulo=message[:120],
                )
            MensajeIA.objects.create(
                conversacion=conversation, rol='user', contenido=message,
                metadata_json={'reader_operation': operation.pk, 'delivery_status': 'pending'},
            )
            ConversacionIA.objects.filter(pk=conversation.pk).update(
                total_mensajes=F('total_mensajes') + 1, ultima_actividad=timezone.now(),
            )
            state['conversation_id'] = conversation.pk
    request.session[HISTORY_KEY] = state
    request.session.modified = True


def mark_input(operation):
    if operation.actor.startswith('u:') and operation.actor[2:].isdecimal():
        MensajeIA.objects.filter(
            conversacion__usuario_id=operation.actor[2:], rol='user',
            metadata_json__reader_operation=operation.pk,
        ).update(metadata_json={
            'reader_operation': operation.pk,
            'delivery_status': operation.status,
        })
