"""Reparaciones breves del diálogo, basadas solo en la petición del lector."""
import re


def conversation_repair(message, history=(), topic_context=None):
    from .literary_ai import ChatResult, normalized, sanitized_history
    value = normalized(message).strip(' ¿?¡!.,')
    if not (re.fullmatch(r'(?:que{3,}|eh{3,}|como{3,}|what+)', value)
            or re.fullmatch(r'(?:no[, ]+)?(?:no me referia a eso|no era eso|'
                            r'eso no es lo que pedi|no entendiste|no me entendiste|'
                            r'te equivocaste)', value)):
        return None
    from .literary_conversation import _explicit_subject, _safe_subject
    context = topic_context or {}
    subject = _safe_subject(context.get('subject'))
    intent = context.get('intent')
    for turn in reversed(sanitized_history(list(history))):
        if subject:
            break
        subject = _safe_subject(_explicit_subject(turn['question']))
        intent = turn.get('intent', '')
        if subject:
            break
        # No arrastrar una materia más antigua a través de una consulta distinta.
        if turn.get('books'):
            break
    text = 'Mi respuesta anterior no atendió bien tu consulta.'
    if subject and intent == 'recommend':
        text += ' Retomemos los libros sobre ' + subject + '. ¿Prefieres una recomendación de ficción o de no ficción?'
    elif subject:
        text += ' Retomemos tu búsqueda sobre ' + subject + '. ¿Intentas recordar una obra concreta o quieres recomendaciones?'
    else:
        text += ' ¿Qué parte interpreté mal o qué libro o tema quieres retomar?'
    return ChatResult(text, 'clarification', intent=intent,
                      diagnostics={'conversation_repair': True, 'model_calls': 0})
