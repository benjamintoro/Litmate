"""Biblioteca de originales autorizados: adquisición explícita, trazabilidad y RAG.

La biblioteca es auxiliar a Django. Nunca lee la base de producción y no concede
derechos a un fichero por estar disponible en Internet. Un manifiesto revisado
identifica tanto la obra como la edición/traducción y su permiso en Chile.
Los textos son datos no confiables, nunca instrucciones para el asistente.
"""
from contextlib import closing
from datetime import date, datetime, timezone
from functools import lru_cache
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import tempfile
import time
from urllib.parse import urlsplit
import zipfile
import xml.etree.ElementTree as ET

from .literary_identity import (confirmed_aliases, normalize_identity, same_author_name,
                                stable_work_id)
from .literary_web import (PublicFetchError, _robots_permission, _secure_fetch,
                          _validated_url, public_text_has_injection)


VERSION = 'local-library-v1'
MAX_FILE_BYTES = 25_000_000
MAX_TEXT_CHARS = 12_000_000
DOWNLOAD_DOMAINS = ('gutenberg.pglaf.org', 'www.gutenberg.org', 'www.ibiblio.org')
OPEN_LICENSES = {'CC0-1.0', 'CC-BY-4.0', 'CC-BY-SA-4.0'}
_CHAPTER = re.compile(r'^\s*(?:cap[ií]tulo|chapter|libro|book|parte|part|canto)\s+'
                      r'(?:[ivxlcdm]+|\d+|[a-záéíóúñ]+)(?:[ .:—-].*)?$', re.I)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _text(value, maximum=500):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:maximum]


def _evidence_url(value):
    try:
        parsed = urlsplit(str(value))
        host = (parsed.hostname or '').lower()
        if not '.' in host or host.endswith(('.localhost', '.local', '.internal')):
            return False
        try:
            if not ipaddress.ip_address(host).is_global:
                return False
        except ValueError:
            pass
        return (parsed.scheme == 'https' and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None
                and parsed.port in {None, 443})
    except ValueError:
        return False


def validate_record(record):
    """Valida la declaración humana de derechos; no emite una opinión legal.

    Un año de muerte no valida ilustraciones, traducciones o prólogos. Por eso
    se requiere declaración de cobertura de esta edición y evidencia separada.
    El dominio público estadounidense de Gutenberg nunca se acepta como CL.
    """
    if not isinstance(record, dict):
        raise ValueError('Registro bibliográfico inválido')
    item = dict(record)
    for key in ('title', 'author', 'language', 'edition', 'source_url'):
        if not isinstance(item.get(key), str) or not item[key].strip():
            raise ValueError('Falta metadato obligatorio: ' + key)
    if not re.fullmatch(r'[a-z]{2,3}(?:-[A-Za-z]{2,4})?', item['language']):
        raise ValueError('Idioma ISO inválido')
    if not _evidence_url(item['source_url']):
        raise ValueError('La procedencia debe ser una URL HTTPS')
    if public_text_has_injection(item['title'] + ' ' + item['author']):
        raise ValueError('Metadatos con instrucciones no permitidas')
    rights = item.get('rights')
    if not isinstance(rights, dict) or rights.get('jurisdiction') != 'CL':
        raise ValueError('Falta revisión de derechos aplicable a Chile (CL)')
    if rights.get('edition_covered') is not True:
        raise ValueError('No se revisaron traducción, edición e ilustraciones')
    if not rights.get('statement') or len(str(rights['statement']).strip()) < 30:
        raise ValueError('Falta explicación verificable del permiso de esta edición')
    try:
        reviewed = date.fromisoformat(rights.get('reviewed_at', ''))
    except (ValueError, TypeError):
        raise ValueError('Fecha de revisión inválida') from None
    if reviewed > datetime.now(timezone.utc).date():
        raise ValueError('La revisión no puede tener fecha futura')
    evidence = rights.get('evidence_urls', [])
    if (not isinstance(evidence, list) or not evidence or len(evidence) > 12
            or any(not _evidence_url(url) for url in evidence)):
        raise ValueError('Faltan URLs de evidencia del permiso')
    status = rights.get('status')
    if status == 'public_domain':
        # Conservador: no automatiza excepciones de plazo ni versiones anónimas.
        creators = rights.get('creators')
        if not isinstance(creators, list) or not creators:
            raise ValueError('Dominio público exige autores/traductores de esta edición')
        for creator in creators:
            if not isinstance(creator, dict) or not creator.get('name'):
                raise ValueError('Falta identidad de un creador')
            year = creator.get('death_year')
            if (not isinstance(year, int) or isinstance(year, bool)
                    or year == 0 or not -5000 <= year <= datetime.now(timezone.utc).year):
                raise ValueError('Falta año de fallecimiento verificable')
            if year + 70 >= datetime.now(timezone.utc).year:
                raise ValueError('No se ha demostrado extinción del plazo de setenta años')
            if not _evidence_url(creator.get('evidence_url', '')):
                raise ValueError('Falta fuente del año de fallecimiento')
        if not any(same_author_name(creator['name'], item['author'])
                   or same_author_name(creator['name'], item.get('source_author')) for creator in creators):
            raise ValueError('La revisión de derechos no incluye al autor de esta obra')
        item['license'] = 'Public domain (Chile); reviewed edition'
    elif status == 'open_license':
        if rights.get('license') not in OPEN_LICENSES:
            raise ValueError('Licencia abierta no admitida o no identificada')
        item['license'] = rights['license']
    elif status == 'explicit_permission':
        if rights.get('permission_id') is None or not rights.get('permission_scope'):
            raise ValueError('Falta permiso explícito documentado y alcance')
        item['license'] = 'Explicit permission: ' + _text(rights['permission_id'], 100)
    else:
        raise ValueError('Estado de derechos no permitido para texto completo')
    digest = item.get('sha256')
    if not isinstance(digest, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', digest):
        raise ValueError('Falta SHA256 esperado de la edición original')
    item['sha256'] = digest.lower()
    if bool(item.get('path')) == bool(item.get('download_url')):
        raise ValueError('Indica exactamente path local o download_url')
    fmt = item.get('format') or Path(item.get('path', '')).suffix.lstrip('.').lower()
    if fmt not in {'txt', 'epub'}:
        raise ValueError('Sólo TXT y EPUB autorizados')
    item['format'] = fmt
    item['work_id'] = stable_work_id(item['title'], item['author'])
    item['confirmed_aliases'] = confirmed_aliases(dict(item, source='Biblioteca literaria local'))
    item['document_id'] = _sha((item['work_id'] + '\0' + item['edition'] + '\0'
                                + digest.lower()).encode())[:32]
    return item


def _database_path(database):
    database = Path(database).resolve()
    from django.conf import settings
    if settings.configured:
        protected = [Path(value['NAME']).resolve() for value in settings.DATABASES.values()
                     if value.get('NAME') and value['NAME'] != ':memory:']
        for name in dir(settings):
            if name.startswith('LITMATE_') and name.endswith('_DB') and 'LIBRARY' not in name:
                value = getattr(settings, name, None)
                if value:
                    protected.append(Path(value).resolve())
        if database in protected:
            raise ValueError('La biblioteca no puede modificar una base existente de la aplicación')
    if database.is_file():
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=3)) as check:
            try:
                owner = check.execute('SELECT version FROM library_owner WHERE id=1').fetchone()
            except sqlite3.Error:
                owner = None
            if owner != (VERSION,):
                raise ValueError('La base no pertenece a la biblioteca LitMate; no se adopta ni modifica')
    return database


def _connect(database, readonly=False):
    database = _database_path(database)
    exists = database.is_file()
    if readonly:
        if not exists:
            raise ValueError('No existe la biblioteca auxiliar')
        return sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=3)
    database.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(database, timeout=3)
    db.execute('PRAGMA busy_timeout=3000')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS library_owner (id INTEGER PRIMARY KEY,version TEXT NOT NULL);
        INSERT OR IGNORE INTO library_owner VALUES (1,'local-library-v1');
        CREATE TABLE IF NOT EXISTS library_items (
            document_id TEXT PRIMARY KEY, work_id TEXT NOT NULL, sha256 TEXT NOT NULL,
            record TEXT NOT NULL, acquired_at TEXT NOT NULL, status TEXT NOT NULL,
            original_path TEXT NOT NULL, bytes INTEGER NOT NULL, text_chars INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS library_chapters (
            document_id TEXT NOT NULL, number INTEGER NOT NULL, label TEXT NOT NULL,
            text TEXT NOT NULL, PRIMARY KEY(document_id,number));
        CREATE TABLE IF NOT EXISTS library_events (
            id INTEGER PRIMARY KEY, document_id TEXT, action TEXT, at TEXT, detail TEXT);
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
            title,author,body,filename UNINDEXED,locator UNINDEXED,
            document_id UNINDEXED,chunk_id UNINDEXED,
            tokenize="unicode61 remove_diacritics 2");
        CREATE TABLE IF NOT EXISTS documents(document_id TEXT PRIMARY KEY,title TEXT,author TEXT);
        CREATE TABLE IF NOT EXISTS document_metadata(document_id TEXT PRIMARY KEY,record TEXT);
        CREATE TABLE IF NOT EXISTS rag_metadata(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS rag_vectors(rowid INTEGER PRIMARY KEY,chunk_id TEXT UNIQUE,
            dimension INTEGER,vector BLOB);
    ''')
    return db


def _local_bytes(path, base):
    relative = Path(path)
    if relative.is_absolute() or '..' in relative.parts or relative.drive:
        raise ValueError('El path debe ser relativo al manifiesto, sin escapar de su carpeta')
    target = base.joinpath(relative)
    if any(part.is_symlink() for part in [target, *target.parents] if part != base.parent):
        raise ValueError('No se permiten enlaces simbólicos en el origen')
    target = target.resolve()
    if not target.is_relative_to(base.resolve()) or not target.is_file():
        raise ValueError('No existe el archivo local autorizado')
    if not 1 <= target.stat().st_size <= MAX_FILE_BYTES:
        raise ValueError('Archivo vacío o superior a 25 MB')
    return target.read_bytes()


def download_original(url, *, timeout=15, maximum=MAX_FILE_BYTES):
    """Descarga limitada desde distribuciones autorizadas; nunca crawl de ebooks.

    El sitio principal sólo admite harvest/catálogos para robots. El manifiesto
    de libros usa espejos oficiales; no sigue redirecciones a otro servidor.
    """
    safe_url, host = _validated_url(url, DOWNLOAD_DOMAINS)
    path = urlsplit(safe_url).path
    if host == 'www.gutenberg.org' and not path.startswith('/robot/harvest'):
        raise PublicFetchError('use_official_mirror')
    if host == 'www.ibiblio.org' and not path.startswith('/pub/docs/books/gutenberg/'):
        raise PublicFetchError('download_path_not_allowed')
    deadline = time.monotonic() + max(1, min(float(timeout), 30))
    _robots_permission(safe_url, host, DOWNLOAD_DOMAINS, deadline)
    from django.core.cache import cache
    if not cache.add('litmate_library_download_slot:' + host, True, timeout=2):
        raise PublicFetchError('rate_limited', retry_after='2')
    result = _secure_fetch(safe_url, allowed_domains=DOWNLOAD_DOMAINS,
        deadline=deadline, maximum=min(int(maximum), MAX_FILE_BYTES),
        accept='text/plain,application/epub+zip,application/octet-stream')
    content_type = result['content_type'].split(';')[0].strip().lower()
    if content_type not in {'text/plain', 'application/epub+zip', 'application/octet-stream'}:
        raise PublicFetchError('unsupported_type')
    return result['body']


def _decode(raw):
    if b'\0' in raw[:1000] and not raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        raise ValueError('El archivo TXT parece binario')
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16')
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        return raw.decode('cp1252')


def _clean_text(body):
    body = body.replace('\r\n', '\n').replace('\r', '\n').replace('\x00', '')
    # Se conserva siempre el original íntegro en almacenamiento por hash.
    start = re.search(r'^\*\*\* START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK .*?\*\*\*\s*$',
                      body, re.M | re.I)
    end = re.search(r'^\*\*\* END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK .*?\*\*\*',
                    body, re.M | re.I)
    if start:
        body = body[start.end():end.start() if end and end.start() > start.end() else None]
    return re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+', '\n\n', body).strip()


def _txt_chapters(body):
    lines, sections, current, label = body.splitlines(), [], [], 'Inicio'
    for line in lines:
        if len(line) < 180 and _CHAPTER.fullmatch(line) and current:
            value = '\n'.join(current).strip()
            if value:
                sections.append((label, value))
            current, label = [line], line.strip()
        else:
            current.append(line)
    value = '\n'.join(current).strip()
    if value:
        sections.append((label, value))
    return sections


def _xml(raw):
    if b'\0' in raw or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('DTD y entidades XML no permitidas')
    return ET.fromstring(raw)


def _epub_chapters(raw):
    from bs4 import BeautifulSoup
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise ValueError('EPUB corrupto') from None
    with archive:
        infos = archive.infolist()
        if (len(infos) > 3000 or sum(i.file_size for i in infos) > MAX_FILE_BYTES * 4
                or any(i.file_size > 8_000_000 or i.flag_bits & 1 for i in infos)):
            raise ValueError('EPUB excesivo, cifrado o comprimido de forma insegura')
        for info in infos:
            name = PurePosixPath(info.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in info.filename:
                raise ValueError('Ruta insegura en EPUB')
        if archive.read('mimetype').strip() != b'application/epub+zip':
            raise ValueError('Tipo EPUB inválido')
        container = _xml(archive.read('META-INF/container.xml'))
        rootfile = next((node.get('full-path') for node in container.iter()
                         if node.tag.split('}')[-1] == 'rootfile'), None)
        if not rootfile or rootfile not in archive.namelist():
            raise ValueError('Falta documento OPF de EPUB')
        package = _xml(archive.read(rootfile))
        manifest = {node.get('id'): node.get('href') for node in package.iter()
                    if node.tag.split('}')[-1] == 'item'
                    and node.get('media-type') in {'application/xhtml+xml', 'text/html'}}
        sections = []
        for node in package.iter():
            if node.tag.split('}')[-1] != 'itemref' or node.get('linear') == 'no':
                continue
            href = manifest.get(node.get('idref'), '')
            path = PurePosixPath(rootfile).parent / href.split('#')[0]
            if not href or path.is_absolute() or '..' in path.parts or str(path) not in archive.namelist():
                raise ValueError('Referencia EPUB insegura o inexistente')
            soup = BeautifulSoup(archive.read(str(path)), 'html.parser')
            for unwanted in soup.select('script,style,nav,iframe,object,svg'):
                unwanted.decompose()
            heading = soup.find(['h1', 'h2', 'h3'])
            label = _text(heading.get_text(' ', strip=True), 180) if heading else str(path)
            body = _clean_text(soup.get_text('\n\n', strip=True))
            if body:
                sections.append((label, body))
        return sections


def extract_chapters(raw, fmt):
    chapters = _epub_chapters(raw) if fmt == 'epub' else _txt_chapters(_clean_text(_decode(raw)))
    if not chapters or sum(len(text) for _, text in chapters) > MAX_TEXT_CHARS:
        raise ValueError('No hay texto o supera el límite de 12 millones de caracteres')
    if sum(len(text) for _, text in chapters) < 80:
        raise ValueError('Texto insuficiente para indexar')
    return chapters


def _check_language_and_identity(raw, item, chapters):
    """Compara metadatos internos si existen; heurística lingüística conservadora.

    No convierte la detección automática en una identificación bibliográfica.
    Textos breves/mixtos permanecen como idioma declarado, sin falsa confianza.
    """
    metadata = {}
    if item['format'] == 'epub':
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            container = _xml(archive.read('META-INF/container.xml'))
            opf = next(node.get('full-path') for node in container.iter()
                       if node.tag.split('}')[-1] == 'rootfile')
            package = _xml(archive.read(opf))
            for node in package.iter():
                key = node.tag.split('}')[-1]
                if key in {'title', 'creator', 'language', 'rights'} and node.text:
                    metadata.setdefault(key, node.text.strip())
    else:
        # Decodifica antes de cortar para no confundir UTF-8 con CP1252 al
        # partir un carácter multibyte justo en el límite de inspección.
        header = _decode(raw)[:20000]
        start = header.upper().find('*** START OF')
        if start >= 0:
            header = header[:start]
        if item['rights']['status'] == 'public_domain' and _copyright_conflict(header):
            raise ValueError('El aviso de derechos del original contradice el dominio público declarado')
        for label, key in [('Title', 'title'), ('Author', 'creator'), ('Language', 'language')]:
            found = re.search(r'^' + label + r':\s*(.+)$', header, re.M | re.I)
            if found:
                metadata[key] = found.group(1).strip()
    if item['rights']['status'] == 'public_domain' and _copyright_conflict(metadata.get('rights', '')):
        raise ValueError('El aviso de derechos del EPUB contradice el dominio público declarado')
    expected_title = normalize_identity(item.get('source_title', item['title']))
    actual_title = normalize_identity(metadata.get('title', ''))
    if actual_title and actual_title != expected_title:
        raise ValueError('El título interno no coincide con la edición del manifiesto')
    actual_author = normalize_identity(metadata.get('creator', ''))
    if actual_author and actual_author != normalize_identity(item.get('source_author', item['author'])):
        # Orden invertido bibliográfico y palabras completas, nunca apellidos
        # aislados ni iniciales desconocidas.
        if sorted(actual_author.split()) != sorted(normalize_identity(item.get('source_author', item['author'])).split()):
            raise ValueError('El autor interno no coincide con el manifiesto')
    language = metadata.get('language', '').lower()
    language = {'english': 'en', 'spanish': 'es', 'español': 'es'}.get(language, language).split('-')[0]
    if language and re.fullmatch(r'[a-z]{2,3}', language):
        if language != item['language'].split('-')[0]:
            raise ValueError('El idioma interno no coincide con el manifiesto')
        item['language_validation'] = 'embedded_metadata'
        return
    words = re.findall(r'\b\w+\b', ' '.join(body[:10000] for _, body in chapters[:3]).lower())
    lexical = {'es': {'el', 'la', 'los', 'las', 'una', 'que', 'del', 'con', 'para', 'por'},
               'en': {'the', 'and', 'was', 'were', 'with', 'from', 'this', 'that', 'his', 'her'}}
    counts = {lang: sum(word in markers for word in words) for lang, markers in lexical.items()}
    detected = max(counts, key=counts.get)
    other = min(counts.values())
    if counts[detected] >= 12 and counts[detected] >= 4 * max(1, other):
        if item['language'].split('-')[0] in lexical and detected != item['language'].split('-')[0]:
            raise ValueError('La detección lingüística contradice el idioma declarado')
        item['language_validation'] = 'lexical_check'
    else:
        item['language_validation'] = 'declared_only'


def _copyright_conflict(text):
    """Un aviso editorial antiguo no determina derechos actuales en Chile.

    Sólo llega aquí una edición con creadores y derechos ya revisados. Una
    etiqueta actual «Copyrighted» contradice esa revisión; un aviso histórico
    fechado no lo hace automáticamente. Sin fecha, se conserva la cautela.
    """
    if re.search(r'\bcopyrighted\b', text, re.I):
        return True
    for notice in re.finditer(r'\ball rights reserved\b', text, re.I):
        context = text[max(0, notice.start() - 250):notice.end() + 100]
        years = [int(value) for value in re.findall(r'\b(?:1[4-9]\d{2}|20\d{2})\b', context)]
        if (not re.search(r'\bcopyright\b', context, re.I) or not years
                or any(year + 70 >= datetime.now(timezone.utc).year for year in years)):
            return True
    return False


def chapter_chunks(text, maximum=1800):
    """Párrafos completos; sólo divide párrafos enormes entre frases/palabras.

    Los offsets hacen referencia al texto normalizado de este capítulo. No se
    inventan páginas ni se solapan capítulos o ediciones diferentes.
    """
    start, length = 0, len(text)
    while start < length:
        end = min(start + maximum, length)
        if end < length:
            paragraph = text.rfind('\n\n', start + maximum // 3, end)
            sentence = max(text.rfind('. ', start + maximum // 2, end),
                           text.rfind('? ', start + maximum // 2, end),
                           text.rfind('! ', start + maximum // 2, end))
            boundary = paragraph if paragraph >= 0 else sentence + 1 if sentence >= 0 else text.rfind(' ', start + maximum // 2, end)
            if boundary > start:
                end = boundary
        fragment = text[start:end].strip()
        offset = start + len(text[start:end]) - len(text[start:end].lstrip())
        if len(fragment) >= 30:
            yield offset, fragment
        start = end
        while start < length and text[start].isspace():
            start += 1


def _atomic_write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if _sha(path.read_bytes()) != _sha(raw):
            raise ValueError('Original existente no coincide con su hash')
        return
    handle, staging = tempfile.mkstemp(prefix='.library-', dir=path.parent)
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging, path)
    finally:
        Path(staging).unlink(missing_ok=True)


def _attributes(item):
    return {'kind': 'excerpt', 'source': 'Biblioteca literaria local',
        'url': item['source_url'], 'license': item['license'],
        'work_id': item['work_id'], 'work_title': item['title'],
        'work_author': item['author'], 'indexing_authorized': True,
        'work_binding_verified': True, 'edition': item['edition'],
        'language': item['language'], 'original_sha256': item['sha256'],
        'rights': item['rights'], 'extraction_version': VERSION}


def import_manifest(manifest, database, storage, *, dry_run=False, download=False,
                    max_books=10, max_total_bytes=250_000_000, max_seconds=120,
                    stop=None, progress=None):
    """Importa un lote acotado, reanudable por documento SHA/edición.

    dry_run no crea DB, carpetas ni archivos y jamás descarga. stop es una
    función opcional para pausa/cancelación entre documentos. Una interrupción
    conserva documentos confirmados y la siguiente ejecución los omite.
    """
    started, manifest = time.monotonic(), Path(manifest).resolve()
    if manifest.stat().st_size > 2_000_000:
        raise ValueError('El manifiesto supera 2 MB')
    payload = json.loads(manifest.read_text(encoding='utf-8-sig'))
    if not isinstance(payload, dict) or payload.get('version') != 1 or not isinstance(payload.get('books'), list):
        raise ValueError('Manifiesto inválido; se requiere version:1 y books:[]')
    if len(payload['books']) > 5000:
        raise ValueError('Divide el manifiesto en lotes de hasta 5000 registros')
    storage, database = Path(storage).resolve(), _database_path(database)
    if database == manifest or database.is_relative_to(storage / 'originals'):
        raise ValueError('Ubicación de base auxiliar insegura')
    report = {'version': VERSION, 'dry_run': bool(dry_run), 'processed': 0,
        'imported': 0, 'skipped': 0, 'attempted': 0, 'chunks': 0, 'bytes': 0, 'errors': [],
        'stopped': '', 'sources': {}}
    existing_bytes = 0
    if database.is_file():
        with closing(_connect(database, readonly=True)) as db:
            existing_bytes = db.execute('SELECT COALESCE(SUM(bytes),0) FROM library_items').fetchone()[0]
    for position, candidate in enumerate(payload['books']):
        if time.monotonic() - started > max(1, float(max_seconds)):
            report['stopped'] = 'time_limit'
            break
        if stop and stop():
            report['stopped'] = 'paused'
            break
        report['processed'] += 1
        try:
            item = validate_record(candidate)
            if database.is_file():
                with closing(_connect(database, readonly=True)) as db:
                    found = db.execute('SELECT status FROM library_items WHERE document_id=?',
                                       (item['document_id'],)).fetchone()
                if found:
                    # Una retractación requiere restauración explícita, jamás
                    # se reactiva silenciosamente al repetir el manifiesto.
                    report['skipped'] += 1
                    continue
            if report['attempted'] >= max(1, min(int(max_books), 5000)):
                report['stopped'] = 'book_limit'
                break
            report['attempted'] += 1
            if item.get('download_url'):
                if dry_run:
                    _validated_url(item['download_url'], DOWNLOAD_DOMAINS)
                    report['skipped'] += 1
                    continue
                if not download:
                    raise ValueError('Descarga desactivada; usa --descargar explícitamente')
                remaining = max(1, float(max_seconds) - (time.monotonic() - started))
                raw = download_original(item['download_url'], timeout=min(15, remaining))
            else:
                raw = _local_bytes(item['path'], manifest.parent)
            if _sha(raw) != item['sha256']:
                raise ValueError('SHA256 de la edición no coincide')
            if existing_bytes + report['bytes'] + len(raw) > int(max_total_bytes):
                report['stopped'] = 'storage_limit'
                break
            chapters = extract_chapters(raw, item['format'])
            _check_language_and_identity(raw, item, chapters)
            fragments = [(number, label, offset, text)
                for number, (label, body) in enumerate(chapters, 1)
                for offset, text in chapter_chunks(body)]
            if not fragments or len(fragments) > 12000:
                raise ValueError('Cantidad de fragmentos inválida')
            if not dry_run:
                original = storage / 'originals' / (item['sha256'] + '.' + item['format'])
                _atomic_write(original, raw)
                with closing(_connect(database)) as db, db:
                    stamp = _now()
                    db.execute('INSERT INTO library_items VALUES (?,?,?,?,?,?,?,?,?)',
                        (item['document_id'], item['work_id'], item['sha256'], _json(item),
                         stamp, 'active', str(original), len(raw), sum(len(x[1]) for x in chapters)))
                    db.execute('INSERT INTO documents VALUES (?,?,?)',
                               (item['document_id'], item['title'], item['author']))
                    db.execute('INSERT INTO document_metadata VALUES (?,?)',
                               (item['document_id'], _json(_attributes(item))))
                    db.executemany('INSERT INTO library_chapters VALUES (?,?,?,?)',
                        ((item['document_id'], number, label, body)
                         for number, (label, body) in enumerate(chapters, 1)))
                    for number, label, offset, text in fragments:
                        chunk_id = _sha((item['document_id'] + str(number) + ':' + str(offset) + text).encode())[:32]
                        locator = f'capítulo/sección {number}: {label}; caracteres {offset}–{offset + len(text)}'
                        db.execute('INSERT INTO chunks VALUES (?,?,?,?,?,?,?)',
                            (item['title'], item['author'], text, item['document_id'] + '.txt',
                             locator, item['document_id'], chunk_id))
                    db.execute('INSERT INTO library_events(document_id,action,at,detail) VALUES (?,?,?,?)',
                               (item['document_id'], 'import', stamp, item['sha256']))
            report['imported'] += 1
            report['bytes'] += len(raw)
            report['chunks'] += len(fragments)
            source = urlsplit(item['source_url']).hostname
            report['sources'][source] = report['sources'].get(source, 0) + 1
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError, sqlite3.Error) as exc:
            report['errors'].append({'position': position, 'error': _text(str(exc), 180)})
            if len(report['errors']) >= max(1, min(int(max_books), 5000)):
                report['stopped'] = 'error_limit'
                break
        if progress:
            progress(dict(report))
    report['seconds'] = round(time.monotonic() - started, 6)
    return report


def library_status(database):
    """Sólo lectura; no crea una base inexistente."""
    database = Path(database).resolve()
    if not database.is_file():
        return {'exists': False, 'active': 0, 'retracted': 0, 'chunks': 0, 'bytes': 0}
    with closing(_connect(database, readonly=True)) as db:
        counts = dict(db.execute('SELECT status,COUNT(*) FROM library_items GROUP BY status'))
        return {'exists': True, 'active': counts.get('active', 0),
            'retracted': counts.get('retracted', 0),
            'chunks': db.execute('SELECT COUNT(*) FROM chunks').fetchone()[0],
            'bytes': db.execute('SELECT COALESCE(SUM(bytes),0) FROM library_items').fetchone()[0],
            'chapters': db.execute('SELECT COUNT(*) FROM library_chapters').fetchone()[0],
            'database_bytes': database.stat().st_size,
            'documents': [{'document_id': row[0], 'title': row[1], 'author': row[2]}
                          for row in db.execute('SELECT document_id,title,author FROM documents ORDER BY title')]}


@lru_cache(maxsize=1)
def _curated_alias_entries():
    """Carga alias editoriales revisados; un archivo dañado falla cerrado."""
    path = Path(__file__).resolve().parent / 'data' / 'library_aliases.json'
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return ()
    if not isinstance(payload, dict) or payload.get('version') != 1:
        return ()
    entries = []
    for entry in payload.get('aliases', [])[:100]:
        if not isinstance(entry, dict) or not entry.get('title') or not entry.get('author'):
            continue
        aliases = []
        for alias in entry.get('aliases', [])[:20]:
            if (not isinstance(alias, dict) or not alias.get('title')
                    or not _evidence_url(alias.get('source_url'))
                    or not isinstance(alias.get('evidence'), str)):
                continue
            aliases.append({'title': _text(alias['title'], 220),
                'author': _text(alias.get('author', entry['author']), 180),
                'source_url': alias['source_url'],
                'evidence': _text(alias['evidence'], 1500)})
        if aliases:
            entries.append({'title': entry['title'], 'author': entry['author'],
                            'aliases': aliases})
    return tuple(entries)


def curated_aliases(title, author):
    """Variantes en español con evidencia, sólo para la obra y autoría exactos."""
    wanted, wanted_author = normalize_identity(title), normalize_identity(author)
    result = []
    for entry in _curated_alias_entries():
        if (normalize_identity(entry['title']) == wanted
                and same_author_name(entry['author'], author)):
            result.extend(entry['aliases'])
    return result


def list_library_books(query, database, limit=12):
    """Identidades locales y alias documentados; no resume ni inventa tramas."""
    database = Path(database).resolve()
    if not database.is_file():
        return []
    wanted, selected = normalize_identity(query), []
    with closing(_connect(database, readonly=True)) as db:
        for raw, stamp in db.execute('SELECT record,acquired_at FROM library_items WHERE status="active"'):
            item = json.loads(raw)
            existing = item.get('confirmed_aliases')
            existing = existing if isinstance(existing, list) else []
            aliases = confirmed_aliases(dict(item, source='Biblioteca literaria local',
                confirmed_aliases=[*existing, *curated_aliases(item['title'], item['author'])]))
            titles = [normalize_identity(item['title']), *(normalize_identity(a['title']) for a in aliases)]
            author = normalize_identity(item['author'])
            if wanted and not any(title and (wanted == title or re.search(r'(?<!\w)' + re.escape(title) + r'(?!\w)', wanted))
                                  for title in titles) and wanted != author:
                continue
            selected.append({'title': item['title'], 'author': item['author'],
                'kind': 'book', 'source': 'Biblioteca literaria local',
                'url': item['source_url'], 'work_id': item['work_id'],
                'work_title': item['title'], 'work_author': item['author'],
                'work_binding_verified': True, 'confirmed_aliases': aliases,
                'language': item['language'], 'edition': item['edition'],
                'license': item['license'], 'library_document_id': item['document_id'],
                'original_sha256': item['sha256'], 'acquired_at': stamp,
                'complete_work': True, 'indexing_authorized': True})
    return selected[:max(1, min(int(limit), 50))]


def retrieve_library(query, database, maximum=4, *, books=None, embedder=None, index=None):
    """Reutiliza FTS/BM25 y RRF semántico actuales, con identidad bibliográfica."""
    from .local_rag import retrieve_fragments
    from .literary_research import looks_like_front_matter
    if not Path(database).is_file():
        return []
    retrieval_db = Path(index) if index is not None else Path(database)
    sources = retrieve_fragments(query, retrieval_db, maximum, embedder=embedder,
                                book_identities=books)
    if index is not None and retrieval_db.is_file():
        # El índice vectorial es sólo candidato. Se vuelve a comprobar su
        # documento original en la biblioteca vigente antes de usar el texto.
        with closing(sqlite3.connect(retrieval_db.resolve().as_uri() + '?mode=ro', uri=True)) as derived:
            for source in sources:
                row = derived.execute('SELECT m.record FROM chunks c JOIN document_metadata m '
                    'ON m.document_id=c.document_id WHERE c.chunk_id=?', (source['book_id'],)).fetchone()
                metadata = json.loads(row[0]) if row else {}
                source['_library_document_id'] = metadata.get('library_document_id')
                source['_library_sha256'] = metadata.get('original_sha256')
    with closing(_connect(database, readonly=True)) as db:
        for source in sources:
            if index is None:
                row = db.execute('SELECT record FROM library_items WHERE document_id=(SELECT '
                    'document_id FROM chunks WHERE chunk_id=?) AND status="active"',
                    (source['book_id'],)).fetchone()
            else:
                row = db.execute('SELECT record FROM library_items WHERE document_id=? AND sha256=? '
                    'AND status="active"', (source.pop('_library_document_id', None),
                    source.pop('_library_sha256', None))).fetchone()
            if not row:
                continue
            item = json.loads(row[0])
            if index is not None:
                body = _text(source['description'], 10000)
                chapter = next(((number, label, text) for number, label, text in db.execute(
                    'SELECT number,label,text FROM library_chapters WHERE document_id=? ORDER BY number',
                    (item['document_id'],)) if body in _text(text, MAX_TEXT_CHARS)), None)
                if not chapter:
                    continue
                number, label, _ = chapter
                source['locator'] = f'capítulo/sección {number}: {label}; fragmento del índice derivado'
            source.update(title=item['title'], author=item['author'],
                url=item['source_url'], license=item['license'],
                work_id=item['work_id'], work_title=item['title'], work_author=item['author'],
                library_document_id=item['document_id'], indexing_authorized=True, edition=item['edition'],
                language=item['language'], original_sha256=item['sha256'],
                rights=item['rights'], extraction_version=VERSION, complete_work=False,
                source='Biblioteca literaria local', read_mode='fragmento del original autorizado')
            # La compuerta de sinopsis se calcula sobre el fragmento completo,
            # antes de que canonical_sources recorte la descripción. Así un
            # prefacio largo no se vuelve «narrativa» al perder sus marcas.
            source['front_matter'] = looks_like_front_matter({**source, 'kind': 'excerpt'})
    verified = [source for source in sources if source.get('original_sha256')]
    if index is not None and not verified:
        return retrieve_library(query, database, maximum, books=books)
    return verified


def retract_document(document_id, database, *, reason):
    """Retira sólo índices derivados; conserva original, capítulos e historial."""
    if not str(reason).strip():
        raise ValueError('Se requiere motivo de retractación')
    if not Path(database).is_file():
        return False
    with closing(_connect(database)) as db, db:
        rowids = [row[0] for row in db.execute('SELECT rowid FROM chunks WHERE document_id=?', (document_id,))]
        for rowid in rowids:
            db.execute('DELETE FROM rag_vectors WHERE rowid=?', (rowid,))
        db.execute('DELETE FROM chunks WHERE document_id=?', (document_id,))
        db.execute('DELETE FROM documents WHERE document_id=?', (document_id,))
        db.execute('DELETE FROM document_metadata WHERE document_id=?', (document_id,))
        changed = db.execute('UPDATE library_items SET status="retracted" WHERE document_id=? AND status="active"',
                             (document_id,)).rowcount
        if changed:
            db.execute('INSERT INTO library_events(document_id,action,at,detail) VALUES (?,?,?,?)',
                       (document_id, 'retract', _now(), _text(reason)))
    return bool(changed)


def export_rag(database, folder):
    """Exporta copias derivadas gestionadas, nunca elimina archivos del usuario.

    Devuelve metadata compatible con index_documents. No sustituye ni modifica
    el índice personal de settings.LITMATE_RAG_DB.
    """
    folder = Path(folder).resolve()
    marker, previous_file = folder / '.litmate-library-export', folder / 'metadatos.json'
    if marker.is_symlink() or previous_file.is_symlink():
        raise ValueError('No se permiten enlaces en los controles de exportación')
    if folder.exists() and any(folder.iterdir()) and not marker.is_file():
        raise ValueError('La exportación requiere carpeta vacía o gestionada por LitMate')
    folder.mkdir(parents=True, exist_ok=True)
    (folder / '.litmate-library-export').write_text(VERSION, encoding='utf-8')
    if previous_file.is_file() and previous_file.stat().st_size > 2_000_000:
        raise ValueError('El control de exportación supera 2 MB')
    previous = json.loads(previous_file.read_text(encoding='utf-8')) if previous_file.is_file() else {}
    if not isinstance(previous, dict) or any(not isinstance(value, dict) for value in previous.values()):
        raise ValueError('Control de exportación inválido')
    metadata = {}
    with closing(_connect(database, readonly=True)) as db:
        for document_id, raw in db.execute('SELECT document_id,record FROM library_items WHERE status="active"'):
            item = json.loads(raw)
            def safe_name(value):
                value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', ' ', value)
                return re.sub(r'\s+', ' ', value).strip(' .')[:90] or 'Obra'
            filename = safe_name(item['title']) + '__' + safe_name(item['author']) + '.txt'
            if filename in metadata:
                filename = safe_name(item['title']) + ' ' + document_id[:8] + '__' + safe_name(item['author']) + '.txt'
            body = '\n\n'.join(text for (text,) in db.execute(
                'SELECT text FROM library_chapters WHERE document_id=? ORDER BY number', (document_id,)))
            destination = folder / filename
            if destination.exists():
                old = previous.get(filename, {})
                if (destination.is_symlink() or not old.get('export_sha256')
                        or _sha(destination.read_bytes()) != old['export_sha256']):
                    raise ValueError('No se sobrescribe un archivo ajeno o modificado: ' + filename)
            destination.write_bytes(body.encode('utf-8'))
            metadata[filename] = dict(_attributes(item), library_document_id=document_id,
                                      export_sha256=_sha(body.encode('utf-8')))
    # Sólo elimina derivados del manifiesto anterior si su hash coincide.
    # Archivos personales o modificados manualmente permanecen intactos.
    for filename, attributes in previous.items():
        if filename in metadata or Path(filename).name != filename or not filename.endswith('.txt'):
            continue
        stale = folder / filename
        if (stale.is_file() and not stale.is_symlink() and attributes.get('export_sha256')
                and _sha(stale.read_bytes()) == attributes['export_sha256']):
            stale.unlink()
    (folder / 'metadatos.json').write_text(_json(metadata), encoding='utf-8')
    return metadata


def read_gutenberg_rdf(path, *, languages=('es', 'en'), maximum=100):
    """Lee RDF oficial local por iterparse; sólo descubrimiento, ningún permiso.

    No descarga el catálogo global ni retiene todo el árbol en memoria. Las
    licencias estadounidenses del catálogo se conservan sin inferir derechos CL.
    """
    if Path(path).stat().st_size > 500_000_000:
        raise ValueError('Usa un subconjunto RDF oficial de hasta 500 MB')
    # DTD/entity scanning streaming antes de iterparse evita expansión de XML.
    with open(path, 'rb') as stream:
        previous = b''
        for block in iter(lambda: stream.read(65536), b''):
            chunk = previous + block.upper()
            if b'\0' in chunk or b'<!DOCTYPE' in chunk or b'<!ENTITY' in chunk:
                raise ValueError('DTD y entidades XML no permitidas')
            previous = chunk[-16:]
    count, stack = 0, []
    for event, node in ET.iterparse(path, events=('start', 'end')):
        if event == 'start':
            stack.append(node)
            continue
        if node.tag.split('}')[-1] != 'ebook':
            stack.pop()
            continue
        values = {}
        for child in node.iter():
            key = child.tag.split('}')[-1]
            if key in {'title', 'name', 'rights'} and child.text:
                values.setdefault(key, []).append(child.text.strip())
            if key == 'language':
                values['language'] = [value.text.strip() for value in child.iter()
                                      if value.tag.split('}')[-1] == 'value' and value.text]
        identifier = next((value for key, value in node.attrib.items() if key.endswith('about')), '')
        if set(values.get('language', [])) & set(languages):
            yield {'identifier': identifier, 'title': values.get('title', [''])[0],
                'authors': values.get('name', []), 'languages': values.get('language', []),
                'catalog_rights': values.get('rights', []), 'full_text_authorized': False}
            count += 1
        node.clear()
        if len(stack) >= 2:
            stack[-2].remove(node)
        stack.pop()
        if count >= max(1, min(int(maximum), 5000)):
            break
