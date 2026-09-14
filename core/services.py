import os
import re
import requests
import logging
import random
from decimal import Decimal
from django.conf import settings
from django.db.models import Q
from django.utils.text import slugify
from core.models import Libro, Autor, Genero, Editorial

logger = logging.getLogger('litmate')


def generar_enlaces_tiendas(titulo, autor, google_id=None, precio_base=None, isbn=None, cached_records=None):
    """
    Genera enlaces de compra y comparación de precios en librerías online.
    Prioriza enlaces directos escrapeados en la base de datos (PrecioLibroTienda) para
    llevar al usuario directamente al producto sin pasar por un buscador genérico.
    No realiza peticiones de red bloqueantes durante el renderizado del catálogo.
    """
    from core.models import PrecioLibroTienda
    from core.scraper import get_store_meta

    tiendas = []
    isbn_limpio = re.sub(r'[^\d]', '', str(isbn)) if isbn else ""
    precio_ref = precio_base or 14990
    query_busqueda = f"{titulo} {autor}".strip()
    query_plus = query_busqueda.replace(' ', '+')

    # 1. Usar registros de BD si fueron provistos o consultarlos
    if cached_records is not None:
        registros = cached_records
    else:
        registros = list(PrecioLibroTienda.objects.filter(
            titulo_referencia__iexact=titulo,
            es_enlace_directo=True
        ).order_by('precio_actual'))

    if registros:
        for ct in registros:
            meta = get_store_meta(ct.tienda)
            tiendas.append({
                'tienda': ct.tienda,
                'nombre_corto': meta['nombre_corto'],
                'formato': ct.formato,
                'precio_clp': ct.precio_actual,
                'precio_formateado': f"${ct.precio_actual:,.0f} CLP".replace(',', '.'),
                'disponibilidad': ct.disponibilidad,
                'url': ct.enlace_directo,
                'badge': meta['badge'],
                'badge_class': meta['badge_class'],
                'icono': meta['icono'],
                'es_directo': True
            })
        return tiendas

    # 2. Si aún no está en caché, generar opciones inmediatas sin bloquear con HTTP
    # Buscalibre Chile
    tiendas.append({
        'tienda': 'Buscalibre Chile',
        'nombre_corto': 'Buscalibre',
        'formato': 'Físico',
        'precio_clp': precio_ref,
        'precio_formateado': f"${precio_ref:,.0f} CLP".replace(',', '.'),
        'disponibilidad': 'Verificar Disponibilidad',
        'url': f"https://www.buscalibre.cl/libros/search?q={query_plus}",
        'badge': 'Mejor Opción',
        'badge_class': 'bg-success',
        'icono': 'iconoir-shopping-bag',
        'es_directo': False
    })

    # Feria Chilena del Libro
    url_fcl = f"https://www.feriachilenadellibro.cl/buscar?controller=search&s={isbn_limpio}" if isbn_limpio else f"https://www.feriachilenadellibro.cl/buscar?controller=search&s={query_plus}"
    tiendas.append({
        'tienda': 'Feria Chilena del Libro',
        'nombre_corto': 'Feria Chilena',
        'formato': 'Físico',
        'precio_clp': int(precio_ref * 1.05),
        'precio_formateado': f"${int(precio_ref * 1.05):,.0f} CLP".replace(',', '.'),
        'disponibilidad': 'Verificar Disponibilidad',
        'url': url_fcl,
        'badge': 'Tradicional',
        'badge_class': 'bg-warning text-dark',
        'icono': 'iconoir-shop',
        'es_directo': False
    })

    # Librería Contrapunto
    tiendas.append({
        'tienda': 'Librería Contrapunto',
        'nombre_corto': 'Contrapunto',
        'formato': 'Físico / Especialidad',
        'precio_clp': int(precio_ref * 1.08),
        'precio_formateado': f"${int(precio_ref * 1.08):,.0f} CLP".replace(',', '.'),
        'disponibilidad': 'Verificar Disponibilidad',
        'url': f"https://contrapunto.cl/search?q={query_plus}",
        'badge': 'Especializada',
        'badge_class': 'bg-info text-dark',
        'icono': 'iconoir-palette',
        'es_directo': False
    })

    # Librerías Qué Leo
    tiendas.append({
        'tienda': 'Librerías Qué Leo',
        'nombre_corto': 'Qué Leo',
        'formato': 'Físico',
        'precio_clp': int(precio_ref * 1.02),
        'precio_formateado': f"${int(precio_ref * 1.02):,.0f} CLP".replace(',', '.'),
        'disponibilidad': 'Verificar Disponibilidad',
        'url': f"https://queleochile.cl/buscar?q={query_plus}",
        'badge': 'Independiente',
        'badge_class': 'bg-secondary',
        'icono': 'iconoir-bookmark-book',
        'es_directo': False
    })

    # Google Play Books
    if google_id and not str(google_id).startswith(('db_', 'ol_')) and len(str(google_id)) >= 4:
        precio_digital = int(precio_ref * 0.65)
        tiendas.append({
            'tienda': 'Google Play Books',
            'nombre_corto': 'Google Books',
            'formato': 'eBook (Digital)',
            'precio_clp': precio_digital,
            'precio_formateado': f"${precio_digital:,.0f} CLP".replace(',', '.'),
            'disponibilidad': 'Descarga Inmediata',
            'url': f"https://books.google.cl/books?id={google_id}",
            'badge': 'Digital',
            'badge_class': 'bg-primary',
            'icono': 'iconoir-google',
            'es_directo': True
        })

    # Amazon Libros
    if isbn_limpio and len(isbn_limpio) in (10, 13):
        precio_amazon = int(precio_ref * 1.15)
        tiendas.append({
            'tienda': 'Amazon Kindle / Libros',
            'nombre_corto': 'Amazon',
            'formato': 'Tapa Blanda / Kindle',
            'precio_clp': precio_amazon,
            'precio_formateado': f"${precio_amazon:,.0f} CLP".replace(',', '.'),
            'disponibilidad': 'Envío Internacional',
            'url': f"https://www.amazon.com/dp/{isbn_limpio}",
            'badge': 'Internacional',
            'badge_class': 'bg-warning text-dark',
            'icono': 'iconoir-open-book',
            'es_directo': True
        })

    return tiendas


def generar_demo_extracto(libro_obj=None, sinopsis="", titulo="", autor=""):
    """Genera un fragmento o resumen demo para lectura preliminar."""
    if sinopsis and len(sinopsis) > 120:
        return (
            f"Adelanto de lectura — '{titulo or (libro_obj.titulo if libro_obj else 'Obra')}' de {autor or (libro_obj.autor.nombre if libro_obj else 'Autor')}:\n\n"
            f"{sinopsis}\n\n"
            "«...El universo narrativo de esta obra invita al lector a sumergirse en una trama envolvente, explorando sus temas centrales con notable maestría y profundidad de personajes.»"
        )
    return (
        f"Muestra previa de '{titulo}': Esta destacada obra combina una cuidada construcción narrativa "
        "con reflexiones profundas. Explora el comparador de precios inferior para adquirir tu copia física o digital."
    )


def buscar_libros_hibrido(query="", author="", genre="", year="", order="", max_results=36):
    """
    Motor de búsqueda híbrido y resiliente:
    1. Consulta primero el catálogo enriquecido en Base de Datos (Cloud / TiDB).
    2. Si hay pocos resultados o búsqueda específica, consulta Google Books API / Open Library de forma segura.
    3. Normaliza y fusiona los resultados con enlaces de tiendas online.
    """
    resultados = []
    google_ids_vistos = set()
    
    # -------------------------------------------------------------
    # PASO 1: Búsqueda en Base de Datos Local / Cloud
    # -------------------------------------------------------------
    db_queryset = Libro.objects.select_related('autor', 'editorial').prefetch_related('generos')
    
    filtros = Q()
    if query:
        filtros &= (
            Q(titulo__icontains=query) |
            Q(autor__nombre__icontains=query) |
            Q(genero__icontains=query) |
            Q(generos__nombre__icontains=query) |
            Q(sinopsis__icontains=query)
        )
    if author:
        filtros &= Q(autor__nombre__icontains=author)
    if genre:
        filtros &= (Q(genero__icontains=genre) | Q(generos__nombre__icontains=genre))
    if year:
        try:
            filtros &= Q(fecha_publicacion__year=int(year))
        except ValueError:
            pass

    # Ordenamiento
    if order == 'rating':
        db_queryset = db_queryset.order_by('-calificacion_promedio', '-total_resenas')
    elif order == 'recent':
        db_queryset = db_queryset.order_by('-fecha_publicacion')
    elif order == 'title':
        db_queryset = db_queryset.order_by('titulo')
    elif order == 'popular':
        db_queryset = db_queryset.order_by('-total_resenas', '-total_favoritos')
    else:
        # Por defecto ordenamos por popularidad/calificación para mostrar las mejores obras primero
        db_queryset = db_queryset.order_by('-calificacion_promedio', 'titulo')

    libros_db = list(db_queryset.filter(filtros).distinct()[:max_results])

    # Pre-cargar precios de tiendas en una sola consulta para evitar latencia N+1
    cached_tiendas_map = {}
    titulos_db = [l.titulo for l in libros_db]
    if titulos_db:
        from core.models import PrecioLibroTienda
        try:
            for pt in PrecioLibroTienda.objects.filter(titulo_referencia__in=titulos_db, es_enlace_directo=True).order_by('precio_actual'):
                cached_tiendas_map.setdefault(pt.titulo_referencia.lower(), []).append(pt)
        except Exception:
            pass

    for l in libros_db:
        gid = l.google_book_id or f"db_{l.id}"
        google_ids_vistos.add(gid)
        
        año_pub = str(l.fecha_publicacion.year) if l.fecha_publicacion else "N/A"
        recs = cached_tiendas_map.get(l.titulo.lower())
        tiendas = generar_enlaces_tiendas(l.titulo, l.autor.nombre, google_id=l.google_book_id, isbn=l.isbn_13 or l.isbn_10, cached_records=recs)
        
        precio_desde = tiendas[0]['precio_formateado'] if tiendas else '$14.990 CLP'
        link_principal = tiendas[0]['url'] if tiendas else '#'

        resultados.append({
            'id': gid,
            'db_id': l.id,
            'google_id': l.google_book_id or '',
            'isbn': l.isbn_13 or l.isbn_10 or '',
            'titulo': l.titulo,
            'autores': [l.autor.nombre],
            'autor_str': l.autor.nombre,
            'editorial': l.editorial.nombre if l.editorial else 'Editorial Internacional',
            'genero': l.genero or 'Literatura',
            'paginas': l.paginas or 320,
            'año': año_pub,
            'sinopsis': l.sinopsis or "Sinopsis disponible en el visor.",
            'demo_extracto': generar_demo_extracto(libro_obj=l, sinopsis=l.sinopsis, titulo=l.titulo, autor=l.autor.nombre),
            'imagen': l.portada_url or '',
            'calificacion': l.calificacion_promedio or 4.8,
            'total_resenas': l.total_resenas or 12,
            'tiendas': tiendas,
            'precio_desde': precio_desde,
            'link_principal': link_principal,
            'fuente': 'Catálogo LitMate'
        })

    # -------------------------------------------------------------
    # PASO 2: Consulta complementaria a Google Books API (Protegida)
    # -------------------------------------------------------------
    google_books_failed = False
    if len(resultados) < max_results:
        api_query_terms = []
        if query:
            api_query_terms.append(query)
        if author:
            api_query_terms.append(f"inauthor:{author}")
        if genre:
            api_query_terms.append(f"subject:{genre}")

        if not api_query_terms and not year:
            api_query_terms.append("novelas destacadas")

        if api_query_terms:
            api_query = " ".join(api_query_terms)
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) LitMate/1.0',
                    'Accept': 'application/json'
                }
                api_key = getattr(settings, 'GOOGLE_BOOKS_API_KEY', '') or os.environ.get('GOOGLE_BOOKS_API_KEY', '')
                url = f"https://www.googleapis.com/books/v1/volumes?q={requests.utils.quote(api_query)}&maxResults=16&langRestrict=es&orderBy=relevance"
                if api_key:
                    url += f"&key={api_key}"
                
                resp = requests.get(url, headers=headers, timeout=4)
                if resp.status_code == 200:
                    data = resp.json()
                    for item in data.get('items', []):
                        gid = item.get('id')
                        if not gid or gid in google_ids_vistos:
                            continue

                        info = item.get('volumeInfo', {})
                        titulo = info.get('title', '').strip()
                        if not titulo or len(titulo) < 2:
                            continue

                        autores = info.get('authors', ['Autor Desconocido'])
                        autor_str = ", ".join(autores)
                        pub_date = info.get('publishedDate', 'N/A')
                        año_api = pub_date[:4] if len(pub_date) >= 4 else "N/A"

                        if year and año_api != str(year):
                            continue

                        image_links = info.get('imageLinks', {})
                        portada = image_links.get('thumbnail') or image_links.get('smallThumbnail') or ''
                        if portada.startswith('http://'):
                            portada = portada.replace('http://', 'https://')

                        desc = info.get('description', '') or f"Una destacada obra literaria de {autor_str}."
                        cats = info.get('categories', ['Ficción'])
                        gen_str = cats[0] if cats else 'Ficción'
                        pags = info.get('pageCount', 280)

                        identifiers = info.get('industryIdentifiers', [])
                        isbn_val = ""
                        for ident in identifiers:
                            if ident.get('type') in ('ISBN_13', 'ISBN_10'):
                                isbn_val = ident.get('identifier', '')
                                break

                        tiendas = generar_enlaces_tiendas(titulo, autor_str, google_id=gid, isbn=isbn_val)

                        resultados.append({
                            'id': gid,
                            'db_id': None,
                            'google_id': gid,
                            'isbn': isbn_val,
                            'titulo': titulo,
                            'autores': autores,
                            'autor_str': autor_str,
                            'editorial': info.get('publisher', 'Editorial Internacional'),
                            'genero': gen_str,
                            'paginas': pags,
                            'año': año_api,
                            'sinopsis': desc,
                            'demo_extracto': generar_demo_extracto(sinopsis=desc, titulo=titulo, autor=autor_str),
                            'imagen': portada,
                            'calificacion': info.get('averageRating', 4.5),
                            'total_resenas': info.get('ratingsCount', 8),
                            'tiendas': tiendas,
                            'precio_desde': tiendas[0]['precio_formateado'] if tiendas else '$14.990 CLP',
                            'link_principal': tiendas[0]['url'] if tiendas else '#',
                            'fuente': 'Google Books'
                        })
                        google_ids_vistos.add(gid)

                        if len(resultados) >= max_results:
                            break
                elif resp.status_code == 429:
                    google_books_failed = True
                    logger.warning("Google Books API devolvió 429 (Rate limit). Activando fallback de Open Library.")
                else:
                    google_books_failed = True
            except Exception as e:
                google_books_failed = True
                logger.warning(f"Excepción en Google Books API: {e}. Activando fallback de Open Library.")

    # -------------------------------------------------------------
    # PASO 3: Fallback a Open Library API (Sin rate-limit estricto)
    # -------------------------------------------------------------
    if (google_books_failed or len(resultados) == 0) and (query or author or genre) and len(resultados) < max_results:
        try:
            ol_terms = []
            if query:
                ol_terms.append(query)
            if author:
                ol_terms.append(author)
            if genre:
                ol_terms.append(genre)
            ol_query = " ".join(ol_terms)

            ol_url = f"https://openlibrary.org/search.json?q={requests.utils.quote(ol_query)}&limit=15"
            ol_resp = requests.get(ol_url, timeout=5, headers={'User-Agent': 'LitMate/1.0 (literary-platform)'})
            
            if ol_resp.status_code == 200:
                ol_data = ol_resp.json()
                for doc in ol_data.get('docs', []):
                    ol_key = doc.get('key', '').replace('/works/', 'ol_')
                    if not ol_key or ol_key in google_ids_vistos:
                        continue

                    titulo = doc.get('title', '').strip()
                    if not titulo:
                        continue

                    autores = doc.get('author_name', ['Autor Desconocido'])
                    autor_str = ", ".join(autores) if isinstance(autores, list) else str(autores)
                    año_api = str(doc.get('first_publish_year', 'N/A'))

                    if year and año_api != str(year):
                        continue

                    cover_id = doc.get('cover_i')
                    if cover_id:
                        portada = f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"
                    else:
                        portada = ''

                    publishers = doc.get('publisher', [])
                    editorial_str = publishers[0] if publishers else 'Editorial Internacional'
                    
                    subjects = doc.get('subject', [])
                    gen_str = subjects[0] if subjects else (genre or 'Fantasía / Ficción')
                    pags = doc.get('number_of_pages_median') or 320

                    sinopsis = f"Obra literaria destacada '{titulo}' de {autor_str}. Publicada originalmente en {año_api}."
                    tiendas = generar_enlaces_tiendas(titulo, autor_str, google_id=ol_key)

                    resultados.append({
                        'id': ol_key,
                        'db_id': None,
                        'titulo': titulo,
                        'autores': autores if isinstance(autores, list) else [autores],
                        'autor_str': autor_str,
                        'editorial': editorial_str,
                        'genero': gen_str,
                        'paginas': pags,
                        'año': año_api,
                        'sinopsis': sinopsis,
                        'demo_extracto': generar_demo_extracto(sinopsis=sinopsis, titulo=titulo, autor=autor_str),
                        'imagen': portada,
                        'calificacion': 4.7,
                        'total_resenas': random.randint(15, 60),
                        'tiendas': tiendas,
                        'precio_desde': tiendas[0]['precio_formateado'],
                        'link_principal': tiendas[0]['url'],
                        'fuente': 'Open Library'
                    })
                    google_ids_vistos.add(ol_key)

                    if len(resultados) >= max_results:
                        break
        except Exception as ol_err:
            logger.warning(f"Error consultando Open Library: {ol_err}")

    return resultados
