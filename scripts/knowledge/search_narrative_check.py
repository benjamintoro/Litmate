"""Consultas HTTP/SSE reales, MySQL local y memoria auxiliar aislada.

No importa registros ni cambia configuraciones persistentes. Las copias SQLite
permiten comparar el mismo conocimiento sin que la investigación de una prueba
alimente artificialmente la siguiente ejecución.
"""
import argparse
from contextlib import closing
import getpass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import traceback
from copy import deepcopy
from contextlib import ExitStack
from urllib.parse import urlsplit, parse_qs
from tempfile import TemporaryDirectory
from unittest.mock import patch


QUESTIONS = (
    'Hola, dime la trama de Harry Potter',
    'Dime la trama de El Se\u00f1or de los Anillos',
    'Dime los personajes de Papelucho y el marciano',
    'Dime la trama de Naruto',
)
LITERARY_CASES = (
    'Dime la trama de Naruto',
    'Dime la trama de El rey león',
    'Dime la trama de La Odisea',
    'Dime la trama de BladeRunner',
    'Dime la trama de Frankenstein',
    'Dime los personajes de Frankenstein',
    'Dime los personajes de La Odisea',
)
REPAIR_CONVERSATION = (
    'Dime la trama de Frankenstein de Mary Shelley.',
    '¿Quiénes son los personajes principales?',
    '¿Qué relación tiene Víctor Frankenstein con la criatura?',
    'Dime la trama de La Odisea.',
    '¿Quiénes son sus personajes principales?',
    'Dime la trama del manga Naruto.',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--local-only', action='store_true', help='Comprueba SQL y memoria sin proveedores externos.')
    parser.add_argument('--suite', choices=('search', 'literary'), default='search')
    parser.add_argument('--followup', action='store_true', help='Misma sesión: trama y referencia a sus personajes.')
    parser.add_argument('--conversation', action='store_true', help='Conversación pública de reparación, seis turnos exactos.')
    parser.add_argument('--question', action='append', default=[], help='Consulta pública de evaluación, sin datos personales.')
    parser.add_argument('--memory-snapshot', type=Path, help='Snapshot público de sólo lectura para comparación.')
    parser.add_argument('--trace-search',action='store_true',help='Registra consultas públicas del piloto y lecturas, sin claves ni cookies.')
    parser.add_argument('--case', type=int, choices=range(1, 8), action='append',
                        help='Caso numerado del lote literario; conserva preguntas públicas fijas.')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Utiliza una salida nueva para conservar los resultados anteriores.')
    from iniciar_mysql_local import local_database_environment
    password = getpass.getpass('Contrase\u00f1a MySQL local (oculta): ')
    with local_database_environment(password, development_http=True):
        password = None
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'litmate_project.settings')
        import django
        django.setup()
        from django.conf import settings
        from django.test import override_settings
        from django.db import connection
        from core.bibliographic_http_probe import run_probe
        from core import ai_narrative_answers as narrative
        from core import ai_character_answers as characters
        from core import literary_search
        reports = []
        def counts():
            result = {}
            with connection.cursor() as cursor:
                for table in connection.introspection.table_names(cursor):
                    cursor.execute('SELECT COUNT(*) FROM ' + connection.ops.quote_name(table))
                    result[table] = cursor.fetchone()[0]
            return result
        original_counts = counts()
        with TemporaryDirectory(prefix='litmate-narrative-check-') as temporary:
            folder = Path(temporary)
            memory = args.memory_snapshot or Path(settings.LITMATE_LITERARY_MEMORY_DB)
            copied_memory = folder / 'memory.sqlite3'
            original_memory_hash = hashlib.sha256(memory.read_bytes()).hexdigest()
            with closing(sqlite3.connect(memory.resolve().as_uri() + '?mode=ro', uri=True)) as source:
                with closing(sqlite3.connect(copied_memory)) as target:
                    source.backup(target)
            overrides = {'LITMATE_LITERARY_MEMORY_DB': copied_memory}
            for name in ('LITMATE_AI_RUNTIME_DB', 'LITMATE_AI_STREAM_DB', 'LITMATE_AI_ANSWER_CACHE_DB'):
                overrides[name] = folder / (name.lower() + '.sqlite3')
            if args.local_only:
                overrides.update(LITMATE_AI_USE_WEB=False, LITMATE_AI_USE_SEARXNG=False,
                                 LITMATE_AI_USE_OPENLIBRARY=False, LITMATE_AI_USE_WIKIDATA=False)
            original = narrative.narrative_answer
            retrieve = narrative.retrieve_sources
            synthesize = narrative.synthesize_answer
            character_run = characters.character_answer
            character_bound = characters._bound
            wikipedia_search = literary_search.search_wikipedia
            observations = []
            original_http = literary_search.read_json_url
            original_quick = __import__('core.ai_quick_answers',fromlist=['quick_knowledge_sources']).quick_knowledge_sources
            readers = {name:getattr(literary_search,name) for name in ('read_public_page','read_public_web_page')}

            def traced_http(url, **kwargs):
                parts=urlsplit(url)
                traced=(parts.hostname in {'127.0.0.1','localhost'} and parts.path=='/search')
                started=time.monotonic()
                try:
                    value=original_http(url,**kwargs)
                except Exception as exc:
                    if traced:observations.append({'stage':'searx_http','error_class':type(exc).__name__})
                    raise
                if traced:
                    params=parse_qs(parts.query)
                    observations.append({'stage':'searx_http','query':params.get('q',[''])[0],
                        'engines_requested':params.get('engines',[''])[0], 'seconds':round(time.monotonic()-started,3),
                        'unresponsive_engines':value.get('unresponsive_engines',[]),
                        'results':[{key:item.get(key) for key in ('title','url','content','engine','engines')}
                                   for item in value.get('results',[])[:10]]})
                return value

            def traced_quick(*args,**kwargs):
                value=original_quick(*args,**kwargs)
                observations.append({'stage':'known_sources','sources':value})
                return value

            def traced_reader(name):
                def read(*args,**kwargs):
                    result=readers[name](*args,**kwargs)
                    observations.append({'stage':'public_page','url':args[0],
                        'status':result.get('status') if isinstance(result,dict) else 'legacy_text',
                        'title':result.get('title') if isinstance(result,dict) else '',
                        'description':result.get('description') if isinstance(result,dict) else result})
                    return result
                return read

            def retrieved(*values, **kwargs):
                sources = retrieve(*values, **kwargs)
                observations.append({'stage': 'retrieval', 'sources': sources})
                return sources

            def synthesized(*values, **kwargs):
                kwargs['trace'] = lambda stage, output: observations.append({'stage': stage, 'output': output})
                return synthesize(*values, **kwargs)

            def observed(*values, **kwargs):
                result = original(*values, **kwargs)
                observations.append({'request': narrative.request_for(values[0], values[1] if len(values) > 1 else []),
                    'diagnostics': result.diagnostics if result else {},
                    'sources': result.sources if result else []})
                return result

            def observed_characters(*values, **kwargs):
                observations.append({'stage':'character_request', 'request':characters.request_for(*values[:2],
                    pending_clarification=kwargs.get('pending_clarification'))})
                try:
                    result = character_run(*values, **kwargs)
                except Exception as error:
                    observations.append({'stage':'character_exception', 'exception_class':type(error).__name__,
                        'frames':[{'file':Path(frame.filename).name, 'line':frame.lineno, 'function':frame.name}
                                  for frame in traceback.extract_tb(error.__traceback__)]})
                    raise
                if result is not None:
                    observations.append({'stage': 'characters', 'diagnostics': result.diagnostics,
                                         'sources': result.sources})
                return result

            def bound_characters(*values, **kwargs):
                sources = character_bound(*values, **kwargs)
                observations.append({'stage': 'character_binding', 'sources': sources})
                return sources

            def observed_wikipedia(*values, **kwargs):
                result = wikipedia_search(*values, **kwargs)
                from core.literary_sources import research_snapshot
                observations.append({'stage': 'wikipedia_adapter', 'status': getattr(result, 'status', ''),
                                     'sources': list(result), 'research': research_snapshot()})
                return result

            with ExitStack() as search_traces, override_settings(**overrides), patch.object(narrative, 'narrative_answer', side_effect=observed), \
                    patch.object(narrative, 'retrieve_sources', side_effect=retrieved), \
                    patch.object(narrative, 'synthesize_answer', side_effect=synthesized), \
                    patch.object(characters, 'character_answer', side_effect=observed_characters), \
                    patch.object(characters, '_bound', side_effect=bound_characters), \
                    patch.object(literary_search, 'search_wikipedia', side_effect=observed_wikipedia):
                if args.trace_search:
                    search_traces.enter_context(patch.object(literary_search,'read_json_url',side_effect=traced_http))
                    search_traces.enter_context(patch('core.ai_quick_answers.quick_knowledge_sources',side_effect=traced_quick))
                    for name in readers:search_traces.enter_context(patch.object(literary_search,name,side_effect=traced_reader(name)))
                questions = ((None, 'Dime la trama de Orgullo y prejuicio') if args.local_only
                             else LITERARY_CASES if args.suite == 'literary' else QUESTIONS)
                if args.case and not args.local_only:
                    questions = tuple(LITERARY_CASES[index - 1] for index in args.case)
                if args.question:
                    questions = tuple(args.question)
                if args.followup or args.conversation:
                    from core.bibliographic_http_probe import run_conversation
                    def record(result):
                        result['narrative_observations'] = deepcopy(observations)
                        result['mysql_counts_unchanged'] = counts() == original_counts
                        result['original_memory_unchanged'] = hashlib.sha256(memory.read_bytes()).hexdigest() == original_memory_hash
                        reports.append(result)
                        args.output.parent.mkdir(parents=True, exist_ok=True)
                        args.output.write_text(json.dumps(reports, ensure_ascii=True, indent=2), encoding='utf-8')
                        print(json.dumps({key:result.get(key) for key in ('question','status','seconds','answer')}, ensure_ascii=True),flush=True)
                    messages = args.question or (REPAIR_CONVERSATION if args.conversation else
                                                 ['Dime la trama de Frankenstein', '¿Y sus personajes?'])
                    run_conversation(messages, before_turn=lambda message: observations.clear(), after_turn=record)
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(json.dumps(reports, ensure_ascii=True, indent=2), encoding='utf-8')
                    print(json.dumps([{key: result.get(key) for key in ('question', 'status', 'seconds', 'answer')}
                                      for result in reports], ensure_ascii=True), flush=True)
                    return
                for question in questions:
                    observations.clear()
                    try:
                        result = run_probe(question=question, require_sql_card=question is None)
                    except Exception as error:
                        result = {'question': question, 'error': type(error).__name__}
                    result['narrative_observations'] = list(observations)
                    # HTTP 200 and an answered status are not a factual verdict.
                    result['content_manually_reviewed'] = False
                    result['mysql_row_counts'] = counts()
                    result['mysql_counts_unchanged'] = result['mysql_row_counts'] == original_counts
                    result['original_memory_unchanged'] = hashlib.sha256(memory.read_bytes()).hexdigest() == original_memory_hash
                    reports.append(result)
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(json.dumps(reports, ensure_ascii=True, indent=2), encoding='utf-8')
                    print(json.dumps({key: result.get(key) for key in ('question', 'status', 'seconds', 'answer', 'error')},
                                     ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
