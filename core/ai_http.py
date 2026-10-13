"""HTTP acotado. Servicios locales sin proxy y sin redirecciones."""
import json
import time
from .ai_budget import budget_timeout, check_budget
from urllib.parse import urlsplit
from urllib.request import (HTTPRedirectHandler, ProxyHandler, Request,
                            build_opener, urlopen)


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def local_origin(value):
    parsed = urlsplit(str(value or '').strip())
    if (parsed.scheme not in {'http', 'https'}
            or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {'', '/'}):
        raise ValueError('Solo se admiten servicios del mismo computador')
    port = parsed.port
    if port is None or not 1 <= port <= 65535:
        raise ValueError('Indica el puerto del servicio local')
    host = '[::1]' if parsed.hostname == '::1' else '127.0.0.1'
    return f'{parsed.scheme}://{host}:{port}'


def read_json_url(url, *, payload=None, headers=None, timeout=8, local=False):
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None
    request = Request(url, data=body, headers=headers or {},
                      method='POST' if body is not None else 'GET')
    opener = build_opener(ProxyHandler({}), NoRedirects()) if local else None
    open_request = opener.open if opener is not None else urlopen
    deadline = time.monotonic() + budget_timeout(timeout)
    with open_request(request, timeout=budget_timeout(timeout)) as response:
        raw = read_bounded(response, 2_000_000, deadline)
    check_budget()
    if len(raw) > 2_000_000:
        raise ValueError('Respuesta externa demasiado grande')
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError('Se esperaba un objeto JSON')
    return result


def read_bounded(response, maximum, deadline):
    """Acota bytes y tiempo total; una respuesta lenta no renueva el presupuesto."""
    chunks, size = [], 0
    read = getattr(response, 'read1', None) or response.read
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            from .ai_budget import BudgetExpired
            raise BudgetExpired('tiempo_total_agotado')
        remaining = budget_timeout(remaining)
        try:
            response.fp.raw._sock.settimeout(remaining)
        except (AttributeError, OSError):
            pass
        block = read(min(16384, maximum + 1 - size))
        check_budget()
        if time.monotonic() > deadline:
            from .ai_budget import BudgetExpired
            raise BudgetExpired('tiempo_total_agotado')
        if not block:
            break
        if not isinstance(block, bytes):
            raise ValueError('Respuesta HTTP inválida')
        size += len(block)
        if size > maximum:
            raise ValueError('Respuesta externa demasiado grande')
        chunks.append(block)
    return b''.join(chunks)
