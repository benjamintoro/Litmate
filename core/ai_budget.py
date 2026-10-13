"""Presupuesto compartido entre modelo, búsqueda y embeddings de una consulta."""
import time
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from concurrent.futures import ThreadPoolExecutor

_deadline = ContextVar('litmate_ai_deadline', default=None)


class BudgetExpired(TimeoutError):
    pass


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
