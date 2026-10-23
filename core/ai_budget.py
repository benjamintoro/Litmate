"""Presupuesto compartido entre modelo, búsqueda y embeddings de una consulta."""
import time
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from threading import BoundedSemaphore

_deadline = ContextVar('litmate_ai_deadline', default=None)
# Sin cola ilimitada: una fuente atascada no permite acumular hilos por visita.
_chat_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='litmate-chat')
_chat_slots = BoundedSemaphore(2)
CHAT_RESPONSE_SECONDS = 30
CHAT_WORK_SECONDS = CHAT_RESPONSE_SECONDS - 1


class BudgetExpired(TimeoutError):
    pass


class WorkerBusy(Exception):
    pass


def chat_timeout(config):
    """Reserva un segundo para sesión/HTTP; .env antiguo no puede volver a 360 s."""
    try:
        value = float(getattr(config, 'LITMATE_CHAT_TIMEOUT', CHAT_WORK_SECONDS))
    except (TypeError, ValueError):
        value = CHAT_WORK_SECONDS
    return max(.1, min(value, CHAT_WORK_SECONDS))


def current_deadline():
    return _deadline.get()


def run_before_deadline(function, deadline, *args):
    """Espera acotada incluso si una dependencia ignora su timeout.

    El trabajo no recibe request/sesión ni publica/consume cuotas. Si vence la
    espera, se descarta su resultado. El slot y cualquier lease del modelo se
    conservan hasta que termine: nunca se finge haber cancelado un hilo Python.
    Las operaciones HTTP sí comparten el deadline y cierran su socket al vencer.
    """
    with request_budget(deadline):
        if not _chat_slots.acquire(blocking=False):
            raise WorkerBusy()

        def work():
            try:
                check_budget()
                result = function(*args)
                check_budget()
                return result
            finally:
                _chat_slots.release()

        try:
            future = submit_with_budget(_chat_pool, work)
        except BaseException:
            _chat_slots.release()
            raise
        try:
            return future.result(timeout=budget_timeout(CHAT_WORK_SECONDS))
        except FutureTimeout:
            # No liberar aquí: un proveedor no cooperativo puede seguir activo.
            raise BudgetExpired('tiempo_total_agotado') from None


def budget_timeout(maximum):
    deadline = _deadline.get()
    if deadline is None:
        return float(maximum)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise BudgetExpired('tiempo_total_agotado')
    return max(0.001, min(float(maximum), remaining))


def check_budget():
    budget_timeout(1)


@contextmanager
def request_budget(deadline):
    previous = _deadline.get()
    token = _deadline.set(min(previous, deadline) if previous is not None else deadline)
    try:
        check_budget()
        yield
    finally:
        _deadline.reset(token)


def submit_with_budget(pool, function, *args):
    # ContextVar no se transmite automáticamente a ThreadPoolExecutor.
    return pool.submit(copy_context().run, function, *args)


@contextmanager
def pool_in_budget(maximum):
    """El HTTP que excedió su espera no bloquea el retorno de la petición."""
    pool = ThreadPoolExecutor(max_workers=maximum)
    try:
        yield pool
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
