"""Límite proporcionado de altas abiertas; sin IP ni fingerprint del dispositivo."""
import hashlib
import time
from django.conf import settings
from core.ai_concurrency import rate_increment


def signup_allowed(request):
    if not getattr(settings,'LITMATE_PRODUCTION_OPEN',False):
        return True
    if not request.reader_identity_established:
        return False
    identity=request.reader_visitor_hash
    day=int(time.time())//86400
    hour=int(time.time())//3600
    # Sólo se guardan claves hash y contadores. Un cupo global limita el abuso
    # por rotación de cookies; puede rechazar altas legítimas y se documenta.
    visitor='signup:'+hashlib.sha256((identity+':'+str(day)).encode()).hexdigest()
    return (rate_increment(visitor,86401)<=settings.LITMATE_SIGNUP_VISITOR_PER_DAY
            and rate_increment('signup-global:'+str(hour),3601)<=settings.LITMATE_SIGNUP_GLOBAL_PER_HOUR)
