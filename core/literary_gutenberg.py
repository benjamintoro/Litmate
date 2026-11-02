"""Catálogo oficial Gutenberg, separado del permiso de uso de las novelas.

El CSV/RDF contiene metadatos de dominio público. Ningún registro concede
permiso para descargar el texto: la biblioteca exige otra revisión por edición.
Reutiliza el ledger, outbox y memoria bibliográfica existentes.
"""
import csv
import gzip
import hashlib
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from xml.etree import ElementTree

CATALOG_URL = 'https://gutenberg.pglaf.org/cache/epub/feeds/pg_catalog.csv.gz'
CATALOG_POLICY = 'gutenberg-catalog-public-domain-v1'
CATALOG_DOCUMENTATION = 'https://www.gutenberg.org/policy/robot_access.html'
MAX_DOWNLOAD = 12_000_000


def download_catalog(destination, *, timeout=45):
    """Una descarga oficial limitada; no recorre /ebooks ni sigue redirects."""
    from .literary_web import _secure_fetch, _robots_permission
    from .ai_budget import budget_timeout
    destination = Path(destination)
    if destination.is_symlink() or destination.exists():
        raise ValueError('El catálogo de destino debe ser nuevo; reutiliza el existente.')
    deadline = time.monotonic() + budget_timeout(timeout)
    host = 'gutenberg.pglaf.org'
    _robots_permission(CATALOG_URL, host, (host,), deadline)
    result = _secure_fetch(CATALOG_URL, allowed_domains=(host,), deadline=deadline,
                           maximum=MAX_DOWNLOAD, accept='application/gzip,application/octet-stream')
    body = result['body']
    if not body.startswith(b'\x1f\x8b'):
        raise ValueError('El catálogo oficial no devolvió gzip.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as stream:
        stream.write(body)
    return {'path': str(destination), 'bytes': len(body), 'url': CATALOG_URL,
            'sha256': hashlib.sha256(body).hexdigest()}


def _author(label):
    # No atribuir una traducción, prólogo o recopilación al novelista por quitar
    # silenciosamente la función editorial publicada en el catálogo.
    if not label or '[' in label or ';' in label:
        return ''
    value = re.sub(r',\s*\d{1,4}\??\s*-\s*\d{0,4}\??\s*$', '', label).strip()
    parts = [part.strip() for part in value.split(',')]
    value = ' '.join([*parts[1:], parts[0]]) if len(parts) == 2 else value
    return value if 2 <= len(value) <= 220 else ''


def catalog_record(row):
    identifier = str(row.get('Text#', ''))
    title, author = str(row.get('Title', '')).strip(), _author(str(row.get('Authors', '')))
    if (not re.fullmatch(r'[1-9]\d{0,7}', identifier) or not 2 <= len(title) <= 220 or not author
            or row.get('Type', 'Text') != 'Text'):
        return None
    languages = [item.strip() for item in str(row.get('Language', '')).split(';') if item.strip()]
    if not languages or any(not re.fullmatch(r'[a-z]{2,3}', value) for value in languages):
        return None
    categories = [item.strip()[:100] for item in str(row.get('Subjects', '')).split(';') if item.strip()][:12]
    source = {'kind': 'book', 'source': 'Project Gutenberg', 'title': title, 'author': author,
              'url': 'https://www.gutenberg.org/ebooks/' + identifier, 'description': '',
              'categories': categories, 'language': languages[0] if len(languages) == 1 else '',
              'license': 'CC0-1.0', 'storage_policy': CATALOG_POLICY,
              'edition_id': 'gutenberg:' + identifier,
              'read_mode': 'metadatos del catálogo; derechos del texto no evaluados'}
    return {'provider': 'gutenberg', 'kind': 'work', 'external_id': identifier, 'revision': 1,
            'title': title, 'author': author, 'languages': languages, 'book': source,
            'catalog_author_label': row.get('Authors', ''), 'sources': [source]}


def iter_rdf_catalog(path, *, maximum_bytes=12_000_000):
    """RDF oficial por ebook o subconjunto local; XML sin DTD ni entidades.

    No presupone permisos de textos ni conserva resúmenes del catálogo. Para
    volcados grandes se debe proporcionar un subconjunto, no cargar el XML en RAM.
    """
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > maximum_bytes:
        raise ValueError('RDF fuera del límite del lote.')
    class Guard:
        def __init__(self, stream):
            self.stream, self.tail, self.size = stream, b'', 0
        def read(self, size=16384):
            block = self.stream.read(min(size if size > 0 else 16384, 16384))
            self.size += len(block)
            if self.size > maximum_bytes:
                raise ValueError('RDF expandido demasiado grande.')
            test = (self.tail + block).upper()
            if b'\0' in block or b'<!DOCTYPE' in test or b'<!ENTITY' in test:
                raise ValueError('RDF con entidades externas no permitido.')
            self.tail = test[-20:]
            return block
    ns = {'pg': 'http://www.gutenberg.org/2009/pgterms/',
          'dc': 'http://purl.org/dc/terms/', 'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'}
    with path.open('rb') as stream:
        for _, element in ElementTree.iterparse(Guard(stream), events=('end',)):
            if element.tag != '{' + ns['pg'] + '}ebook':
                continue
            key = element.get('{' + ns['rdf'] + '}about', '')
            names = [node.text for node in element.findall('dc:creator/pg:agent/pg:name', ns) if node.text]
            languages = [node.text for node in element.findall('dc:language/rdf:Description/rdf:value', ns) if node.text]
            subjects = [node.text for node in element.findall('dc:subject/rdf:Description/rdf:value', ns) if node.text]
            types = [node.text for node in element.findall('dc:type/rdf:Description/rdf:value', ns) if node.text]
            row = {'Text#': key.rsplit('/', 1)[-1], 'Title': element.findtext('dc:title', '', ns),
                   'Authors': '; '.join(names), 'Language': '; '.join(languages),
                   'Subjects': '; '.join(subjects), 'Type': types[0] if types else 'Text'}
            yield catalog_record(row)
            element.clear()


def _bounded_lines(stream, deadline):
    size = 0
    while True:
        if time.monotonic() >= deadline:
            raise TimeoutError('Presupuesto del catálogo agotado.')
        line = stream.readline(64001)
        if not line:
            return
        size += len(line)
        if len(line) > 64000 or size > 150_000_000:
            raise ValueError('El catálogo expandido supera los límites del lote.')
        yield line


def import_catalog(path, *, state_database, memory_database, source_url=CATALOG_URL,
                   max_records=1000, max_scanned=100000, max_seconds=120,
                   max_storage_mb=128, languages=('es', 'en'), dry_run=False, rdf=False,
                   selected_ids=None):
    """Streaming y checkpoint ordinal+SHA256; una repetición no duplica libros."""
    from .literary_acquisition import (_limits, _path, _memory_path, _fingerprint, _connect, _hash, _json,
        _storage_limit, _put, _checkpoint, drain_projection, verify_and_release)
    _limits(max_records, max_scanned, max_seconds, max_storage_mb)
    if selected_ids is not None:
        if (not isinstance(selected_ids, (tuple, list, set, frozenset))
                or not 1 <= len(selected_ids) <= 10000
                or any(not re.fullmatch(r'[1-9]\d{0,7}', str(value)) for value in selected_ids)):
            raise ValueError('La selección requiere entre 1 y 10000 IDs válidos de catálogo.')
        selected_ids = frozenset(str(value) for value in selected_ids)
    memory_database = _memory_path(memory_database)
    if (not isinstance(languages, (tuple, list)) or len(languages) > 20
            or any(not isinstance(value, str) or not re.fullmatch(r'[a-z]{2,3}', value) for value in languages)):
        raise ValueError('Indica códigos de idioma ISO válidos.')
    if source_url != CATALOG_URL and not re.fullmatch(
            r'https://(?:www\.gutenberg\.org|gutenberg\.pglaf\.org)/cache/epub/feeds/[^?#]+', source_url):
        raise ValueError('El catálogo necesita procedencia oficial explícita.')
    if _path(state_database) == Path(memory_database).resolve():
        raise ValueError('Ledger y memoria deben ser distintos.')
    started, path = time.monotonic(), Path(path)
    deadline = started + max_seconds
    digest, signature = _fingerprint(path, deadline=deadline, clock=time.monotonic)
    selection_key = '' if selected_ids is None else '\0selection:' + _hash(_json(sorted(selected_ids)))
    dataset = _hash('gutenberg\0' + str(path.resolve()) + '\0' + source_url + '\0'
                    + _json(sorted(languages)) + selection_key)
    previous = None
    db = _connect(state_database)
    if db is not None:
        with closing(db):
            previous = db.execute('SELECT * FROM acquisition_datasets WHERE dataset_id=?', (dataset,)).fetchone()
    if previous and previous['sha256'] != digest:
        raise ValueError('El catálogo cambió; utiliza otro nombre de archivo para su nueva versión.')
    skip = previous['records'] if previous else 0
    report = {'provider': 'gutenberg', 'dry_run': dry_run, 'accepted': 0, 'scanned': 0,
              'filtered': 0, 'rejected': 0, 'inserted': 0, 'updated': 0, 'stale': 0,
              'duplicates': 0, 'complete': False,
              'offset_before': skip, 'offset_after': skip, 'sha256': digest}
    writable = _connect(state_database, write=True) if not dry_run else None
    try:
        if writable:
            _storage_limit(writable, max_storage_mb * 1024 * 1024)
        opener = gzip.open if path.suffix.lower() == '.gz' else open
        with opener(path, 'rt', encoding='utf-8-sig', newline='') as stream:
            csv.field_size_limit(64000)
            reader = (iter_rdf_catalog(path) if rdf else
                      (catalog_record(row) for row in csv.DictReader(_bounded_lines(stream, deadline))))
            for number, record in enumerate(reader, 1):
                if time.monotonic() >= deadline:
                    break
                if number <= skip:
                    continue
                if report['accepted'] >= max_records or report['scanned'] >= max_scanned or time.monotonic() >= deadline:
                    break
                report['scanned'] += 1
                report['offset_after'] = number
                if not record:
                    report['rejected'] += 1
                elif ((selected_ids is not None and record['external_id'] not in selected_ids)
                      or (languages and not set(languages).intersection(record['languages']))):
                    record = None
                    report['filtered'] += 1
                else:
                    report['accepted'] += 1
                    record['provenance'] = {'dataset_url': source_url, 'dataset_sha256': digest,
                                            'admission': 'staged',
                                            'record_number': number, 'license_scope': 'catalog_metadata_only'}
                # Las filas seleccionadas siempre tienen checkpoint atómico;
                # los descartes se agrupan para no confirmar miles de filtros.
                if writable and (selected_ids is None or record is not None or report['scanned'] % 250 == 0):
                    inserted = None
                    with writable:
                        if record:
                            inserted = _put(writable, record, with_status=True)
                        _checkpoint(writable, dataset, 'gutenberg', source_url, digest, number, number, False)
                    if inserted is not None:
                        report[inserted] += 1
            else:
                report['complete'] = True
        if signature != (path.stat().st_size, path.stat().st_mtime_ns):
            raise ValueError('El catálogo cambió durante la importación; no se proyecta.')
        if writable:
            # Un checkpoint permite reanudar, pero no autoriza publicar filas
            # hasta volver a comprobar el fichero completo. El outbox mantiene
            # staged incluso si otro trabajador intenta proyectar a la vez.
            report['admission'] = verify_and_release(path, state_database=state_database,
                source_url=source_url, expected_sha256=digest, deadline=deadline)
        if writable:
            with writable:
                _checkpoint(writable, dataset, 'gutenberg', source_url, digest,
                            report['offset_after'], report['offset_after'], report['complete'])
    except KeyboardInterrupt:
        report['paused'] = True
    except TimeoutError:
        report['budget_exhausted'] = True
    except ValueError as error:
        if 'Presupuesto agotado' not in str(error):
            raise
        report['budget_exhausted'] = True
    except sqlite3.OperationalError as error:
        if 'full' not in str(error).lower():
            raise
        report['storage_limit'] = True
    finally:
        if writable:
            writable.close()
    if not dry_run and not report.get('storage_limit'):
        remaining = deadline - time.monotonic()
        if remaining > 0:
            report['projection'] = drain_projection(state_database=state_database,
                memory_database=memory_database, max_records=max_records, max_seconds=min(remaining, 3600))
    report['seconds'] = round(time.monotonic() - started, 4)
    return report
