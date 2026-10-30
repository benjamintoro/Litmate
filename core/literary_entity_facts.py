"""Literal entity definitions and relations, independent of book-specific data."""
import re
from .literary_identity import normalize_identity
from .literary_quality import factual_statements


def profile_topic_fact(fact, body):
    """Verify a named definition followed by a zero-subject role predicate.

    A different named subject in the second sentence cannot donate its role.
    This check is reused at storage time; a profile flag is never sufficient.
    """
    proof, role, name = (str(fact.get(k, '')) for k in ('evidence','role','name'))
    if not proof or proof not in body or len(proof) > 300 or role not in proof:
        return False
    sentences = factual_statements(proof, strip_markers=False)
    if len(sentences) != 2 or not normalize_identity(sentences[0]).startswith(normalize_identity(name)+' '):
        return False
    return bool(re.match(r'(?i)^(?:Aparece|Figura|Actúa)\s+(?:especialmente\s+)?como\s+'
                         r'(?:el |la )?protagonista\b', sentences[1])
        and not re.search(r'\b(?:no|nunca|quizás|podría)\b', proof, re.I))


def profile_topic_facts(source):
    if source.get('work_binding_verified') is not True:
        return []
    body, name = source.get('description',''), source.get('title','')
    name = re.sub(r'\s*\([^)]*\)\s*$', '', name)
    lines = factual_statements(body, strip_markers=False)
    if len(lines) < 2 or not normalize_identity(lines[0]).startswith(normalize_identity(name)+' '):
        return []
    match = re.search(r'\b(?:es|fue|era)\s+', lines[0])
    if not match or not re.search(r'\b(?:personajes?|héroes?|heroínas?)\b', lines[0], re.I):
        return []
    # Keep only the clause about this bound work, before other works are named.
    second = re.split(r'\s+(?:pero|aunque|y también)\b', lines[1], maxsplit=1)[0].rstrip(' ,')
    work = normalize_identity(source.get('work_title',''))
    if not work or work not in normalize_identity(second):
        return []
    begin, middle = body.find(lines[0]), body.find(second)
    if begin < 0 or middle < begin:
        return []
    proof = body[begin:middle+len(second)]
    role = body[begin+match.end():middle+len(second)]
    fact = {'name':name,'role':role,'evidence':proof,'profile':True}
    return [fact] if profile_topic_fact(fact, body) else []


def profile_creation_relations(source):
    """A living being's named creator, within a bound fictional profile.

    Require a life/experiment predicate; authorship of a fictional character
    is a different relationship and must not be mistaken for its story creator.
    """
    if source.get('work_binding_verified') is not True:
        return []
    body, name = source.get('description',''), source.get('title','')
    lines = factual_statements(body, strip_markers=False)
    if len(lines) < 2 or normalize_identity(name) not in normalize_identity(lines[0]):
        return []
    if not re.search(r'\bes (?:un|una) personaje\b', normalize_identity(lines[0])):
        return []
    statement = lines[1]
    if (not re.match(r'(?i)^Se trata de (?:un|una)\s+', statement)
            or not re.search(r'\b(?:experimento|laboratorio|construcción|fabricación)\b', statement, re.I)
            or not re.search(r'\bvida\b', statement, re.I)
            or re.search(r'\b(?:no|nunca|quizás|podría)\b', statement, re.I)):
        return []
    match = re.search(r'\b(?:su|el) creador,?\s+([A-ZÁÉÍÓÚÑ][\w’\'-]+(?:\s+[A-ZÁÉÍÓÚÑ][\w’\'-]+){1,3})', statement)
    if not match:
        return []
    start = body.find(lines[0]); end = body.find(statement)+len(statement)
    proof = body[start:end]
    if start < 0 or not 30 <= len(statement) <= 300 or len(proof) > 1000:
        return []
    return [{'topic':'relationships','subject':match[1], 'relation':'creador','value':name,
             'evidence':proof,'role_evidence':statement, 'scope':'explicit_profile_definition'}]


def published_designations(body):
    """Quoted appellations, not embeddings or invented character aliases."""
    result = []
    body = re.sub(r'={2,}[^=]+={2,}', ' ', body).strip()
    for line in factual_statements(body, strip_markers=False):
        match = re.match(r'((?:El|La)\s+[a-záéíóúñ]+)(?:,.*?,)?\s*'
            r'(?:carece de nombre y )?es referido como\s+(.+)', line)
        if match and not re.search(r'\b(?:no|nunca)\b', match[2], re.I):
            aliases = re.findall(r'["«“]([^"»”]{2,70})["»”]', match[2])
            result.append({'subject':match[1],'aliases':aliases,'evidence':line})
    return result
