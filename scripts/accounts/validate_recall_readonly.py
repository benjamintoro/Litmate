"""Piloto secuencial de recuerdos: catálogo MySQL read-only, sin HTTP ni usuarios."""
import getpass
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import time
from unittest.mock import patch


def main():
    root = Path.cwd()
    folder = root / '.testtmp' / 'recall-real-readonly-20261031-01'
    output = root / 'reports/recuerdos_opencode_20261031/real_readonly.json'
    if folder.exists() or output.exists():
        raise ValueError('Se requiere un ensayo nuevo; no se sobrescribe evidencia.')
    folder.mkdir(parents=True)
    from iniciar_mysql_local import local_database_environment
    with local_database_environment(getpass.getpass('MySQL local, sólo lectura (oculta): ')):
        os.environ['DJANGO_SETTINGS_MODULE'] = 'litmate_project.settings'
        from django.conf import settings
        settings.LOGGING_CONFIG = None
        import django
        django.setup()
        logging.disable(logging.CRITICAL)
        from django.db import connection
        from django.db.backends.signals import connection_created
        from django.test import override_settings
        from scripts.knowledge.knowledge_campaign import STORES, sqlite_snapshot
        originals = {}
        overrides = {key: folder / (key.lower() + '.sqlite3') for key in (
            *STORES, 'LITMATE_AI_RUNTIME_DB', 'LITMATE_AI_STREAM_DB', 'LITMATE_AI_ANSWER_CACHE_DB')}
        # Sólo estos dos almacenes son necesarios para el adaptador nuevo.
        for key in ('LITMATE_KNOWLEDGE_DB', 'LITMATE_LITERARY_MEMORY_DB'):
            source = Path(getattr(settings, key))
            if source.is_file():
                originals[str(source)] = hashlib.sha256(source.read_bytes()).hexdigest()
                sqlite_snapshot(source, overrides[key])
        overrides.update(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                             'LOCATION': 'recall-isolated'}},
                         LITMATE_AUTO_ENRICHMENT=False)
        def protect(sender, connection, **kwargs):
            if connection.vendor != 'mysql':
                raise RuntimeError('Conexión ORM inesperada')
            with connection.cursor() as cursor:
                cursor.execute('SET SESSION TRANSACTION READ ONLY')
        connection_created.connect(protect, weak=False, dispatch_uid='recall-readonly-pilot')
        protect(None, connection)
        def select_only(execute, sql, params, many, context):
            if not sql.lstrip().upper().startswith(('SELECT ', 'SHOW ')):
                raise RuntimeError('Escritura ORM bloqueada')
            return execute(sql, params, many, context)
        native_connect = sqlite3.connect
        def isolated_sqlite(database, *args, **kwargs):
            value = str(database)
            if str(folder).replace('\\', '/') not in value.replace('\\', '/'):
                raise RuntimeError('SQLite fuera del ensayo bloqueado')
            return native_connect(database, *args, **kwargs)
        tables = ['auth_user', 'core_conversacionia', 'core_mensajeia',
                  'suscripciones_suscripcionusuario', 'suscripciones_historialpago', 'core_libro']
        def counts():
            with connection.cursor() as cursor:
                result = {}
                for table in tables:
                    cursor.execute('SELECT COUNT(*) FROM ' + connection.ops.quote_name(table))
                    result[table] = cursor.fetchone()[0]
                return result
        cases = [
            ('El principito', 'Un niño que vivía en un planeta diminuto, cuidaba una rosa y conoció a un zorro'),
            ('La metamorfosis', 'Alguien despierta convertido en un insecto horrible y su familia lo rechaza'),
            ('Fahrenheit 451', 'Una sociedad donde se prohíben los libros y los queman'),
            ('1984', 'Una historia sobre vigilancia constante y ausencia de libertad'),
            ('Don Quijote', 'Recuerdo un caballero que confunde molinos de viento con gigantes y viaja con su escudero'),
            ('Alicia en el país de las maravillas', 'Recuerdo una niña que sigue a un conejo blanco y cae por una madriguera'),
        ]
        from core.ai_identification_details import identification_recall_answer
        from core.literary_candidates import candidate_sources
        from core.literary_ai import build_assistant, ROUTER_PROMPT
        from core.ai_presentation import build_book_cards
        report = {'scope': 'real catalogue; no server, sessions or history', 'rows': [],
                  'model': settings.LITMATE_LOCAL_MODEL, 'model_changed': False,
                  'ollama_probe': 'supplementary real routing; not the final fast-path answer'}
        with override_settings(**overrides), connection.execute_wrapper(select_only), \
                patch('sqlite3.connect', side_effect=isolated_sqlite):
            with connection.cursor() as cursor:
                cursor.execute('SELECT DATABASE(), @@session.transaction_read_only')
                database, readonly = cursor.fetchone()
                if database != 'litmate_db' or readonly != 1:
                    raise RuntimeError('No se garantiza MySQL local read-only')
            report['mysql_read_only'] = True
            report['counts_before'] = counts()
            for expected, query in cases:
                start = time.monotonic()
                row = {'expected': expected, 'query': query, 'errors': []}
                try:
                    sources, _, _ = candidate_sources(query)
                    row['retrieved'] = sources
                    result = identification_recall_answer(query)
                    row.update(final_response=result.text if result else None,
                               titles=[book['title'] for book in result.books] if result else [],
                               evidence=result.sources if result else [],
                               diagnostics=result.diagnostics if result else {},
                               cards=build_book_cards(result) if result else [],
                               fast_path_seconds=round(time.monotonic()-start, 3),
                               final_answer_llm_calls=0)
                    # La ruta rápida no llama a Qwen. Comprobar por separado su
                    # clasificador real, sin presentar esta inferencia como final.
                    _, client = build_assistant(settings)
                    probe_start = time.monotonic()
                    try:
                        row['ollama_route'] = client('route', ROUTER_PROMPT,
                            {'message': query, 'accepted_history': []}, settings.LITMATE_LOCAL_MODEL)
                    except Exception as error:
                        row['errors'].append({'stage': 'ollama', 'type': type(error).__name__})
                    row['ollama_seconds'] = round(time.monotonic()-probe_start, 3)
                    row['ollama_calls'] = client.calls
                except Exception as error:
                    row['errors'].append({'stage': 'retrieval', 'type': type(error).__name__})
                row['total_seconds'] = round(time.monotonic()-start, 3)
                report['rows'].append(row)
                output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
                print(json.dumps({k: row.get(k) for k in ('expected', 'titles', 'fast_path_seconds',
                    'ollama_seconds', 'total_seconds', 'errors')}, ensure_ascii=True), flush=True)
            vague = identification_recall_answer('Recuerdo un libro pero no recuerdo ninguna escena ni detalles')
            report['insufficient_evidence_probe'] = {'response': vague.text if vague else None,
                'confidence': vague.diagnostics.get('candidate_confidence') if vague else None}
            report['counts_after'] = counts()
            report['counts_unchanged'] = report['counts_before'] == report['counts_after']
        report['original_sqlite_unchanged'] = all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h
                                                for p, h in originals.items())
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
        connection.close()


if __name__ == '__main__':
    main()
