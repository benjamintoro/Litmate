"""Taxonomía derivada de materias declaradas, nunca de palabras de una sinopsis."""
import re
from .literary_identity import normalize_identity

# código, eje, padres, equivalencias de consulta/materias explícitas.
ROWS = (
 ('crime','genre',(),('crimen','ficción criminal','crime fiction','ficcion criminal')),
 ('psychological_crime','genre',('crime',),('crimen psicológico','psychological crime fiction')),
 ('mystery','genre',('crime',),('misterio','mystery','mystery fiction','detective and mystery stories')),
 ('detective','genre',('crime',),('policial','policiaco','policíaca','detective fiction','detective stories')),
 ('noir','genre',('crime',),('novela negra','noir fiction','hard boiled fiction')),
 ('thriller','genre',('crime',),('thriller','thrillers','suspenso','suspense','suspense fiction')),
 ('fantasy','genre',(),('fantasía','fantasy','fantasy fiction','fantasy literature','fairy tales')),
 ('epic_fantasy','genre',('fantasy',),('fantasía épica','epic fantasy','high fantasy')),
 ('urban_fantasy','genre',('fantasy',),('fantasía urbana','urban fantasy')),
 ('dark_fantasy','genre',('fantasy',),('fantasía oscura','dark fantasy')),
 ('science_fiction','genre',(),('ciencia ficción','science fiction','sci fi')),
 ('horror','genre',(),('terror','horror','horror tales','horror fiction','ghost stories')),
 ('romance','genre',(),('romance','romántico','romántica','romantic fiction','love stories')),
 ('historical_romance','genre',('romance','historical_fiction'),('romance histórico','historical romance')),
 ('historical_fiction','genre',(),('literatura histórica','ficción histórica','novela histórica','historical fiction')),
 ('magical_realism','genre',(),('realismo mágico','magical realism','magic realism')),
 ('adventure','genre',(),('aventura','adventure fiction','adventure stories')),
 ('drama','genre',(),('drama','teatro','plays')),
 ('poetry','genre',(),('poesía','poetry','poems')),
 ('essay','genre',('nonfiction',),('ensayo','essays')),
 ('biography','genre',('nonfiction',),('biografía','biography','autobiography')),
 ('nonfiction','genre',(),('no ficción','nonfiction','non fiction')),
 ('programming','subject',(),('programación','programming','computer programming',
    'programming electronic computers','software development','software engineering','desarrollo de software')),
 ('python_programming','subject',('programming',),('python','python computer program language',
    'python programming language','python lenguaje de programación')),
 ('java_programming','subject',('programming',),('java','java computer program language','java programming language')),
 ('javascript_programming','subject',('programming',),('javascript','javascript computer program language',
    'javascript programming language')),
 ('sql_programming','subject',('programming',),('sql','sql computer program language','structured query language')),
 ('web_programming','subject',('programming',),('programación web','web programming','web development')),
 ('algorithms','subject',(),('algoritmos','algorithms','computer algorithms')),
 ('networking','subject',(),('redes informáticas','redes de computadoras','redes de computadores',
    'redes de ordenadores','redes','computer networks','computer networking','networking','tcp ip')),
 ('cisco','subject',('networking',),('cisco','cisco systems','cisco networking','ccna','ccnp','ccst','ccie')),
 ('packet_tracer','subject',('cisco',),('packet tracer','cisco packet tracer')),
 ('manga','format',(),('manga',)),
 ('graphic_novel','format',(),('novela gráfica','graphic novels','graphic novel')),
 ('children','audience',(),('literatura infantil','infantil','children fiction','children s fiction','children s literature')),
 ('young_adult','audience',(),('literatura juvenil','juvenil','young adult fiction','juvenile fiction','juvenile literature')),
)
TAXONOMY={code:{'axis':axis,'parents':parents,'aliases':tuple(normalize_identity(x) for x in aliases)}
          for code,axis,parents,aliases in ROWS}
VERSION='literary-taxonomy-v3-networking'


def ancestors(code):
    result={code}
    for parent in TAXONOMY[code]['parents']:result.update(ancestors(parent))
    return result


def classify_categories(categories):
    """Conserva valor original y mapeo exacto. LC geografía/temas no son géneros."""
    result={}
    for raw in categories if isinstance(categories,(list,tuple)) else ():
        if not isinstance(raw,str):continue
        # BISAC jerárquico separa categorías con /; LC -- conserva el tema
        # completo para no convertir 'History -- Fiction' en no ficción.
        parts=[normalize_identity(part) for part in raw.split('/')]
        parts += [right+' '+left for left,right in zip(parts,parts[1:])]
        for code,record in TAXONOMY.items():
            if any(part in record['aliases'] for part in parts):
                for parent in ancestors(code):
                    result.setdefault(parent,[]).append(raw)
    return result


def requested_categories(text):
    value=normalize_identity(text)
    for code,row in TAXONOMY.items():
        for alias in row['aliases']:
            value=re.sub(r'\b(?:sin|excepto|no quiero|que no sean?)\s+'+re.escape(alias)+r'(?!\w)',' ',value)
    found={code for code,row in TAXONOMY.items() if any(re.search(r'(?<!\w)'+re.escape(alias)+r'(?!\w)',value)
        for alias in row['aliases'])}
    # Pedir fantasía oscura no equivale a aceptar cualquier fantasía.
    return sorted(code for code in found if not any(code in ancestors(other)-{other} for other in found))


def excluded_categories(text):
    value=normalize_identity(text)
    return {code for code,row in TAXONOMY.items() if any(re.search(
        r'\b(?:sin|excepto|no quiero|que no sean?)\s+'+re.escape(alias)+r'(?!\w)',value) for alias in row['aliases'])}


def matches_categories(source,codes):
    actual=classify_categories(source.get('categories',[]))
    if not all(code in actual for code in codes):return False
    languages={'python_programming':'python','java_programming':'java',
               'javascript_programming':'javascript','sql_programming':'sql'}
    requested={languages[code] for code in codes if code in languages}
    title=normalize_identity(source.get('title'))
    named={name for name in languages.values() if re.search(r'(?<!\w)'+name+r'(?!\w)',title)}
    # Algunas fichas colaborativas mezclan materias de varios lenguajes. Un
    # título explícito de otro lenguaje es una contradicción, no una afinidad.
    return not (requested and named and not requested & named)
