"""Orquestación incremental sobre la cola, fuentes y señales ya existentes.

No entrena modelos, no recibe una corrección como verdad y no crea otro almacén
de hechos. Sólo agenda identidades públicas previamente admitidas.
"""
import json
import re
import time
import hashlib
import shutil
import sqlite3
import uuid
from pathlib import Path
from contextlib import closing
from .literary_identity import work_identity, title_matches, same_work, normalize_identity


GAP_REASONS = frozenset({'insufficient_evidence', 'identity_mismatch', 'retrieval_failed',
    'source_conflict', 'audit_rejected', 'reader_correction_pending'})
KINDS = {'synopsis': 'summary', 'plot': 'summary', 'book_identity': 'metadata',
         'bibliography': 'metadata', 'character_detail': 'characters', 'comparison': 'summary'}


def queue_gap(work_id, requirement, reason, *, database=None, priority=80):
    from .literary_learning import REQUIREMENTS, _bibliographic_query
    from .literary_memory import get_work, enqueue_refresh, _connection, _json
    requirement = KINDS.get(requirement, requirement)
    if reason not in GAP_REASONS or requirement not in REQUIREMENTS:
        raise ValueError('Sólo se registran categorías y códigos técnicos; nunca consultas privadas.')
    work = get_work(work_id, database=database)
    if not work:
        return None
    provider = 'openlibrary' if requirement in {'metadata', 'author'} else 'wikipedia'
    _bibliographic_query(work, provider)
    identifier = enqueue_refresh(work_id, requirement, provider, priority=priority, database=database)
    with _connection(database, write=True) as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT payload FROM memory_jobs WHERE job_id=?', (identifier,)).fetchone()
        try:
            payload = json.loads(row[0])
        except (TypeError, ValueError):
            return identifier  # Preserve corruption for claim_job's quarantine.
        payload.update(last_gap_reason=reason, gap_count=min(1_000_000, int(payload.get('gap_count', 0))+1))
        db.execute('UPDATE memory_jobs SET payload=?,not_before=MAX(not_before,?) WHERE job_id=?',
                   (_json(payload), float(payload.get('last_completed_at', 0)) + 86400, identifier))
    return identifier


def observe_answer(message, result, history=(), *, database=None):
    """Only aggregate outcomes of known works; the message is never persisted."""
    from .literary_ai import has_excerpt, obvious_rejection
    from .ai_narrative_answers import request_for
    from .ai_character_answers import request_for as character_request
    from .literary_memory import retrieve_evidence, get_work, record_use
    if has_excerpt(message) or obvious_rejection(message):
        return {'queued': 0}
    request = character_request(message, history) or request_for(message, history)
    if not request:
        # Reuse the existing bibliographic focus; never extract an identity
        # from personal prose or create a public book from a reader's assertion.
        from .literary_identity import resolve_followup_context
        context = resolve_followup_context(message, history)
        requirement = next((kind for pattern, kind in (
            (r'\badaptaciones\b', 'adaptations'), (r'\bcontexto hist[oó]rico\b', 'historical_context'),
            (r'\bg[eé]neros?\b', 'genres'), (r'\bacontecimientos?\b', 'events'))
            if re.search(pattern, message, re.I)), None)
        focused = context.get('books', []) if context else []
        if requirement and len(focused) == 1 and not context.get('ambiguous'):
            request = {'title': focused[0]['title'], 'targets': focused, 'task': requirement, 'ambiguous': False}
    correction = bool(re.search(r'\b(?:te equivocaste|eso es incorrecto|tu respuesta es incorrecta)\b', message, re.I))
    if correction:
        request = request_for('Dime la trama de ese libro', history)
    if not request or not request.get('title') or request.get('ambiguous'):
        return {'queued': 0}
    books, unused = retrieve_evidence(request['title'], database=database, limit=8)
    matches = [book for book in books if title_matches(request['title'], book)]
    unique = []
    for work in matches:
        if not any(same_work(work, other) for other in unique):
            unique.append(work)
    if len(unique) != 1:
        return {'queued': 0, 'reason': 'identity_not_resolved'}
    work = get_work(work_identity(unique[0])['work_id'], database=database)
    if not work:
        return {'queued': 0}
    requirement = {'summary': 'summary', 'characters': 'characters', 'protagonist': 'characters',
        'character': 'characters', 'relationship': 'relationships', 'object_relation': 'relationships',
        'adaptations':'adaptations', 'historical_context':'historical_context', 'genres':'genres', 'events':'events'}.get(request['task'], 'metadata')
    if request.get('focus') == 'main' or request['task'] == 'protagonist':
        requirement = 'main_characters'
    if request['task']=='summary' and result.diagnostics.get('narrative_coverage')=='premise':
        requirement = 'plot_development'
    failure = (result.status == 'unavailable' or result.diagnostics.get('partial_evidence') or correction)
    record_use(work['work_id'], requirement, 'failed' if failure else 'hit', database=database)
    if not failure:
        return {'queued': 0}
    reason = ('reader_correction_pending' if correction else 'audit_rejected' if
        result.diagnostics.get('narrative_failure') == 'audit_not_approved' else 'insufficient_evidence')
    identifier = queue_gap(work['work_id'], requirement, reason, database=database)
    return {'queued': int(bool(identifier)), 'requirement': requirement}


def gap_priority(work,books,sources,requirement):
    """Prioritize public evidence gaps, never facts by popularity."""
    from .literary_memory import _literal_facts
    from .literary_enrichment import has_development
    narrative=[s for s in sources if same_work(s,work) and not s.get('conflicts_with')]
    names={normalize_identity(f['name']) for s in narrative for f in
           _literal_facts(s.get('character_facts',[]),s.get('description',''),'character_facts')
           if not f.get('membership_only')}
    if requirement in {'characters','character_roster','main_characters'}:
        return 85 if not names else 75 if len(names)<3 else 55
    if requirement in {'summary','plot_development'}:
        return 70 if not any(has_development(s) for s in narrative) else 35
    if requirement=='relationships':
        return 60
    return 40


def schedule_incremental(*, database=None, maximum=5, requirements=('summary', 'characters')):
    """Demand plus a durable rotating cursor; less popular works are included."""
    from .literary_learning import _covers_requirement, REQUIREMENTS
    from .literary_memory import _connection, _json, retrieve_evidence
    maximum = max(1, min(int(maximum), 25))
    if any(requirement not in REQUIREMENTS for requirement in requirements):
        raise ValueError('Tipo de evidencia no admitido')
    with _connection(database, write=True) as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT value FROM memory_meta WHERE key='continuous_cursor'").fetchone()
        cursor = row[0] if row else ''
        demanded = list(db.execute('SELECT w.work_id,w.record FROM memory_works w JOIN memory_usage u '
            'ON u.work_id=w.work_id GROUP BY w.work_id ORDER BY SUM(u.failures+u.hits) DESC,w.work_id LIMIT 1'))
        rotating = maximum-1 if maximum > 1 and demanded else maximum
        rows = list(db.execute('SELECT work_id,record FROM memory_works WHERE work_id>? ORDER BY work_id LIMIT ?',
                               (cursor, rotating)))
        if len(rows) < rotating:
            rows.extend(db.execute('SELECT work_id,record FROM memory_works WHERE work_id<=? ORDER BY work_id LIMIT ?',
                                   (cursor, rotating-len(rows))))
        if rows:
            db.execute("INSERT OR REPLACE INTO memory_meta VALUES ('continuous_cursor',?)", (rows[-1]['work_id'],))
        # The cursor only advances past INCLUDED rotating works. The demand
        # slot never skips an unseen work (including after a process restart).
        selected = {row['work_id']: json.loads(row['record']) for row in rows}
        if maximum > 1 and demanded:
            selected[demanded[0]['work_id']] = json.loads(demanded[0]['record'])
    jobs = []
    for work in selected.values():
        for requirement in requirements:
            books, sources = retrieve_evidence(work['title'], books=[work], requirement=requirement, database=database)
            if not _covers_requirement(work, books, sources, requirement):
                priority = min(95,gap_priority(work,books,sources,requirement)+
                               (10 if demanded and work['work_id']==demanded[0]['work_id'] else 0))
                jobs.append(queue_gap(work['work_id'], requirement, 'insufficient_evidence', database=database, priority=priority))
    return {'work_ids': list(selected), 'jobs': [identifier for identifier in jobs if identifier]}


def project_references(work_ids, *, database=None):
    """Relate accepted SQLite snapshots to exact existing SQL catalogue anchors.

    No title-similarity joins and no duplicated passages. MySQL keeps durable
    references; sources, roles and provenance retain their existing authority.
    """
    from .literary_memory import get_work, retrieve_evidence
    from .knowledge_models import KBRecord, KBRelation
    from .bibliographic_repository import digest
    count = 0
    for work_id in list(dict.fromkeys(work_ids))[:25]:
        work = get_work(work_id, database=database)
        if not work or not work.get('url'):
            continue
        books, sources = retrieve_evidence(work['title'], books=[work], database=database, limit=20)
        # A newer bibliographic source may become the preferred URL. Retain
        # exact catalogue anchors already admitted for this identity instead
        # of losing the SQL link, or joining other records by title similarity.
        urls = {work['url']}
        urls.update(source['url'] for source in [*books,*sources]
                    if source.get('kind') == 'book' and source.get('memory_verified')
                    and source.get('url') and same_work(source,work))
        # Gutenberg's imported catalogue records represent editions. An exact
        # admitted URL can link evidence to that edition without promoting it
        # to a work or merging either identity. Ambiguous anchors still stop.
        records = list(KBRecord.objects.filter(source_url__in=urls, status='source_metadata',
                                               kind__in=('work','edition'))[:2])
        if len(records) != 1:
            continue
        for source in sources:
            if not source.get('memory_source_id'):
                continue
            relation, created = KBRelation.objects.get_or_create(
                id=digest(records[0].id, 'memory_evidence', source['memory_source_id']), defaults={
                'record': records[0], 'predicate': 'memory_evidence',
                'target_id': digest('memory_source', source['memory_source_id']),
                'target_external_id': source['memory_source_id'], 'current': True})
            count += int(created)
    return count


def run_continuous_batch(*, database=None, maximum=5, work_ids=(), max_jobs=2,
                         max_seconds=30, job_seconds=8, pause_seconds=1,
                         stop_file=None, min_free_gb=10, max_rss_mb=512,
                         reindex=True, project_mysql=False, requirements=('summary','characters')):
    """One bounded run, no daemon. Checkpoints and leases survive a restart.

    Resource limits are admission checks between jobs, not an OS memory cap.
    A socket retains its existing deadline; cancellation does not kill threads.
    MySQL projection is additive and optional; SQLite remains the fact authority.
    """
    from . import literary_memory as memory
    from .literary_learning import run_refresh_batch, lower_worker_priority, _covers_requirement, REQUIREMENTS
    from .ai_concurrency import acquire, release
    from evaluar_chat_http import memory_snapshot
    if not (1 <= maximum <= 25 and 1 <= max_jobs <= 20 and 1 <= max_seconds <= 120
            and 1 <= job_seconds <= 12 and 1 <= pause_seconds <= 30
            and 1 <= min_free_gb <= 1000 and 64 <= max_rss_mb <= 4096):
        raise ValueError('Presupuestos de enriquecimiento inválidos.')
    database = memory._path(database)
    if not database.is_file():
        raise ValueError('El modo continuo requiere memoria existente; no crea un catálogo.')
    if not isinstance(work_ids, (tuple, list)) or len(work_ids) > 25:
        raise ValueError('Selecciona hasta 25 obras existentes.')
    if not requirements or len(requirements) > 6 or any(item not in REQUIREMENTS for item in requirements):
        raise ValueError('Selecciona hasta seis requisitos públicos válidos.')
    selected = [memory.get_work(identifier, database=database) for identifier in dict.fromkeys(work_ids)]
    if any(not work for work in selected):
        raise ValueError('Identidad inexistente; no se ejecutó el lote.')
    stop_file = Path(stop_file) if stop_file else database.parent / 'enrichment.stop'
    start, cpu = time.monotonic(), time.process_time()
    initial_bytes = database.stat().st_size
    initial_revision = memory.revision(database)
    report = {'mode': 'continuous_once', 'scheduled': 0, 'llm_calls': 0,
              'new_global_corrections': 0, 'mysql_references_added': 0}
    reason = ''

    def stop():
        nonlocal reason
        if stop_file.exists():
            reason = 'stop_file'
        elif time.monotonic()-start >= max_seconds:
            reason = 'time_budget'
        elif shutil.disk_usage(database.parent).free < min_free_gb * 2**30:
            reason = 'free_disk'
        elif memory_snapshot().get('rss_mb', 0) > max_rss_mb:
            reason = 'process_rss'
        return bool(reason)

    owner = uuid.uuid4().hex
    key = 'litmate-enrichment:' + hashlib.sha256(str(database).encode()).hexdigest()
    if stop():
        return {**report, 'stopped': reason}
    if not acquire(key, owner, int(max_seconds)+60):
        return {**report, 'stopped': 'another_worker'}
    try:
        lower_worker_priority()
        if selected:
            identifiers = [work['work_id'] for work in selected]
            for work in selected:
                for requirement in dict.fromkeys(requirements):
                    if stop():
                        break
                    books, sources = memory.retrieve_evidence(work['title'], books=[work],
                        requirement=requirement, database=database)
                    if not _covers_requirement(work, books, sources, requirement):
                        report['scheduled'] += int(bool(queue_gap(work['work_id'], requirement,
                            'insufficient_evidence', database=database,priority=gap_priority(work,books,sources,requirement))))
        else:
            plan = schedule_incremental(database=database, maximum=maximum, requirements=requirements)
            identifiers = plan['work_ids']
            report['scheduled'] = len(plan['jobs'])
        report['work_ids'] = identifiers
        remaining = max_seconds-(time.monotonic()-start)
        if remaining >= 1 and not stop():
            report['batch'] = run_refresh_batch(database=database, max_jobs=max_jobs,
                max_seconds=remaining, job_seconds=job_seconds, pause_seconds=pause_seconds,
                narrative_pages=1, work_ids=identifiers if selected else (),
                reuse_fresh=True, stop=stop, max_attempts=5,requirements=requirements if selected else ())
        # FTS/entities update in the same transaction as accepted sources.
        # The separate optional BM25 index is atomic and never required by chat.
        if reindex and not stop():
            from .literary_memory_rag import index_path, build_memory_index, _owned_index
            destination = index_path(database.with_name(database.stem + '_rag.sqlite3'), database=database)
            current_revision = memory.revision(database)
            indexed_revision = ''
            indexed_policy = ''
            if destination.is_file():
                _owned_index(destination)
                with closing(sqlite3.connect(destination.resolve().as_uri()+'?mode=ro', uri=True)) as db:
                    row = db.execute("SELECT value FROM rag_metadata WHERE key='memory_revision'").fetchone()
                    indexed_revision = row[0] if row else ''
                    row = db.execute("SELECT value FROM rag_metadata WHERE key='verification_policy'").fetchone()
                    indexed_policy = row[0] if row else ''
            if indexed_revision != current_revision or indexed_policy != memory.READ_POLICY:
                index_key = 'litmate-memory-index:' + hashlib.sha256(str(destination).encode()).hexdigest()
                remaining = max_seconds-(time.monotonic()-start)
                if remaining >= 1 and acquire(index_key, owner, int(remaining)+60):
                    try:
                        report['index'] = build_memory_index(database=database, index=destination, maximum=500,
                            max_seconds=min(30, remaining))
                    finally:
                        release(index_key, owner)
            else:
                report['index'] = {'reason': 'already_current', 'index_updated': False}
        if project_mysql and not stop():
            from django.db import connection, transaction, DatabaseError
            from .knowledge_models import KBProjection
            from .bibliographic_repository import digest
            if connection.vendor != 'mysql' or connection.settings_dict.get('HOST') not in {'127.0.0.1', 'localhost', '::1'}:
                raise ValueError('La proyección continua requiere MySQL local explícito; no se escribe TiDB remoto.')
            try:
                with transaction.atomic():
                    processed = [job['work_id'] for job in report.get('batch', {}).get('jobs', [])
                                 if job.get('lease_current') and job.get('work_id')]
                    # A high-priority chat gap may be outside today's rotating
                    # scan. Project what was actually processed first.
                    projection_ids = list(dict.fromkeys([*processed, *identifiers]))[:25]
                    report['projected_work_ids'] = projection_ids
                    report['mysql_references_added'] = project_references(projection_ids, database=database)
                    KBProjection.objects.update_or_create(id=digest('continuous-enrichment-v1'), defaults={
                        'last_rowid': int(memory.revision(database)),
                        'counters': {'works_selected': len(identifiers), 'completed': report.get('batch', {}).get('completed', 0),
                                     'sources_stored': report.get('batch', {}).get('stored', 0)}})
            except DatabaseError:
                # The admitted SQLite snapshots/queue remain resumable. No false SQL success.
                report['mysql_projection_error'] = 'database_unavailable'
        report.update(stopped=reason or None, seconds=round(time.monotonic()-start, 3),
            cpu_seconds=round(time.process_time()-cpu, 3), process=memory_snapshot(),
            storage_delta_bytes=database.stat().st_size-initial_bytes,
            revision_before=initial_revision, revision_after=memory.revision(database))
        return report
    finally:
        release(key, owner)
