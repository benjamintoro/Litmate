"""Wikidata oficial: entidades de obras y personajes, sin SPARQL abierto ni cargos."""
import re
from urllib.parse import urlencode
from django.core.cache import cache
from .literary_web import read_public_json
from .literary_sources import SearchResults, error_status
from .books_google import public_query


def search_wikidata(query):
    query = public_query(query)
    if not query:
        return SearchResults(status='empty')
    if not cache.add('litmate_wikidata_slot', True, timeout=2):
        return SearchResults(status='rate_limited')
    api = 'https://www.wikidata.org/w/api.php?'
    def fetch(params):
        return read_public_json(api + urlencode({'format': 'json', **params}),
            timeout=5, headers={'User-Agent': 'LitMate/1.0 (local literary research)'})
    def ids(claims, prop):
        return [str(claim.get('mainsnak', {}).get('datavalue', {}).get('value', {}).get('id', ''))
                for claim in claims.get(prop, [])[:12] if isinstance(claim, dict)
                and claim.get('rank') != 'deprecated']
    def label(entity):
        labels = entity.get('labels', {})
        return next((labels[lang].get('value', '') for lang in ('es', 'en') if lang in labels), '')
    try:
        found = fetch({'action': 'wbsearchentities', 'search': query[:200], 'language': 'es', 'limit': 3})
        candidates = [item['id'] for item in found.get('search', []) if re.fullmatch(r'Q\d+', str(item.get('id', '')))]
        if not candidates:
            return SearchResults(status='empty')
        entities = fetch({'action': 'wbgetentities', 'ids': '|'.join(candidates),
                          'props': 'labels|aliases|claims', 'languages': 'es|en'}).get('entities', {})
        related = set()
        for entity in entities.values():
            claims = entity.get('claims', {})
            related.update(ids(claims, 'P50') + ids(claims, 'P674'))
        related = sorted(item for item in related if re.fullmatch(r'Q\d+', item))[:18]
        labels = fetch({'action': 'wbgetentities', 'ids': '|'.join(related),
                        'props': 'labels', 'languages': 'es|en'}).get('entities', {}) if related else {}
        results = []
        for identifier, entity in entities.items():
            claims = entity.get('claims', {})
            authors = [label(labels.get(item, {})) for item in ids(claims, 'P50')]
            title, author = label(entity), ', '.join(item for item in authors if item)
            # Sin autor bibliográfico no se convierte una entidad cualquiera en libro.
            if not title or not author:
                continue
            url = 'https://www.wikidata.org/wiki/' + identifier
            facts = [{'name': label(labels.get(item, {})), 'role': 'Personaje registrado para esta obra en Wikidata'}
                     for item in ids(claims, 'P674') if label(labels.get(item, {}))]
            description = title + ', de ' + author + '.'
            results.append({'title': title, 'author': author, 'kind': 'book', 'source': 'Wikidata',
                'url': url, 'book_id': identifier, 'work_id': 'wikidata:' + identifier,
                'description': description, 'license': 'CC0', 'permanent_index_allowed': True})
            if facts:
                results.append({'title': title, 'author': 'Fuente web', 'kind': 'web', 'source': 'Wikidata',
                    'url': url, 'description': '\n'.join(f['name'] + ': ' + f['role'] for f in facts),
                    'identity_text': description, 'character_facts': facts, 'work_title': title,
                    'work_author': author, 'work_id': 'wikidata:' + identifier,
                    'work_binding_verified': True, 'license': 'CC0', 'read_mode': 'declaraciones de entidad de obra'})
                results[-1]['claim_verification'] = 'Wikidata statement; not independent corroboration'
        return SearchResults(results)
    except Exception as exc:
        return SearchResults(status=error_status(exc))
