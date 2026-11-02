"""Recorrido HTTP acotado del frontend real; sin pagos, correos o cuentas."""
from html.parser import HTMLParser
import json
import time
from urllib.parse import urlsplit

PAGES = ('/', '/about/', '/post/', '/libros/', '/suscripciones/planes/', '/contact/',
         '/login/', '/registro/', '/password-reset/', '/terminos-y-condiciones/',
         '/politica-de-privacidad/', '/politica-de-cookies/', '/chat/', '/chatbot/')


class Resources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.assets, self.external_images = set(), set(), set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        value = attrs.get('href' if tag in {'a', 'link'} else 'src', '')
        if tag == 'a' and value.startswith('/') and not value.startswith('//'):
            self.links.add(value)
        if tag in {'img', 'script', 'link'} and value.startswith('/static/'):
            self.assets.add(value)
        if tag == 'img' and value.startswith('https://'):
            self.external_images.add(value)


def verify_frontend(request):
    checks, pages, assets, links, images = {}, [], set(), set(), set()
    for path in PAGES:
        started = time.monotonic()
        with request(path) as response:
            html = response.read().decode('utf-8')
            checks['page:' + path] = response.status == 200 and 'navbar-brand' in html
            resources = Resources()
            resources.feed(html)
            assets.update(resources.assets)
            links.update(resources.links)
            images.update(resources.external_images)
            pages.append({'path': path, 'status': response.status,
                          'seconds': round(time.monotonic() - started, 4),
                          'internal_links': sorted(resources.links)})
            if path == '/':
                checks['real_homepage'] = 'coverflowStage' in html and 'chat-character-page' not in html
            if path in {'/login/', '/registro/', '/password-reset/', '/contact/'}:
                checks['preview_notice:' + path] = 'role="status"' in html and 'vista previa' in html.lower()
        if path in {'/login/', '/registro/', '/password-reset/', '/contact/'}:
            with request(path, {'username': 'demo-test', 'password': 'not-a-real-credential-fixture',
                                'email': 'nobody@example.invalid', 'message': 'Prueba sin envío'}) as response:
                body = response.read().decode('utf-8')
                checks['readonly_submit:' + path] = (response.status == 200
                    and 'vista previa' in body.lower() and 'not-a-real-credential-fixture' not in body)
    # Los filtros se prueban aparte, sin ejecutar decenas de búsquedas externas.
    for path in sorted({urlsplit(link).path for link in links} - set(PAGES)):
        with request(path) as response:
            checks['navigation:' + path] = response.status == 200
            response.read()
    for asset in sorted(assets):
        with request(asset) as response:
            checks['asset:' + asset] = response.status == 200 and bool(response.read())
    endpoints = []
    for path in ('/libros/?q=Dune', '/api/quick-search/?q=Dune',
                 '/api/libro/precios/?titulo=Dune&force=true'):
        with request(path) as response:
            body = response.read()
            checks['function:' + path] = response.status == 200 and bool(body)
            entry = {'path': path, 'status': response.status}
            if '/api/' in path and response.status == 200:
                data = json.loads(body)
                if 'books' in data:
                    entry['book_count'] = len(data['books'])
                    checks['catalogue_results'] = any('dune' in book['titulo'].lower() for book in data['books'])
                else:
                    entry['cached_prices'] = len(data.get('tiendas', []))
            endpoints.append(entry)
    return {'checks': checks, 'pages': pages, 'endpoints': endpoints,
            'asset_count': len(assets), 'external_cover_urls': sorted(images),
            'external_images_downloaded_by_this_check': False}
