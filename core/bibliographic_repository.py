"""Proyección MySQL del ledger existente; no admite textos/LLM ni escribe lectores.

SQLite acquisition es staging/outbox reanudable. MySQL indexa sus registros
admitidos. Los índices RAG y la memoria narrativa conservan sus políticas.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone as utc
import hashlib
import json
import os
import re
import time
import uuid
from django.conf import settings
from django.db import DatabaseError, transaction
from django.db.models import Sum
from django.utils import timezone
from .knowledge_models import KBRecord, KBName, KBRelation, KBVersion, KBProjection
from .literary_identity import normalize_identity


def digest(*values):
    return hashlib.sha256('\0'.join(str(value) for value in values).encode()).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def enabled():
    db = settings.DATABASES['default']
    local = (db['ENGINE'].endswith('mysql') and db.get('HOST') in {'localhost', '127.0.0.1'}
             and db.get('NAME') == 'litmate_db')
    configured = getattr(settings, 'LITMATE_STRUCTURED_KNOWLEDGE', None)
    if configured is not None:
        return configured is True
    flag = os.environ.get('LITMATE_STRUCTURED_KNOWLEDGE', 'auto').strip().lower()
    return local if flag == 'auto' else flag in {'1', 'true', 'yes'}


def repository_revision():
    if not enabled():
        return ''
    try:
        stamp = KBProjection.objects.order_by('-updated_at').values_list('updated_at', flat=True).first()
        return str(stamp or 'empty')
    except DatabaseError:
        return 'schema-unavailable'


def metadata_record(raw):
    """Lista cerrada de hechos catalográficos; ningún resumen hereda permiso."""
    from urllib.parse import urlsplit
    from .literary_acquisition import _isbn, _text, _strings
    from .literary_web import public_text_has_injection
    if not isinstance(raw, dict) or any(raw.get(key) for key in ('generated_by', 'llm_generated')):
        raise ValueError('untrusted_record')
    provider = raw.get('provider')
    book = raw.get('book') or raw
    if not isinstance(book, dict) or any(book.get(key) for key in ('generated_by', 'llm_generated')):
        raise ValueError('untrusted_record')
    url = str(book.get('url', ''))
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('untrusted_origin')
    patterns = {'openlibrary': ('openlibrary.org', r'/(?:works/OL\d+W|books/OL\d+M|authors/OL\d+A)'),
                'gutenberg': ('www.gutenberg.org', r'/ebooks/[1-9]\d{0,8}'),
                'wikidata': ('www.wikidata.org', r'/wiki/Q\d+'),
                'bne': ('datos.bne.es', r'/resource/[A-Za-z0-9_-]{1,80}')}
    if (provider not in patterns or parsed.hostname != patterns[provider][0]
            or parsed.port not in {None, 443} or not re.fullmatch(patterns[provider][1], parsed.path)):
        raise ValueError('untrusted_origin')
    external = parsed.path if provider == 'openlibrary' else parsed.path.rsplit('/', 1)[-1]
    kind = raw.get('kind')
    if provider == 'gutenberg':
        kind = 'edition'  # Un ebook del catálogo no es el identificador de obra abstracta.
    if provider == 'openlibrary':
        kind = 'author' if external.startswith('/authors/') else 'edition' if external.startswith('/books/') else 'work'
    if kind not in {'work', 'edition', 'author'}:
        raise ValueError('unsupported_kind')
    label = _text(raw.get('name') if kind == 'author' else book.get('title'), 220)
    if not label:
        raise ValueError('missing_identity')
    if public_text_has_injection(encoded(raw)):
        raise ValueError('untrusted_record')
    if not isinstance(raw.get('provenance', {}), dict):
        raise ValueError('invalid_provenance')
    policy = {'openlibrary': 'openlibrary-minimal-metadata-v1',
              'gutenberg': 'gutenberg-catalog-public-domain-v1', 'bne': 'bne-catalog-cc0-v1',
              'wikidata': 'wikidata-statements-v1'}[provider]
    declared = book.get('storage_policy') or book.get('policy')
    if provider != 'wikidata' and declared != policy:
        raise ValueError('missing_storage_policy')
    if provider == 'wikidata' and book.get('license') not in {'CC0', 'CC0-1.0'}:
        raise ValueError('missing_storage_policy')
    payload = {'provider': provider, 'external_id': external, 'kind': kind,
        'label': label, 'source_url': url, 'policy': policy,
        'license': 'Open Library bibliographic facts; rights vary' if provider == 'openlibrary' else 'CC0-1.0',
        'author': _text(book.get('author')) if kind != 'author' else '',
        'aliases': _strings(raw.get('aliases'), length=220),
        'languages': _strings(raw.get('languages') or [book.get('language')], length=10),
        'categories': _strings(raw.get('categories') or book.get('categories'), length=100),
        'isbns': _isbn(raw.get('isbns') or book.get('isbns') or []),
        'publisher': _text(raw.get('publisher')), 'year': _text(raw.get('year'), 80),
        'author_keys': [], 'work_keys': [],
        'provenance': {key: item for key, item in (raw.get('provenance') or {}).items()
            if key in {'dataset_url', 'dataset_sha256', 'record_number', 'license_scope', 'admission'}
            and isinstance(item, (str, int)) and not isinstance(item, bool)
            and len(str(item)) <= 1024}}
    for field, pattern in [('author_keys', r'/authors/OL\d+A'), ('work_keys', r'/works/OL\d+W')]:
        payload[field] = [key for key in (raw.get(field) or [])[:12]
                          if isinstance(key, str) and re.fullmatch(pattern, key)]
    # No biografías, reseñas, conversaciones, sinopsis, portadas ni textos completos.
    if len(encoded(payload).encode()) > 32000:
        raise ValueError('record_too_large')
    return payload


def put_metadata(raw, acquired_at):
    """Uso administrativo dentro de una transacción breve del proyector."""
    value = metadata_record(raw)
    pk = digest(value['provider'], value['external_id'])
    semantic = {key: item for key, item in value.items() if key != 'provenance'}
    checksum = digest(encoded(semantic))
    revision = int(raw.get('revision', 1))
    if isinstance(raw.get('revision'), bool) or not 0 < revision < 2**63:
        raise ValueError('invalid_revision')
    observed = datetime.fromtimestamp(float(acquired_at), tz=utc.utc)
    if observed > timezone.now() + timedelta(minutes=5):
        raise ValueError('invalid_observation_time')
    current = KBRecord.objects.filter(pk=pk).first()
    if current and (current.revision > revision or
                    current.revision == revision and observed < current.retrieved_at):
        return 'stale'
    version_id = digest(pk, encoded(value), revision)
    version_defaults = {'record': current, 'checksum': checksum, 'payload': value,
        'source_revision': revision, 'retrieved_at': observed,
        'stored_bytes': len(encoded(value).encode()) + 2048}
    if current and current.status == 'conflict' and revision <= current.revision:
        KBVersion.objects.get_or_create(pk=version_id, defaults=version_defaults)
        return 'conflicts'
    if current and current.checksum == checksum:
        KBVersion.objects.get_or_create(pk=version_id, defaults=version_defaults)
        if observed > current.retrieved_at:
            current.retrieved_at = observed
            current.save(update_fields=['retrieved_at'])
        return 'duplicates'
    status = 'source_metadata'
    if current and current.checksum != checksum and current.revision == revision:
        if value['provider'] == 'openlibrary' or observed <= current.retrieved_at:
            status = 'conflict'
    if current and current.verified_at and current.checksum != checksum:
        status = 'conflict'  # Una corrección humana no se sustituye silenciosamente.
    if current is None:
        current = KBRecord(id=pk)
    old_hash = current.checksum
    if status != 'conflict':
        for name in ('provider', 'external_id', 'kind', 'source_url', 'policy', 'license'):
            setattr(current, name, value[name])
        current.label, current.payload, current.checksum = value['label'], value, checksum
        current.revision, current.retrieved_at = revision, observed
        current.stored_bytes = (len(encoded(value).encode()) + 4096
            + sum(len(name.encode()) * 4 + 256 for name in {value['label'], *value['aliases']}))
    current.status = status
    current.save()
    KBVersion.objects.get_or_create(pk=version_id, defaults={'record': current,
        'checksum': checksum, 'payload': value, 'source_revision': revision, 'retrieved_at': observed,
        'stored_bytes': len(encoded(value).encode()) + 2048})
    if status == 'conflict':
        return 'conflicts'
    _sync_indexes(current, value)
    return 'inserted' if not old_hash else 'duplicates' if old_hash == checksum else 'updated'


def _sync_indexes(current, value):
    pk = current.pk
    KBName.objects.filter(record=current).update(current=False)
    for name in {value['label'], *value['aliases']}:
        normalized = normalize_identity(name)[:255]
        KBName.objects.update_or_create(pk=digest(pk, normalized), defaults={
            'record': current, 'normalized': normalized, 'current': True})
    KBRelation.objects.filter(record=current).update(current=False)
    for predicate, targets in [('author', value['author_keys']), ('edition_of', value['work_keys']), ('isbn', value['isbns'])]:
        for target in targets:
            target_id = digest('isbn' if predicate == 'isbn' else value['provider'], target)
            KBRelation.objects.update_or_create(pk=digest(pk, predicate, target_id), defaults={
                'record': current, 'predicate': predicate, 'target_id': target_id,
                'target_external_id': target, 'current': True})
    for edge in classification_edges(current):
        KBRelation.objects.update_or_create(pk=edge.id,defaults={'record':current,'predicate':edge.predicate,
            'target_id':edge.target_id,'target_external_id':edge.target_external_id,'current':True})


def classification_edges(record):
    from .literary_genres import classify_categories,TAXONOMY
    for code in classify_categories(record.payload.get('categories',[])):
        axis=TAXONOMY[code]['axis']
        target=digest('classification',axis,code)
        yield KBRelation(id=digest(record.id,'classification',target),record=record,
            predicate=axis,target_id=target,target_external_id=code,current=True)


def index_classifications(*, after='', maximum=250):
    """Índice aditivo derivado; no cambia metadatos originales ni crea tablas."""
    if not 1<=maximum<=500:raise ValueError('Lote de clasificación de 1..500.')
    records=list(KBRecord.objects.filter(id__gt=after,status='source_metadata',kind__in=['work','edition'])
                 .order_by('id')[:maximum])
    edges=[edge for record in records for edge in classification_edges(record)]
    with transaction.atomic():
        KBRelation.objects.bulk_create(edges,ignore_conflicts=True,batch_size=250)
    return {'scanned':len(records),'edges_expected':len(edges),'cursor':records[-1].id if records else after,
            'complete':len(records)<maximum}


def genre_sources(codes,maximum=160,*,exclude_records=()):
    """Una consulta por el índice target_id; candidatos acotados, sin N+1."""
    from .literary_genres import TAXONOMY,matches_categories
    if not enabled() or not codes or any(code not in TAXONOMY for code in codes):return []
    targets=[digest('classification',TAXONOMY[code]['axis'],code) for code in codes]
    if len(exclude_records)>200:raise ValueError('Hasta 200 exclusiones bibliográficas por consulta.')
    edges=KBRelation.objects.filter(target_id__in=targets,current=True,record__status='source_metadata',
        ).exclude(record_id__in=list(exclude_records)).filter(
        predicate__in=['genre','format','audience']).select_related('record').order_by('record_id')[:min(500,maximum*3)]
    edges=list(edges)
    parent_ids={digest(edge.record.provider,key) for edge in edges for key in edge.record.payload.get('work_keys',[])}
    blocked=set(KBRecord.objects.filter(id__in=parent_ids,status='conflict').values_list('id',flat=True)) if parent_ids else set()
    result=[];seen=set()
    for edge in edges:
        record=edge.record
        if record.id in seen:continue
        seen.add(record.id)
        data=record.payload
        if any(digest(record.provider,key) in blocked for key in data.get('work_keys',[])):continue
        if not data.get('author') or normalize_identity(data['author']) in {'unknown','various','anonymous'}:continue
        source={'kind':'book','title':record.label,'author':data['author'],'book_id':'sqlkb:'+record.id,
            'source':{'gutenberg':'Project Gutenberg','openlibrary':'Open Library','wikidata':'Wikidata','bne':'BNE'}[record.provider],
            'url':record.source_url,'categories':data.get('categories',[]),'isbns':data.get('isbns',[]),
            'language':data.get('languages',[''])[0] if data.get('languages') else '',
            'policy':record.policy,'storage_policy':record.policy,'license':record.license,
            'description':'','synopsis':'','year':data.get('year',''),'retrieved_at':record.retrieved_at.isoformat(),
            'memory_verified':True}
        if matches_categories(source,codes):result.append(source)
        if len(result)>=maximum:break
    return result


def project_ledger(state_database, *, max_records=100, batch_size=25, max_seconds=30,
                   max_storage_mb=64, replay=False, after_record=None):
    """Consume outbox admitido en streaming, con checkpoint transaccional MySQL.

    INSERT OR REPLACE del ledger asigna un rowid nuevo a actualizaciones; el
    cursor no depende de títulos, consultas del lector ni relojes de sistema.
    """
    from .literary_acquisition import _connect, _json, _hash
    if not (1 <= max_records <= 100000 and 1 <= batch_size <= 100 and 1 <= max_seconds <= 3600
            and 1 <= max_storage_mb <= 10240):
        raise ValueError('invalid_limits')
    start = time.monotonic()
    readable = _connect(state_database, write=False)
    if readable is None:
        raise ValueError('missing_ledger')
    readable.close()
    # UUID de este outbox, no un nuevo almacén. No modifica registros anteriores.
    with closing(_connect(state_database, write=True)) as source, source:
        source.execute("INSERT OR IGNORE INTO acquisition_meta VALUES('mysql_projection_uuid',?)", (uuid.uuid4().hex,))
        source_id = source.execute("SELECT value FROM acquisition_meta WHERE key='mysql_projection_uuid'").fetchone()[0]
    job_id, token = digest(source_id), uuid.uuid4().hex
    global_id = digest('single-bibliographic-projector')
    KBProjection.objects.get_or_create(pk=global_id)
    job, _ = KBProjection.objects.get_or_create(pk=job_id)
    with transaction.atomic():
        guard = KBProjection.objects.select_for_update().get(pk=global_id)
        if guard.lease_until and guard.lease_until > timezone.now():
            raise ValueError('projection_busy')
        job = KBProjection.objects.select_for_update().get(pk=job_id)
        if job.lease_until and job.lease_until > timezone.now():
            raise ValueError('projection_busy')
        job.lease_token, job.lease_until = token, timezone.now() + timedelta(seconds=max_seconds + 30)
        job.save()
        guard.lease_token, guard.lease_until = token, job.lease_until
        guard.save()
    cursor = 0 if replay else job.last_rowid
    report = {key: 0 for key in ('scanned', 'inserted', 'updated', 'duplicates', 'stale', 'conflicts', 'rejected')}
    report.update(cursor_before=cursor, cursor_after=cursor, complete=False, issues=[])
    try:
        with closing(_connect(state_database)) as source:
            maximum = source.execute('SELECT COALESCE(MAX(rowid),0) FROM acquisition_records').fetchone()[0]
            if not replay and maximum < cursor:
                raise ValueError('ledger_rewound_restore_requires_new_checkpoint')
            while report['scanned'] < max_records and time.monotonic() - start < max_seconds:
                rows = source.execute('SELECT r.rowid AS cursor,r.record_id,r.content_hash,r.acquired_at,'
                    'substr(CAST(r.record AS BLOB),1,65537) AS record,o.state AS admission,o.content_hash AS admitted_hash '
                    'FROM acquisition_records r LEFT JOIN acquisition_outbox o USING(record_id) '
                    'WHERE r.rowid>? ORDER BY r.rowid LIMIT ?',
                    (cursor, min(batch_size, max_records - report['scanned']))).fetchall()
                if not rows:
                    report['complete'] = True
                    break
                if any(row['admission'] == 'staged' or row['admission'] is None for row in rows):
                    report['blocked_on_unverified_source'] = True
                    break
                logical = sum((model.objects.aggregate(size=Sum('stored_bytes'))['size'] or 0)
                              for model in (KBRecord, KBVersion))
                reserve = sum(len(row['record']) * 4 + 16384 for row in rows)
                if logical + reserve > max_storage_mb * 1024 * 1024:
                    report['storage_limit'] = True
                    break
                increments = {key: 0 for key in ('scanned', 'inserted', 'updated', 'duplicates', 'stale', 'conflicts', 'rejected')}
                issues = []
                with transaction.atomic():
                    guard = KBProjection.objects.select_for_update().get(pk=global_id)
                    if guard.lease_token != token:
                        raise ValueError('projection_lease_lost')
                    locked = KBProjection.objects.select_for_update().get(pk=job_id)
                    if locked.lease_token != token:
                        raise ValueError('projection_lease_lost')
                    processed = []
                    for row in rows:
                        if time.monotonic() - start >= max_seconds:
                            report['budget_exhausted'] = True
                            break
                        increments['scanned'] += 1
                        try:
                            if len(row['record']) > 65536:
                                raise ValueError('record_too_large')
                            raw = json.loads(row['record'])
                            if (_hash(_json(raw)) != row['content_hash'] or row['admitted_hash'] != row['content_hash']):
                                raise ValueError('checksum_mismatch')
                            result = put_metadata(raw, row['acquired_at'])
                            increments[result] += 1
                        except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
                            increments['rejected'] += 1
                            issues.append({'record_id': row['record_id'], 'code': 'invalid_metadata_or_checksum'})
                        if after_record:
                            after_record(row['record_id'])
                        processed.append(row['cursor'])
                    cursor = processed[-1] if processed else cursor
                    locked.last_rowid = max(locked.last_rowid, cursor)
                    locked.counters = {key: locked.counters.get(key, 0) + value for key, value in increments.items()}
                    locked.save()
                for key, value in increments.items():
                    report[key] += value
                report['issues'] = (report['issues'] + issues)[-20:]
                report['cursor_after'] = cursor
    finally:
        KBProjection.objects.filter(pk=job_id, lease_token=token).update(lease_token='', lease_until=None)
        KBProjection.objects.filter(pk=global_id, lease_token=token).update(lease_token='', lease_until=None)
    report.update(seconds=round(time.monotonic() - start, 4),
                  logical_bytes=sum((model.objects.aggregate(size=Sum('stored_bytes'))['size'] or 0)
                                    for model in (KBRecord, KBVersion)))
    return report


def review_version(record_id, version_id, *, evidence_url, operator_confirmed=False):
    """Revisión humana local explícita; nunca feedback anónimo ni veredicto LLM.

    El operador declara haber contrastado el dato con la fuente primaria.
    No se consulta Internet ni se certifica automáticamente esa declaración.
    """
    if operator_confirmed is not True:
        raise ValueError('operator_confirmation_required')
    with transaction.atomic():
        guard, _ = KBProjection.objects.get_or_create(pk=digest('single-bibliographic-projector'))
        guard = KBProjection.objects.select_for_update().get(pk=guard.pk)
        if guard.lease_until and guard.lease_until > timezone.now():
            raise ValueError('projection_busy')
        record = KBRecord.objects.select_for_update().get(pk=record_id)
        version = KBVersion.objects.get(pk=version_id, record=record)
        value = version.payload
        if evidence_url != value.get('source_url') or not evidence_url:
            raise ValueError('primary_source_required')
        if digest(encoded({key: item for key, item in value.items() if key != 'provenance'})) != version.checksum:
            raise ValueError('version_integrity_failed')
        # Una versión ya admitida contiene sólo el esquema bibliográfico permitido.
        record.status, record.checksum = 'source_metadata', version.checksum
        record.payload, record.label = value, value['label']
        record.revision, record.verified_at = version.source_revision, timezone.now()
        record.save()
        _sync_indexes(record, value)
        audit = {'selected_version':version.id, 'evidence_url':evidence_url,
                 'review_type':'local_operator_confirmed_primary_metadata',
                 'reviewed_at':record.verified_at.isoformat()}
        KBVersion.objects.create(id=digest(record.id, encoded(audit)), record=record,
            checksum=record.checksum, payload={'operator_review':audit},
            source_revision=record.revision, retrieved_at=record.verified_at,
            stored_bytes=len(encoded(audit).encode())+2048)
        guard.save()  # Invalida cachés derivadas; no modifica pesos ni hechos narrativos.
        return audit


def lookup_sources(query, *, maximum=8):
    """B-tree de nombres/alias e identificadores. Nunca escanea todos los JSON."""
    if not enabled():
        return []
    maximum = max(1, min(int(maximum), 24))
    from .literary_language import request_text
    literal = normalize_identity(str(query).strip('¿?¡!., "«»'))[:255]
    value = request_text(query).strip('¿?¡!., "«»')
    value = re.sub(r'^(?:quien escribio|de que trata|dime (?:la trama|los personajes) de)\s+', '', value)
    wanted = normalize_identity(value)[:255]
    if not literal and not wanted:
        return []
    try:
        ids = []
        for exact in dict.fromkeys([literal, wanted]):
            names = KBName.objects.filter(normalized=exact, current=True,
                record__status='source_metadata', record__kind__in=['work', 'edition'])
            ids = list(names.values_list('record_id', flat=True)[:maximum + 1])
            if ids:
                break
        if not ids and len(wanted) >= 3:
            ids = list(KBName.objects.filter(normalized__startswith=wanted, current=True,
                record__status='source_metadata', record__kind__in=['work', 'edition'])
                .values_list('record_id', flat=True)[:maximum + 1])
        isbn = re.sub(r'[\s-]', '', str(query))
        if re.fullmatch(r'(?:\d{13}|\d{9}[\dX])', isbn):
            ids += list(KBRelation.objects.filter(predicate='isbn', target_id=digest('isbn', isbn),
                current=True, record__status='source_metadata').values_list('record_id', flat=True)[:maximum + 1])
        if len(set(ids)) > maximum:
            return []  # No ocultar homónimos por truncar antes de desambiguar.
        records = list(KBRecord.objects.filter(pk__in=ids).order_by('id')[:maximum])
        parents = list(KBRelation.objects.filter(record_id__in=ids, predicate='edition_of', current=True)
                       .values_list('record_id', 'target_id'))
        conflicted = set(KBRecord.objects.filter(pk__in=[target for _, target in parents],
                         status='conflict').values_list('id', flat=True))
        blocked_editions = {edition for edition, target in parents if target in conflicted}
        author_ids = list(KBRelation.objects.filter(record_id__in=ids, predicate='author', current=True)
                          .values_list('target_id', flat=True)[:maximum * 12])
        authors = {item.id: item.label for item in KBRecord.objects.filter(pk__in=author_ids,
                   kind='author', status='source_metadata')}
        links = {}
        for edge in KBRelation.objects.filter(record_id__in=ids, predicate='author', current=True):
            if edge.target_id in authors:
                links.setdefault(edge.record_id, []).append(authors[edge.target_id])
        result = []
        for record in records:
            if record.id in blocked_editions:
                continue
            data = record.payload
            author = data.get('author') or ', '.join(links.get(record.id, []))
            if not author:
                continue
            result.append({'title': record.label, 'author': author, 'kind': 'book',
                'book_id': 'sqlkb:' + record.id, 'source': {'openlibrary': 'Open Library',
                    'gutenberg': 'Project Gutenberg', 'wikidata': 'Wikidata', 'bne': 'BNE'}[record.provider],
                'url': record.source_url, 'description': '', 'synopsis': '',
                'categories': data.get('categories', []), 'isbns': data.get('isbns', []),
                'language': data['languages'][0] if len(data.get('languages', [])) == 1 else '',
                'edition_id': record.external_id if record.kind == 'edition' else '',
                'policy': record.policy, 'storage_policy': record.policy, 'license': record.license,
                'read_mode': 'metadatos de fuente; sin trama ni texto completo',
                'memory_verified': True})
        return result
    except DatabaseError:
        return []  # Una instalación sin las tablas nuevas mantiene su recuperación anterior.
