"""Publica metadatos admitidos en el catálogo existente sin actualizar libros."""
from datetime import date
from decimal import Decimal
import json
import time
from urllib.parse import urlsplit

from django.db import connection,transaction
from django.utils.text import slugify

from core.bibliographic_repository import digest,encoded
from core.knowledge_models import KBRecord
from core.literary_genres import classify_categories
from core.literary_identity import normalize_identity
from core.models import Autor,Editorial,Genero,Libro


LABELS={'fantasy':'Fantasía','science_fiction':'Ciencia Ficción','horror':'Terror','mystery':'Misterio',
        'poetry':'Poesía','drama':'Teatro','romance':'Romance','adventure':'Aventura','essay':'Ensayo',
        'biography':'Biografía','children':'Literatura infantil','programming':'Programación',
        'networking':'Redes informáticas','cisco':'Cisco','packet_tracer':'Packet Tracer',
        'python_programming':'Python','java_programming':'Java','javascript_programming':'JavaScript',
        'sql_programming':'SQL','web_programming':'Programación web','algorithms':'Algoritmos'}


def pair_key(title,author):
    # La misma inversión bibliográfica que admite same_author_name, sin
    # equiparar apellidos sueltos ni iniciales diferentes.
    return normalize_identity(title),tuple(sorted(normalize_identity(author).split()))


def check_target():
    name=connection.settings_dict['NAME']
    if (connection.vendor!='mysql' or connection.settings_dict.get('HOST') not in {'localhost','127.0.0.1'}
            or not (name=='litmate_db' or name.startswith('litmate_catalog_restore_'))):
        raise ValueError('Se requiere el catálogo MySQL local explícito o su restauración aislada.')


class CatalogueWriter:
    """La caché del lote evita búsquedas por cada autor y materia repetidos."""
    def __init__(self):
        self.pairs={}
        for book in Libro.objects.select_related('autor').order_by('id'):
            key=pair_key(book.titulo,book.autor.nombre)
            self.pairs.setdefault(key,book)
        self.authors={}
        for author in Autor.objects.order_by('pk'):
            self.authors.setdefault(author.nombre,author)
        self.genres={genre.nombre:genre for genre in Genero.objects.all()}
        self.publishers={publisher.nombre:publisher for publisher in Editorial.objects.all()}

    def put(self,metadata):
        title,author=metadata['title'].strip(),metadata['author'].strip()
        if not 2<=len(title)<=220 or not 2<=len(author)<=200:
            raise ValueError('Identidad bibliográfica fuera de los límites.')
        key=pair_key(title,author)
        if key in self.pairs:return self.pairs[key],False
        categories=[category for category in metadata.get('categories',[]) if isinstance(category,str)]
        classifications=classify_categories(categories)
        genre=next((LABELS[code] for code in ('packet_tracer','cisco','networking','programming',
            'mystery','science_fiction','fantasy','horror','poetry','drama','romance','adventure','essay','biography','children')
            if code in classifications),'Sin clasificar')
        language=metadata.get('language') or 'und'
        language={'eng':'en','spa':'es','fra':'fr','fre':'fr','ger':'de','deu':'de','por':'pt','ita':'it'}.get(language,language)
        if len(language)>3:language='und'
        provenance=('Información catalográfica; sin sinopsis ni texto completo. Fuente: '+metadata['source_url']
                    +'\nMaterias originales: '+'; '.join(categories[:12]))
        if metadata.get('publisher') and len(metadata['publisher'])>100:
            raise ValueError('Editorial fuera de los límites.')
        with transaction.atomic():
            current_author=self.authors.get(author)
            if current_author is None:
                current_author=Autor.objects.filter(nombre=author).first() or Autor.objects.create(nombre=author)
                self.authors[author]=current_author
            publisher=None
            if name:=metadata.get('publisher'):
                if len(name)>100:raise ValueError('Editorial fuera de los límites.')
                publisher=self.publishers.get(name)
                if publisher is None:
                    publisher=Editorial.objects.create(nombre=name);self.publishers[name]=publisher
            book=Libro.objects.create(titulo=title,autor=current_author,editorial=publisher,genero=genre,
                sinopsis=provenance,idioma=language,portada_url=None,
                isbn_13=metadata.get('isbn_13') or None,paginas=metadata.get('pages') or 0,
                fecha_publicacion=date.fromisoformat(metadata['published_date']) if metadata.get('published_date') else None)
            # Las miles de materias LC originales no se convierten en miles de
            # opciones de navegación: quedan en KB y en la procedencia de la ficha.
            names=list(dict.fromkeys([genre,*[LABELS[code] for code in classifications if code in LABELS]]))
            chosen=[]
            for name in names:
                if not 1<=len(name)<=100:continue
                item=self.genres.get(name)
                if item is None:
                    item,_=Genero.objects.get_or_create(nombre=name,defaults={
                        'slug':(slugify(name)[:75] or 'materia')+'-'+digest(name)[:12]})
                    self.genres[name]=item
                chosen.append(item)
            book.generos.add(*chosen)
        self.pairs[key]=book
        return book,True


def materialize_admitted(*,maximum=13000,max_seconds=240,after=''):
    check_target()
    if not 1<=maximum<=20000 or not 1<=max_seconds<=600:raise ValueError('Lote fuera de presupuesto.')
    writer=CatalogueWriter();start=time.monotonic()
    report={'scanned':0,'created':0,'existing':0,'invalid':0,'unresolved_authors':0,'blocked':0,
            'cursor':after,'complete':False,'books':[]}
    query=KBRecord.objects.filter(id__gt=after,status='source_metadata',kind__in=['work','edition']).order_by('id')
    # El índice ya aplica la política de admisión y conserva las fuentes.
    for record in query.iterator(chunk_size=200):
        if report['scanned']>=maximum or time.monotonic()-start>=max_seconds:break
        report['scanned']+=1;report['cursor']=record.id
        data=record.payload
        if record.provider not in {'gutenberg','openlibrary','wikidata','bne'}:
            report['blocked']+=1;continue
        if digest(encoded({key:value for key,value in data.items() if key!='provenance'}))!=record.checksum:
            report['invalid']+=1;continue
        parents=[digest(record.provider,key) for key in data.get('work_keys',[])]
        if parents and KBRecord.objects.filter(pk__in=parents,status='conflict').exists():
            report['blocked']+=1;continue
        author=data.get('author')
        if not author:
            keys=data.get('author_keys',[])
            authors={item.id:item.label for item in KBRecord.objects.filter(
                id__in=[digest(record.provider,key) for key in keys],kind='author',status='source_metadata')}
            if not keys or any(digest(record.provider,key) not in authors for key in keys):
                report['unresolved_authors']+=1;continue
            author=', '.join(authors[digest(record.provider,key)] for key in keys)
        try:
            book,created=writer.put({'title':record.label,'author':author,'categories':data.get('categories',[]),
                'language':(data.get('languages') or ['und'])[0] if len(data.get('languages') or [])==1 else 'und',
                'source_url':record.source_url})
        except ValueError:
            report['invalid']+=1;continue
        report['created' if created else 'existing']+=1
        report['books'].append({'catalogue_id':book.pk,'title':book.titulo,'author':book.autor.nombre,
            'source_record':record.id,'source_url':record.source_url,'created':created})
    else:report['complete']=True
    report['seconds']=round(time.monotonic()-start,3)
    return report


def materialize_reviewed(books):
    check_target();writer=CatalogueWriter();result=[]
    if not isinstance(books,list) or len(books)>100:raise ValueError('Hasta cien fichas revisadas por lote.')
    for item in books:
        url=urlsplit(item.get('source_url',''))
        if (url.scheme!='https' or url.username or url.password or url.port not in (None,443)
                or url.hostname not in {'www.ciscopress.com','www.oreilly.com','openlibrary.org','www.gutenberg.org','seapanama.org'}
                or item.get('admission') not in {'official-publisher-bibliographic-facts-only','reviewed-catalogue-facts-only'}
                or item.get('full_text_imported') is not False):
            raise ValueError('Ficha no revisada o procedencia no permitida.')
        isbn=item.get('isbn_13')
        if isbn:
            if len(isbn)!=13 or not isbn.isdigit():raise ValueError('ISBN inválido.')
            if (10-sum(int(c)*(1 if i%2==0 else 3) for i,c in enumerate(isbn[:12]))%10)%10!=int(isbn[-1]):
                raise ValueError('ISBN inválido.')
        book,created=writer.put(item)
        result.append({'catalogue_id':book.pk,'title':book.titulo,'author':book.autor.nombre,
                       'source_url':item['source_url'],'created':created})
    return result
