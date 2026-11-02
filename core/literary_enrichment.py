"""Enriquecimiento literal de fuentes admitidas; no genera hechos con un LLM."""
import re
from .literary_identity import same_work, normalize_identity


def has_development(source):
    """A literal distributed excerpt; not a guarantee of a complete plot."""
    from .literary_memory import _literal_facts
    return any(fact.get('topic') == 'plot' and fact.get('scope') in {'development_excerpt','sequential_excerpt'}
               for fact in _literal_facts(source.get('literary_facts',[]),source.get('description',''),'literary_facts'))


def enrich_source(source, work, requirement):
    """Anota sólo pasajes acotados del adaptador Wikipedia ya vinculado.

    Los roles proceden del extractor estructural existente. Las relaciones
    requieren una frase positiva que nombre ambos personajes y su vínculo.
    Los temas de un catálogo nunca se convierten en acontecimientos.
    """
    if (not isinstance(source, dict) or source.get('source') != 'Wikipedia'
            or source.get('storage_policy') != 'wikipedia-cc-by-sa-4.0-v1'
            or source.get('license') != 'CC-BY-SA-4.0' or not same_work(source, work)):
        return source
    scope = {'summary':'summary','synopsis':'summary','plot':'summary','plot_development':'summary',
        'characters':'characters','character_roster':'characters','main_characters':'characters','character_detail':'characters',
        'relationships':'relationships','events':'events','themes':'themes',
        'historical_context':'historical_context','adaptations':'adaptations'}.get(requirement)
    if not scope:
        return source
    body = str(source.get('description', ''))[:1800]
    facts = list(source.get('literary_facts', []))[:12]
    from .literary_entity_facts import profile_creation_relations
    facts.extend(profile_creation_relations(source))
    # Sólo un encabezado publicado identifica inequívocamente la sección.
    labels = r'argumento|trama|sinopsis|plot|resumen|la obra|temas|themes|contenido|contents|ambientación|contexto histórico|adaptaciones|adaptations'
    heading = (re.search(r'(?i)={2,}\s*('+labels+r')\s*={2,}', body)
               or re.search(r'(?im)^\s*('+labels+r')\s*$', body))
    if heading:
        text = body[heading.end():].strip()[:950]
        stop = max(text.rfind('.'), text.rfind('!'), text.rfind('?'))
        if stop >= 60:
            text = text[:stop+1]
        if len(text) >= 60:
            topic = ('themes' if normalize_identity(heading[1]) in {'temas','themes','contenido','contents'} else
                'adaptations' if normalize_identity(heading[1]) in {'adaptaciones','adaptations'} else
                'setting' if normalize_identity(heading[1]) == 'ambientacion' else
                'historical_context' if normalize_identity(heading[1]) == 'contexto historico' else 'plot')
            facts.append({'topic':topic,'evidence':text,'scope':'partial'})
    characters = source.get('character_facts', [])
    names = [fact['name'] for fact in characters if isinstance(fact, dict) and isinstance(fact.get('name'), str)]
    # Exact names only; a nickname is not resolved merely by matching a word.
    names = sorted(set(names), key=len, reverse=True)[:24]
    if names:
        name = '|'.join(re.escape(value) for value in names)
        relation = (r'(?P<subject>'+name+r')\s*(?::|\s+(?:es|era))\s*(?:el |la |un |una )?'
            r'(?P<relation>madre|padre|herman[oa]|amig[oa]|espos[oa]|hij[oa])\s+de\s+'
            r'(?P<object>'+name+r')(?!\w)')
        for match in re.finditer(relation, body):
            # Do not turn a negative, hypothetical, or quoted possibility into
            # a positive assertion. Full source checks run again on storage.
            start = max(body.rfind('\n', 0, match.start()), body.rfind('.', 0, match.start()))+1
            end = body.find('.', match.end())
            end = len(body) if end < 0 else end+1
            sentence = body[start:end].strip()
            if (len(sentence) > 900 or re.search(r'\b(?:no|nunca|quizás|tal vez|podría|sería|not|never)\b', sentence, re.I)):
                continue
            facts.append({'topic':'relationships','subject':match['subject'],
                'relation':match['relation'],'value':match['object'],
                'evidence':sentence,'scope':'explicit_statement'})
    return {**source, 'evidence_scope':scope, 'literary_facts':facts[:24]}


def narrative_coverage(database=None, work_ids=()):
    """Cuenta evidencia vigente, distingue menciones, roles y tramas explícitas."""
    import json
    import time
    from .literary_memory import _connection, _current_source, _literal_facts
    summaries, descriptions, roles, protagonists, relations, facts, linked = (set() for _ in range(7))
    memberships=set()
    developed=set()
    per_work = {}
    with _connection(database) as db:
        if db is None:
            return {'works':0}
        works = {row['work_id']: json.loads(row['record']) for row in db.execute('SELECT * FROM memory_works')
                 if not work_ids or row['work_id'] in work_ids}
        for identifier in works:
            per_work[identifier] = {'synopsis':False,'description':False,'development_excerpt':False,'roles':0,'relationships':0,'facts':0}
        for row in db.execute('SELECT source_id,work_id FROM memory_sources'):
            if row['work_id'] not in works:
                continue
            source = _current_source(db, row['source_id'], time.time())
            if not source:
                continue
            wid = source['work_id']
            linked.add((wid, row['source_id']))
            if source.get('kind') == 'web' and source.get('description') and source.get('policy') != 'wikidata-statements-v1':
                descriptions.add(wid); per_work[wid]['description'] = True
            if has_development(source):
                developed.add(wid); per_work[wid]['development_excerpt']=True
            for fact in _literal_facts(source.get('character_facts', []),source['description'],'character_facts'):
                if fact.get('membership_only'):
                    memberships.add((wid,normalize_identity(fact['name'])))
                    continue
                roles.add((wid,normalize_identity(fact['name'])))
                from .ai_character_answers import _classification
                if _classification(fact,source) == 'main':
                    protagonists.add((wid, normalize_identity(fact['name'])))
            for fact in _literal_facts(source.get('literary_facts', []),source['description'],'literary_facts'):
                token = (wid, fact.get('topic'), fact.get('subject'), fact.get('relation') or fact.get('predicate'),
                         fact.get('value') or fact.get('object') or fact.get('evidence'))
                facts.add(token)
                if fact.get('topic') in {'summary','plot'}:
                    summaries.add(wid); per_work[wid]['synopsis'] = True
                if fact.get('topic') == 'relationships':
                    relations.add(token)
        for wid, detail in per_work.items():
            detail['roles'] = sum(item[0] == wid for item in roles)
            detail['relationships'] = sum(item[0] == wid for item in relations)
            detail['facts'] = sum(item[0] == wid for item in facts)
    return {'works':len(works), 'works_with_explicit_plot':len(summaries),'works_with_development_excerpt':len(developed),
        'works_with_admitted_description':len(descriptions), 'characters_with_literal_roles':len(roles),
        'works_with_literal_roles':len({wid for wid,name in roles}),
        'characters_with_membership_only':len(memberships-roles),
        'works_with_explicit_protagonist':len({wid for wid,name in protagonists}),
        'explicit_protagonist_mentions':len(protagonists), 'relationships':len(relations),
        'narrative_facts':len(facts),'linked_sources':len(linked),'per_work':per_work,
        'verification':'source_identity_license_literal_evidence_not_independent_corroboration'}
