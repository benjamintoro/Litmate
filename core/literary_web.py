"""Lectura limitada de fuentes públicas: contenido no confiable, nunca instrucciones.

Las conexiones TLS usan exactamente una dirección previamente validada, conservan
SNI y verifican el certificado del nombre original. No usan proxies ni siguen
redirecciones. La excepción para servicios locales pertenece a ai_http, no aquí.
"""
import hashlib
import http.client
import io
import ipaddress
import json
import re
import socket
import ssl
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from django.conf import settings
from django.core.cache import cache

from .ai_budget import BudgetExpired, budget_timeout, check_budget


PUBLIC_DOMAINS = (
    'wikipedia.org', 'wikisource.org', 'wikidata.org', 'openlibrary.org',
    'gutenberg.org', 'memoriachilena.gob.cl', 'bibliotecanacionaldigital.gob.cl',
    'bnchile.gob.cl', 'cervantesvirtual.com', 'rae.es', 'penguinlibros.com',
    'planetadelibros.com', 'anagrama-ed.es', 'fce.com.mx', 'literaturasm.cl',
    'literaturasm.com', 'metmuseum.org', 'tuttlepublishing.com',
)
API_DOMAINS = ('wikipedia.org', 'wikidata.org', 'openlibrary.org', 'www.googleapis.com')
USER_AGENT = 'LitMate/Local-1.0 (+public-literary-research; no-commercial-api)'
_DNS_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix='litmate-public-dns')
_DNS_SLOTS = threading.BoundedSemaphore(3)
_INJECTION = re.compile(
    r'ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions|'
    r'ignora(?:r)?\s+(?:todas\s+)?(?:las\s+)?instrucciones\s+anteriores|'
    r'(?:reveal|print|show)\s+(?:the\s+)?system\s+prompt|'
    r'(?:revela|muestra)\s+(?:el\s+)?prompt\s+(?:del\s+)?sistema|'
    r'<\|(?:system|assistant|im_start)\|>|\[INST\]|'
    r'(?:send|env[ií]a)\s+(?:all\s+|todas?\s+)?(?:api\s*keys?|contraseñas|secrets?)',
    re.I,
)
_STOP = {'el', 'la', 'los', 'las', 'un', 'una', 'de', 'del', 'en', 'y', 'que',
         'sus', 'son', 'dime', 'cuales', 'quienes', 'libro', 'sobre', 'con', 'por'}


class PublicFetchError(ValueError):
    """Fallo tipado, sin incluir direcciones privadas ni cuerpos en registros."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise PublicFetchError('timeout')
    return budget_timeout(remaining)


def _validated_url(url, allowed_domains):
    if not isinstance(url, str) or len(url) > 4096 or re.search(r'[\x00-\x20\x7f\\]', url):
        raise PublicFetchError('unsafe_url')
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').encode('idna').decode('ascii').lower()
        if (parsed.scheme != 'https' or not host or parsed.username is not None
                or parsed.password is not None or parsed.port not in {None, 443}
                or host.endswith('.')):
            raise PublicFetchError('unsafe_url')
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise PublicFetchError('unsafe_url')
        domains = tuple(str(item).lower().strip('.') for item in allowed_domains)
        # El comodín sólo se usa para páginas descubiertas por un buscador
        # público. La resolución DNS y la conexión siguen rechazando redes
        # privadas, redirecciones y esquemas distintos de HTTPS.
        if '*' not in domains and not any(host == domain or host.endswith('.' + domain)
                                          for domain in domains if domain):
            raise PublicFetchError('domain_not_allowed')
        return urlunsplit(('https', host, parsed.path or '/', parsed.query, '')), host
    except (UnicodeError, ValueError) as exc:
        if isinstance(exc, PublicFetchError):
            raise
        raise PublicFetchError('unsafe_url') from None


def _resolve_public(host, deadline):
    if not _DNS_SLOTS.acquire(blocking=False):
        raise PublicFetchError('dns_busy')
    def resolve():
        try:
            return socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        finally:
            _DNS_SLOTS.release()
    future = _DNS_POOL.submit(resolve)
    try:
        addresses = future.result(timeout=_remaining(deadline))
    except FutureTimeout:
        raise PublicFetchError('timeout') from None
    except OSError:
        raise PublicFetchError('dns_failed') from None
    if not addresses:
        raise PublicFetchError('dns_failed')
    for family, socktype, protocol, _, address in addresses:
        try:
            ip = ipaddress.ip_address(address[0].split('%', 1)[0])
            if (family not in {socket.AF_INET, socket.AF_INET6} or not ip.is_global
                    or ip.is_multicast or ip.is_unspecified
                    or getattr(ip, 'sixtofour', None) is not None
                    or getattr(ip, 'teredo', None) is not None
                    or (getattr(ip, 'ipv4_mapped', None) is not None
                        and not ip.ipv4_mapped.is_global)):
                raise PublicFetchError('unsafe_address')
        except ValueError:
            raise PublicFetchError('unsafe_address') from None
    return addresses[0]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address, deadline):
        super().__init__(host, timeout=_remaining(deadline), context=ssl.create_default_context())
        self._address = address
        self._deadline = deadline
        self._connecting_socket = None
        self._transport_socket = None

    def connect(self):
        family, socktype, protocol, _, address = self._address
        raw = socket.socket(family, socktype, protocol)
        self._connecting_socket = raw
        self._transport_socket = raw
        try:
            raw.settimeout(_remaining(self._deadline))
            raw.connect(address)  # Sin una segunda resolución DNS.
            raw.settimeout(_remaining(self._deadline))
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
            self._transport_socket = self.sock
            self.sock.settimeout(_remaining(self._deadline))
        except BaseException:
            raw.close()
            raise
        finally:
            self._connecting_socket = None

    def abort(self):
        # HTTP/1.0 y Connection:close pueden separar el socket de connection.sock
        # mientras el cuerpo todavía se está leyendo desde response.fp.
        sock = self.sock or self._transport_socket or self._connecting_socket
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()


def _secure_fetch(url, *, allowed_domains, deadline, maximum, accept, headers=None):
    url, host = _validated_url(url, allowed_domains)
    address = _resolve_public(host, deadline)
    connection = _PinnedHTTPSConnection(host, address, deadline)
    timer = threading.Timer(_remaining(deadline), connection.abort)
    timer.daemon = True
    timer.start()
    try:
        parsed = urlsplit(url)
        request_headers = {'User-Agent': USER_AGENT, 'Accept': accept,
                           'Accept-Encoding': 'identity', 'Connection': 'close'}
        # Solo cabeceras de identificación/negociación; jamás cookies ni secretos.
        for name, value in (headers or {}).items():
            if name.lower() in {'user-agent', 'accept', 'accept-language'}:
                request_headers[name] = str(value)[:250]
        connection.request('GET', parsed.path + ('?' + parsed.query if parsed.query else ''),
                           headers=request_headers)
        response = connection.getresponse()
        status = response.status
        if 300 <= status < 400:
            raise PublicFetchError('redirect_blocked')
        if status == 429:
            raise PublicFetchError('rate_limited')
        if status >= 500:
            raise PublicFetchError('service_unavailable')
        if status != 200:
            raise PublicFetchError('http_' + str(status))
        if response.getheader('Content-Encoding', 'identity').lower() not in {'', 'identity'}:
            raise PublicFetchError('unsupported_encoding')
        length = response.getheader('Content-Length', '')
        if length.isdigit() and int(length) > maximum:
            raise PublicFetchError('too_large')
        chunks, size = [], 0
        while True:
            transport = connection.sock or connection._transport_socket
            if transport is not None:
                try:
                    transport.settimeout(_remaining(deadline))
                except OSError:
                    # read1 cierra el descriptor al consumir Content-Length.
                    # Ese EOF normal no es un fallo de conexión.
                    if response.isclosed():
                        break
                    raise
            block = response.read1(min(16_384, maximum + 1 - size))
            _remaining(deadline)
            check_budget()
            if not block:
                break
            size += len(block)
            if size > maximum:
                raise PublicFetchError('too_large')
            chunks.append(block)
        return {'body': b''.join(chunks), 'content_type': response.getheader('Content-Type', ''),
                'url': url, 'status': status}
    except (TimeoutError, BudgetExpired):
        raise PublicFetchError('timeout') from None
    except (OSError, ssl.SSLError, http.client.HTTPException):
        code = 'timeout' if time.monotonic() >= deadline else 'connection_failed'
        raise PublicFetchError(code) from None
    finally:
        timer.cancel()
        connection.close()


def read_public_json(url, *, headers=None, timeout=6, allowed_domains=None, maximum=2_000_000):
    """Objeto JSON de una API oficial gratuita; mismos límites DNS/TLS que las páginas.

    Los endpoints de APIs se rigen por su política propia, no por robots del sitio.
    Nunca usar para URLs recibidas del usuario ni para servicios locales.
    """
    deadline = time.monotonic() + budget_timeout(timeout)
    result = _secure_fetch(url, allowed_domains=API_DOMAINS if allowed_domains is None else allowed_domains,
                           deadline=deadline, maximum=maximum,
                           accept='application/json', headers=headers)
    content_type = result['content_type'].split(';', 1)[0].strip().lower()
    if content_type not in {'application/json', 'application/sparql-results+json'}:
        raise PublicFetchError('unsupported_type')
    try:
        data = json.loads(result['body'])
    except (ValueError, UnicodeError):
        raise PublicFetchError('invalid_json') from None
    if not isinstance(data, dict):
        raise PublicFetchError('invalid_json')
    return data


def _robots_can_fetch(parser, url):
    """Respeta comodines/fin de ruta también con versiones antiguas de Python."""
    agent = USER_AGENT.lower()
    entries = [(max((len(name) for name in entry.useragents
                     if name != '*' and name.lower() in agent), default=0), entry)
               for entry in parser.entries]
    specificity = max((score for score, _ in entries), default=0)
    active = [entry for score, entry in entries if score == specificity and score > 0]
    if not active:
        active = [entry for _, entry in entries if '*' in entry.useragents]
        if parser.default_entry is not None:
            active.append(parser.default_entry)
    parsed = urlsplit(url)
    target = unquote(parsed.path or '/') + ('?' + unquote(parsed.query) if parsed.query else '')
    matches = []
    for entry in active:
        for rule in entry.rulelines:
            path = unquote(rule.path)
            terminal = getattr(rule, 'fullmatch', False) or path.endswith('$')
            pattern = re.escape(path.rstrip('$')).replace(r'\*', '.*')
            if re.match('^' + pattern + ('$' if terminal else ''), target):
                matches.append((len(path.replace('*', '').rstrip('$')), rule.allowance))
    # Ante igual longitud prevalece Allow, según las reglas de robots.txt.
    return not matches or max(matches)[1]


def _robots_permission(url, host, domains, deadline):
    key = 'litmate_robots_v1:' + hashlib.sha256(host.encode()).hexdigest()
    try:
        record = cache.get(key)
    except Exception:
        raise PublicFetchError('robots_unavailable') from None
    if record is None:
        try:
            result = _secure_fetch('https://' + host + '/robots.txt', allowed_domains=domains,
                                   deadline=deadline, maximum=128_000, accept='text/plain')
            mime = result['content_type'].split(';', 1)[0].lower().strip()
            if mime not in {'text/plain', ''}:
                raise PublicFetchError('robots_unavailable')
            record = {'text': result['body'].decode('utf-8', errors='replace'), 'allow': None}
            ttl = 1800
        except PublicFetchError as exc:
            # Ausencia explícita de robots permite acceso; bloqueos/fallos no.
            if exc.code in {'http_404', 'http_410'}:
                record, ttl = {'allow': True, 'text': ''}, 1800
            elif exc.code in {'http_401', 'http_403'}:
                record, ttl = {'allow': False, 'text': ''}, 300
            else:
                record, ttl = {'allow': False, 'text': '', 'error': 'robots_unavailable'}, 30
        try:
            cache.set(key, record, ttl)
        except Exception:
            raise PublicFetchError('robots_unavailable') from None
    if not isinstance(record, dict):
        raise PublicFetchError('robots_unavailable')
    if record.get('error'):
        raise PublicFetchError(record['error'])
    parser = RobotFileParser()
    parser.parse(record.get('text', '').splitlines())
    if record.get('allow') is False or (record.get('allow') is None and not _robots_can_fetch(parser, url)):
        raise PublicFetchError('robots_denied')
    delay = max(1, parser.crawl_delay(USER_AGENT) or parser.crawl_delay('*') or 1)
    rate = parser.request_rate(USER_AGENT) or parser.request_rate('*')
    if rate and rate.requests:
        delay = max(delay, rate.seconds / rate.requests)
    try:
        if not cache.add('litmate_public_host_slot:' + host, True, timeout=max(1, int(delay + .99))):
            raise PublicFetchError('rate_limited')
    except PublicFetchError:
        raise
    except Exception:
        raise PublicFetchError('rate_limit_unavailable') from None


def read_public_html(url, *, headers=None, timeout=6, allowed_domains=None, maximum=1_500_000):
    """HTML público tras comprobar robots, DNS público y límites de tamaño.

    Se usa para buscadores y páginas descubiertas por ellos. No sigue
    redirecciones ni acepta cookies; el comodín ``'*'`` sólo evita la lista
    cerrada de dominios, nunca las comprobaciones de red privada.
    """
    domains = ('*',) if allowed_domains is None else tuple(allowed_domains)
    if not domains:
        raise PublicFetchError('domain_not_allowed')
    safe_url, host = _validated_url(url, domains)
    deadline = time.monotonic() + budget_timeout(timeout)
    _robots_permission(safe_url, host, domains, deadline)
    result = _secure_fetch(safe_url, allowed_domains=domains, deadline=deadline,
                           maximum=maximum, accept='text/html,application/xhtml+xml',
                           headers=headers)
    content_type = result['content_type'].split(';', 1)[0].strip().lower()
    if content_type not in {'text/html', 'application/xhtml+xml', ''}:
        raise PublicFetchError('unsupported_type')
    return result['body'].decode('utf-8', errors='replace')


def public_text_has_injection(text):
    """Los fragmentos web son datos; jamás deben publicar instrucciones ajenas."""
    return bool(_INJECTION.search(str(text or '')))


def _plain(value, maximum=300):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:maximum]


def character_table_passage(html, *, context='', maximum=1800):
    """Conserva filas literales de tablas bajo un encabezado de personajes.

    Solo admite columnas explícitas de nombre/descripción, nunca un reparto
    cinematográfico ni tablas encontradas fuera de la sección pertinente.
    El llamador debe verificar antes la identidad y procedencia de la página.
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(str(html or ''), 'html.parser')
    if _INJECTION.search(soup.get_text(' ', strip=True)):
        return ''
    adaptation = re.compile(r'\b(?:adaptaciones?|adaptations?|cine|cinematografic\w*|'
        r'peliculas?|films?|movies?|television|televisiv\w*|videojuegos?|video games?|cast|reparto)\b')
    rows = []
    for heading in soup.find_all(['h2', 'h3', 'h4']):
        label = _normalized(heading.get_text(' ', strip=True))
        if not re.fullmatch(r'(?:personajes(?: principales)?|(?:main )?characters|character list)', label):
            continue
        level = int(heading.name[1])
        ancestor_level, adaptation_parent = level, False
        for previous in heading.find_all_previous(['h1', 'h2', 'h3', 'h4']):
            previous_level = int(previous.name[1])
            if previous_level < ancestor_level:
                ancestor_level = previous_level
                if adaptation.search(_normalized(previous.get_text(' ', strip=True))):
                    adaptation_parent = True
                    break
        if adaptation_parent:
            continue
        blocked_level = None
        for node in heading.find_all_next(['h1', 'h2', 'h3', 'h4', 'table']):
            if node.name.startswith('h'):
                current_level = int(node.name[1])
                if current_level <= level:
                    break
                if blocked_level is not None and current_level <= blocked_level:
                    blocked_level = None
                if adaptation.search(_normalized(node.get_text(' ', strip=True))):
                    blocked_level = current_level
                continue
            if blocked_level is not None:
                continue
            table_rows = node.find_all('tr', recursive=True)
            if not table_rows:
                continue
            labels = [_normalized(cell.get_text(' ', strip=True))
                      for cell in table_rows[0].find_all(['th', 'td'], recursive=False)]
            if any(re.search(r'\b(?:actor|actriz|cast|reparto|interprete|portrayed|portrayer)\b', item)
                   for item in labels):
                continue
            names = [i for i, item in enumerate(labels) if item in {'nombre', 'personaje', 'name', 'character'}]
            roles = [i for i, item in enumerate(labels) if item in {'resumen', 'descripcion', 'description', 'summary', 'role', 'papel'}]
            if len(names) != 1 or len(roles) != 1:
                continue
            for row in table_rows[1:31]:
                cells = row.find_all(['th', 'td'], recursive=False)
                if len(cells) != len(labels) or any(cell.get('rowspan') or cell.get('colspan') for cell in cells):
                    continue
                for cell in cells:
                    for note in cell.select('sup, .reference, .mw-ref'):
                        note.decompose()
                name = _plain(cells[names[0]].get_text(' ', strip=True), 90)
                role = _plain(cells[roles[0]].get_text(' ', strip=True), 1000)
                # Una oración publicada, no un resumen generado ni un corte a
                # mitad de frase. El resto del párrafo puede contener spoilers.
                role = re.split(r'(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ])', role, maxsplit=1)[0]
                if (not re.fullmatch(r'[A-ZÁÉÍÓÚÑ][^\n,:;]{0,64}', name)
                        or len(name.split()) > 6 or not 12 <= len(role) <= 280
                        or adaptation.search(_normalized(role))):
                    continue
                rows.append((name, role))
    value = _normalized(context)
    rows.sort(key=lambda row: not bool(re.search(r'(?<!\w)' + re.escape(_normalized(row[0])) + r'(?!\w)', value)))
    lines, seen = ['== Personajes principales =='], set()
    for name, role in rows:
        line = name + ': ' + role
        if _normalized(name) in seen or len('\n'.join(lines + [line])) > maximum:
            continue
        lines.append(line)
        seen.add(_normalized(name))
        if len(seen) == 12:
            break
    return '\n'.join(lines) if len(lines) > 2 else ''


def _normalized(value):
    return ''.join(char for char in unicodedata.normalize('NFKD', value.lower())
                   if not unicodedata.combining(char))


def _relevant_excerpt(text, query, maximum):
    paragraphs = [line.strip() for line in re.split(r'\n+', text) if line.strip()]
    paragraphs = [line for line in paragraphs if not _INJECTION.search(line)]
    terms = {term for term in re.findall(r'\w+', _normalized(query))
             if len(term) >= 3 and term not in _STOP}
    if not paragraphs:
        return ''
    ranked = sorted(range(len(paragraphs)), key=lambda index: (
        -sum(term in _normalized(paragraphs[index]) for term in terms), index))
    selected, used = [], 0
    for index in ranked:
        paragraph = paragraphs[index]
        remaining = maximum - used
        if remaining < 50:
            break
        paragraph = paragraph[:remaining]
        selected.append((index, paragraph))
        used += len(paragraph) + 1
    return '\n'.join(paragraph for _, paragraph in sorted(selected))[:maximum]


def _extract_html(raw, url, query, maximum):
    import trafilatura
    from bs4 import BeautifulSoup
    from bs4.element import Comment
    # Beautiful Soup se limita a metadatos y selectores estructurales explícitos.
    soup = BeautifulSoup(raw, 'html.parser')
    def meta(*names):
        for name in names:
            node = soup.find('meta', attrs={'property': name}) or soup.find('meta', attrs={'name': name})
            if node and node.get('content'):
                return _plain(node['content'], 400)
        return ''
    title = meta('og:title', 'twitter:title') or _plain(soup.title.get_text(' ', strip=True) if soup.title else '')
    site = meta('og:site_name') or urlsplit(url).hostname
    metadata_description = meta('description', 'og:description')
    injection = bool(_INJECTION.search(soup.get_text(' ', strip=True)))
    for node in soup(['script', 'style', 'nav', 'footer', 'aside', 'form', 'iframe', 'noscript', 'template']):
        node.decompose()
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()
    headings = [_plain(node.get_text(' ', strip=True), 180)
                for node in soup.find_all(['h1', 'h2', 'h3'])
                if not _INJECTION.search(node.get_text(' ', strip=True))][:12]
    # Retira órdenes explícitas antes de seleccionar evidencia; el resto continúa
    # marcado como datos no confiables al llegar al generador.
    for node in soup.find_all(['p', 'li']):
        if _INJECTION.search(node.get_text(' ', strip=True)):
            node.decompose()
    cleaned = str(soup)
    text = trafilatura.extract(cleaned, url=url, include_comments=False, include_tables=False,
                               include_links=False, favor_precision=True) or ''
    method = 'trafilatura'
    if len(text.strip()) < 80:
        nodes = soup.select('article, main, [itemprop="description"], .entry-content, .book-description')
        text = '\n'.join(dict.fromkeys(node.get_text('\n', strip=True) for node in nodes))
        if not text:
            text = metadata_description
        method = 'beautifulsoup_structured'
    excerpt = _relevant_excerpt(text, query, maximum)
    # Son menciones candidatas, no una afirmación de que sean todos personajes.
    # Solo listas bajo un encabezado explícito de personajes proporcionan nombres.
    mentions = []
    for heading in soup.find_all(['h2', 'h3', 'h4']):
        if 'personaje' not in _normalized(heading.get_text(' ', strip=True)):
            continue
        for sibling in heading.next_siblings:
            if getattr(sibling, 'name', '') in {'h1', 'h2', 'h3', 'h4'}:
                break
            if getattr(sibling, 'name', '') in {'ul', 'ol'}:
                for node in sibling.find_all('li', recursive=False)[:15]:
                    name = re.split(r'[:—–]', node.get_text(' ', strip=True), maxsplit=1)[0]
                    name = _plain(name, 90)
                    if name and len(name.split()) <= 6 and not _INJECTION.search(name):
                        mentions.append(name)
    return {'title': title, 'site': site, 'description': excerpt, 'excerpt': excerpt,
            'headings': headings, 'character_mentions': list(dict.fromkeys(mentions))[:15],
            'injection_detected': injection, 'extraction_method': method}


def _extract_pdf(raw, query, maximum, deadline):
    """Solo PDFs breves públicos; no OCR, JavaScript ni extracción de libros enteros."""
    import zlib
    from pypdf import PdfReader
    # Preflight de streams Flate: evita expansiones enormes antes de PdfReader.
    expanded = 0
    for index, match in enumerate(re.finditer(rb'(?<![A-Za-z])stream\r?\n', raw)):
        _remaining(deadline)
        if index >= 2048:
            raise PublicFetchError('too_large')
        # No se interpreta el contenido de streams ni se ejecutan acciones PDF.
        # El análisis conservador puede rechazar PDFs inusuales; es preferible
        # a descomprimir contenidos sin límite dentro del proceso de Django.
        end = raw.find(b'endstream', match.end())
        if end == -1:
            raise PublicFetchError('invalid_pdf')
        header = raw[max(0, match.start() - 2048):match.start()]
        previous_end = header.rfind(b'endobj')
        header = header[previous_end + 6:] if previous_end != -1 else header
        if not re.search(rb'\b\d+\s+\d+\s+obj\b', header):
            raise PublicFetchError('pdf_not_brief')
        header = re.sub(rb'#([0-9A-Fa-f]{2})',
                        lambda token: bytes.fromhex(token.group(1).decode('ascii')), header)
        if re.search(rb'/Filter\s+\d+\s+\d+\s+R\b', header):
            raise PublicFetchError('unsupported_pdf_filter')
        data = raw[match.end():end].rstrip(b'\r\n')
        if any(name in header for name in (b'ASCII85Decode', b'ASCIIHexDecode', b'LZWDecode',
                                           b'RunLengthDecode', b'Crypt', b'CCITTFaxDecode')):
            raise PublicFetchError('unsupported_pdf_filter')
        if re.search(rb'/(?:A85|AHx|LZW|RL|CCF)(?=[\s/\[\]<>])', header):
            raise PublicFetchError('unsupported_pdf_filter')
        if b'FlateDecode' in header or re.search(rb'/Fl(?=[\s/\[\]<>])', header):
            decoder = zlib.decompressobj()
            try:
                unpacked = decoder.decompress(data, 1_000_001)
            except zlib.error:
                raise PublicFetchError('invalid_pdf') from None
            expanded += len(unpacked)
            if len(unpacked) > 1_000_000 or decoder.unconsumed_tail or expanded > 4_000_000:
                raise PublicFetchError('too_large')
    try:
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted or len(reader.pages) > 12:
            raise PublicFetchError('pdf_not_brief')
        fragments = []
        for page in reader.pages[:8]:
            _remaining(deadline)
            fragments.append((page.extract_text() or '')[:8000])
    except (PublicFetchError, BudgetExpired):
        raise
    except Exception:
        raise PublicFetchError('invalid_pdf') from None
    text = '\n'.join(fragments)
    excerpt = _relevant_excerpt(text, query, maximum)
    title = _plain((reader.metadata or {}).get('/Title', ''))
    return {'title': title, 'description': excerpt, 'excerpt': excerpt, 'headings': [],
            'character_mentions': [], 'injection_detected': bool(_INJECTION.search(text)),
            'extraction_method': 'pypdf_public_brief'}


def extract_public_page(url, query, *, allowed_domains=None, maximum=1800, timeout=6):
    """Recupera un pasaje breve permitido; jamás lo autoriza para indexación permanente."""
    base = {'status': 'unavailable', 'kind': 'web', 'trust': 'untrusted_data',
            'permanent_index_allowed': False, 'url': '', 'title': '', 'site': '',
            'description': '', 'excerpt': '', 'headings': [], 'character_mentions': [],
            'injection_detected': False, 'extraction_method': '',
            'retrieved_at': datetime.now(timezone.utc).isoformat()}
    try:
        domains = (tuple(allowed_domains) if allowed_domains is not None else
                   tuple(getattr(settings, 'LITMATE_AI_PUBLIC_DOMAINS', PUBLIC_DOMAINS)))
        safe_url, host = _validated_url(url, domains)
        base.update(url=safe_url, site=host)
        deadline = time.monotonic() + budget_timeout(timeout)
        _robots_permission(safe_url, host, domains, deadline)
        result = _secure_fetch(safe_url, allowed_domains=domains, deadline=deadline,
                               maximum=1_500_000, accept='text/html, application/pdf;q=0.8')
        mime = result['content_type'].split(';', 1)[0].strip().lower()
        maximum = max(100, min(int(maximum), 4000))
        if mime in {'text/html', 'application/xhtml+xml'}:
            evidence = _extract_html(result['body'], safe_url, str(query or '')[:500], maximum)
        elif mime == 'application/pdf' and result['body'].startswith(b'%PDF-'):
            evidence = _extract_pdf(result['body'], str(query or '')[:500], maximum, deadline)
        else:
            raise PublicFetchError('unsupported_type')
        _remaining(deadline)
        base.update(evidence)
        if not base['description']:
            raise PublicFetchError('empty_content')
        base['status'] = 'ok'
    except PublicFetchError as exc:
        base['status'] = exc.code
    except (BudgetExpired, TimeoutError):
        base['status'] = 'timeout'
    except (ValueError, OSError, ImportError):
        base['status'] = 'extraction_failed'
    return base
