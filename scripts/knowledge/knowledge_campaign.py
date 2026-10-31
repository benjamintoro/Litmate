"""Piloto reanudable sobre los almacenes existentes; no crea otro catálogo.

Inventario de sólo lectura antes de investigar. Los resultados HTTP usan una
copia privada persistente entre A/B/C; nunca se presentan como ingesta global.
"""
import argparse
from contextlib import closing, ExitStack
import getpass
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import socket
import sqlite3
import time
from unittest.mock import patch


CASES = (
    ('La península de las casas vacías', 'David Uclés', 'novela'),
    ('Mugre rosa', 'Fernanda Trías', 'novela'),
    ('La dimensión desconocida', 'Nona Fernández', 'no_ficcion'),
    ('Las indignas', 'Agustina Bazterrica', 'novela'),
    ('Un verdor terrible', 'Benjamín Labatut', 'narrativa_hibrida'),
    ('El tercer paraíso', 'Cristian Alarcón', 'novela'),
    ('Nuestra parte de noche', 'Mariana Enríquez', 'novela'),
    ('Los abismos', 'Pilar Quintana', 'novela'),
    ('El invencible verano de Liliana', 'Cristina Rivera Garza', 'no_ficcion'),
    ('La bastarda', 'Trifonia Melibea Obono', 'novela'),
    ('Ekomo', 'María Nsué Angüe', 'novela'),
    ('La mucama de Omicunlé', 'Rita Indiana', 'novela'),
    ('Frieren', 'Kanehito Yamada', 'manga'),
    ('Dandadan', 'Yukinobu Tatsu', 'manga'),
    ('Pluto', 'Naoki Urasawa', 'manga'),
    ('Sapiens', 'Yuval Noah Harari', 'no_ficcion'),
    ('Emma', 'Jane Austen', 'novela'),
    ('Frankenstein', 'Mary Shelley', 'novela'),
    ('The jade cabinet', 'Rikki Ducornet', 'novela'),
    ('El Señor de los Anillos', 'J. R. R. Tolkien', 'novela'),
    ('Nana', 'Émile Zola', 'novela'),
    ('La Odisea', 'Homero', 'poema_epico'),
)
STORES = ('LITMATE_LITERARY_MEMORY_DB', 'LITMATE_KNOWLEDGE_DB',
    'LITMATE_KNOWLEDGE_RAG_DB', 'LITMATE_RAG_DB', 'LITMATE_LIBRARY_DB',
    'LITMATE_LIBRARY_RAG_DB', 'LITMATE_LITERARY_MEMORY_RAG_DB')
REVIEW_ALIASES = {1:['The Peninsula of Vacant Houses'],2:['Pink Slime'],3:['The Twilight Zone'],
    4:['The Unworthy'],5:['When We Cease to Understand the World'],6:['The Third Paradise'],
    7:['Our Share of Night'],9:["Liliana's Invincible Summer"],12:['Tentacle'],
    13:['Frieren: Beyond Journey\u2019s End','Sousou no Frieren','葬送のフリーレン'],
    14:['Dan Da Dan','ダンダダン'],22:['Odisea','The Odyssey']}


def save_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=True, indent=2)


def sqlite_snapshot(source, destination):
    with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro', uri=True)) as src:
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)


def candidate_selection(works,stats,*,maximum=100,preferred=()):
    """Demand + available reader languages, reserving 1/5 for wider coverage.

    No title-length ranking: it biased the first pilot toward short CJK titles
    while the existing full-page adapters currently read Spanish and English.
    The normal continuous worker also retains its independent rotating cursor.
    """
    from collections import deque
    from core.literary_identity import normalize_identity
    from core.literary_learning import prioritize_works
    demanded={r.get('work_id') for r in stats if isinstance(r,dict) and
              (r.get('hits',0) or r.get('failures',0))}
    ranked=prioritize_works([w for w in works if w.get('work_id') in demanded],stats,maximum=100)
    demand_ranks={w['work_id']:i for i,w in enumerate(ranked)}
    ranks={normalize_identity(title):i for i,title in enumerate(preferred)}
    ordered=sorted(works,key=lambda w:(demand_ranks.get(w['work_id'],len(demand_ranks)),
        ranks.get(normalize_identity(w['title']),len(ranks)),w['work_id']))
    supported=deque(w for w in ordered if str(w.get('language','')).lower() in {'es','en','spa','eng'})
    other=deque(w for w in ordered if str(w.get('language','')).lower() not in {'es','en','spa','eng'})
    selected=[];authors={}
    while len(selected)<maximum and (supported or other):
        pool=(other if len(selected)%5==4 and other else supported) if supported else other
        if not pool:
            pool=other
        work=pool.popleft()
        author=normalize_identity(work.get('author'))
        if not author or authors.get(author,0)>=2:
            continue
        authors[author]=authors.get(author,0)+1
        selected.append(work)
    return selected


def public_store_matches(path, cases):
    """Conservative presence: substring hits may overcount, never certify absence.

    Scan only auxiliary public knowledge databases, not user history/session DBs.
    A hit is a lead for manual identity review, not an automatically merged work.
    """
    from core.literary_identity import normalize_identity
    hits = [[] for case in cases]
    schema = {}
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                  if not row[0].startswith(('sqlite_', 'memory_usage', 'memory_jobs', 'memory_meta'))]
        for table in tables:
            quoted = '"'+table.replace('"','""')+'"'
            columns = db.execute('PRAGMA table_info('+quoted+')').fetchall()
            schema[table] = db.execute('SELECT COUNT(*) FROM '+quoted).fetchone()[0]
            text_columns = [i for i, col in enumerate(columns) if col[2].upper() in {'TEXT', 'VARCHAR', 'JSON', ''}]
            if not text_columns:
                continue
            needles = [(normalize_identity(title), normalize_identity(author)) for title, author, kind in cases]
            for row in db.execute('SELECT * FROM '+quoted):
                text = normalize_identity(' '.join(str(row[i]) for i in text_columns if row[i] is not None))
                for i, (title, author) in enumerate(needles):
                    if title in text and len(hits[i]) < 8:
                        hits[i].append({'table': table, 'title_match': True, 'full_author_match': author in text})
    return hits, schema


def freeze(folder):
    from django.conf import settings
    from django.db import connection
    from core.knowledge_models import KBRecord, KBName
    from core.models import Libro
    from core.literary_identity import normalize_identity
    from core.literary_memory import default_path
    from core.literary_enrichment import narrative_coverage
    cases = [{'case':i+1, 'title':title, 'author':author, 'kind':kind, 'presence':{}}
             for i,(title, author, kind) in enumerate(CASES)]
    schemas = {}
    for name in STORES:
        value = getattr(settings, name, '')
        if not value or not Path(value).is_file():
            schemas[name] = {'available': False}
            continue
        matches, schema = public_store_matches(Path(value), CASES)
        schemas[name] = {'available':True,'tables':schema,'bytes':Path(value).stat().st_size}
        for case, hit in zip(cases, matches):
            case['presence'][name] = hit
    for case in cases:
        names = list(KBName.objects.filter(normalized__contains=normalize_identity(case['title']))
                     .values_list('record_id', flat=True)[:10])
        direct = list(KBRecord.objects.filter(label__icontains=case['title']).values('id','label','kind')[:10])
        legacy = list(Libro.objects.filter(titulo__icontains=case['title']).values_list('pk',flat=True)[:10])
        case['presence']['mysql'] = {'name_record_ids':names,'direct_records':direct,'legacy_ids':legacy}
        case['absent_at_start'] = not (names or direct or legacy or
            any(hit for name,hit in case['presence'].items() if name != 'mysql'))
    report = {'cases':cases,'absent_at_start':sum(case['absent_at_start'] for case in cases),
        'stores':schemas,'memory_coverage':narrative_coverage(),
        'sql_counts':sql_counts(), 'disk_free_bytes':shutil.disk_usage(folder).free,
        'absence_scope':'all public SQLite text fields plus MySQL names/labels and legacy catalog; reviewed aliases separately',
        'google_baseline':'not executed; independent references required', 'source_verification_pending':True}
    save_new(folder/'frozen.json',report)
    sqlite_snapshot(default_path(),folder/'initial_memory.sqlite3')
    print(json.dumps({'frozen_cases':len(cases),'absent':report['absent_at_start'],
                     'free_gb':round(report['disk_free_bytes']/2**30,2)},ensure_ascii=True),flush=True)


def sql_counts():
    from django.db import connection
    with connection.cursor() as cursor:
        result = {}
        for name in connection.introspection.table_names(cursor):
            cursor.execute('SELECT COUNT(*) FROM '+connection.ops.quote_name(name))
            result[name] = cursor.fetchone()[0]
        return result


def review_absence(folder,backup):
    """Conservative audit of variants; aliases are search leads, not DB merges."""
    from core.knowledge_models import KBRecord,KBName
    from core.literary_identity import normalize_identity
    frozen=json.loads((folder/'frozen.json').read_text(encoding='utf-8'))
    variants=[]; owners=[]
    for case in frozen['cases']:
        for alias in [case['title'],*REVIEW_ALIASES.get(case['case'],[])]:
            variants.append((alias,case['author'],case['kind']));owners.append(case['case'])
    checks={case['case']:[] for case in frozen['cases']}
    # The original full backup includes the default memory RAG path which was
    # not exposed as a setting in the initial inventory. Preserve that omission
    # transparently and inspect its immutable pre-experiment snapshot here.
    for path in sorted((backup/'files'/'data').rglob('*.sqlite3')):
        if any(word in path.name for word in ('runtime','stream','answers','adquisicion','ol_')):
            continue
        if path.name=='literary_memory.sqlite3':
            path=folder/'initial_memory.sqlite3'
        matches,unused=public_store_matches(path,variants)
        for i,hits in enumerate(matches):
            if hits:
                checks[owners[i]].append({'variant':variants[i][0],'snapshot':str(path),'hits':hits})
    for i,(alias,author,kind) in enumerate(variants):
        names=KBName.objects.filter(normalized__contains=normalize_identity(alias)).count()
        records=KBRecord.objects.filter(label__icontains=alias).count()
        if names or records:
            checks[owners[i]].append({'variant':alias,'mysql_name_matches':names,'mysql_label_matches':records})
    reviewed=[{'case':case['case'],'title':case['title'], 'initial_absence':case['absent_at_start'],
        'variant_leads':checks[case['case']],
        'conservatively_absent':case['absent_at_start'] and not checks[case['case']]} for case in frozen['cases']]
    result={'reviewed':reviewed,'absent_count':sum(c['conservatively_absent'] for c in reviewed),
        'omission':'Initial settings inventory did not resolve the default memory RAG path; immutable pre-experiment backup inspected here.',
        'aliases_are_search_leads_not_verified_identity_merges':True}
    save_new(folder/'absence_review.json',result)
    print(json.dumps({'reviewed':len(reviewed),'absent_count':result['absent_count']},ensure_ascii=True),flush=True)


def project(folder,backup):
    """Append evidence references only; never rewrite catalogue/user rows."""
    from django.db import transaction,connection
    from core.database_transfer import verify_backup
    from scripts.knowledge.continuous_worker import verify_additive_sql
    from core.continuous_knowledge import project_references
    output=folder/'sql_evidence_projection.json'
    if output.exists():
        raise FileExistsError('La proyección ya tiene checkpoint; no se sobrescribe.')
    manifest=verify_backup(backup)
    before=verify_additive_sql(backup,manifest)
    records=[json.loads(p.read_text(encoding='utf-8')) for p in folder.rglob('enrichment_[0-9]*.json')]
    ids=list(dict.fromkeys(r['work']['work_id'] for r in records if r['coverage_changed']))
    batches=[]
    for start in range(0,len(ids),25):
        with transaction.atomic():
            count=project_references(ids[start:start+25])
        batches.append({'work_ids':ids[start:start+25],'references_added':count})
    connection.check_constraints()
    save_new(output,{'before':before,'batches':batches,'after':verify_additive_sql(backup,manifest),
        'catalogue_rows_rewritten':0,'reader_rows_written':0,'passages_copied_to_mysql':0})
    print(json.dumps({'works_considered':len(ids),'references_added':sum(b['references_added'] for b in batches)}),flush=True)


def ingest_public_case(folder, identifiers):
    """Re-fetch the licensed public article; never promote benchmark prose."""
    from core.ai_budget import request_budget
    from core.literary_sources import research_scope
    from core.literary_search import search_wikipedia
    from core.ai_persistent_router import persist_sources
    from core.literary_identity import _verified_web_work,same_author_name,normalize_identity
    from core.literary_memory import default_path
    for identifier in identifiers:
        case=CASES[identifier-1]
        output=folder/f'public_ingestion_{identifier:02}.json'
        if output.exists():
            continue
        with request_budget(time.monotonic()+12),research_scope(maximum=2,seconds=10,pages=1):
            found=search_wikipedia('"'+case[0]+'" '+case[1]+' argumento')
        accepted=[]
        for source in found:
            identity=_verified_web_work(source)
            if (identity and normalize_identity(identity['title'])==normalize_identity(case[0])
                    and same_author_name(identity['author'],case[1])):
                accepted.append(source)
        # A pre-write source snapshot is already covered by the verified full
        # backup + campaign's pre_enrichment_memory. New content remains subject
        # to the normal closed license/identity/literal evidence policy.
        result=persist_sources(accepted)
        save_new(output,{'case':identifier,'source_count':len(found),'matching':len(accepted),
            'result':result,'sources':accepted,'generated_assertions_admitted':0,
            'verification':'publisher identity cross-check plus existing license/identity/literal policy; not exhaustive corroboration'})
        print(json.dumps({'case':identifier,'matching':len(accepted),'result':result}),flush=True)


def finalize(folder,backup,final_backup):
    from core.database_transfer import verify_backup,create_backup
    from scripts.knowledge.continuous_worker import verify_additive_sql
    from core.literary_memory import default_path
    from core.literary_memory_rag import index_path
    from core.literary_enrichment import narrative_coverage
    if (folder/'final_integrity.json').exists() or final_backup.exists():
        raise FileExistsError('Conserva el cierre anterior y elige un nuevo checkpoint.')
    manifest=verify_backup(backup)
    sql=verify_additive_sql(backup,manifest)
    preserved=archived=missing=0
    memory=default_path()
    with closing(sqlite3.connect((folder/'initial_memory.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)) as old:
        with closing(sqlite3.connect(memory.resolve().as_uri()+'?mode=ro',uri=True)) as current:
            old_ids={r[0] for r in old.execute('SELECT work_id FROM memory_works')}
            new_ids={r[0] for r in current.execute('SELECT work_id FROM memory_works')}
            if not old_ids<=new_ids:
                raise ValueError('Falta una identidad original.')
            for sid,digest,record in old.execute('SELECT source_id,content_hash,record FROM memory_sources'):
                row=current.execute('SELECT content_hash,record FROM memory_sources WHERE source_id=?',(sid,)).fetchone()
                if row==(digest,record):
                    preserved+=1
                elif current.execute('SELECT 1 FROM memory_history WHERE source_id=? AND content_hash=? AND record=?',
                                     (sid,digest,record)).fetchone():
                    archived+=1
                else:
                    missing+=1
            if missing:
                raise ValueError('Falta el snapshot de una fuente original.')
    sqlite_checks={}
    for path in (memory,index_path()):
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            quick=db.execute('PRAGMA quick_check').fetchone()[0]
            foreign=len(db.execute('PRAGMA foreign_key_check').fetchall())
            if quick!='ok' or foreign:
                raise ValueError('Integridad SQLite pendiente.')
            sqlite_checks[str(path)]={'quick_check':quick,'fk_errors':foreign,'bytes':path.stat().st_size}
    report={'sql_original_rows':sql,'original_work_ids_preserved':len(old_ids),
        'new_work_ids':len(new_ids-old_ids),'original_sources_active_unchanged':preserved,
        'original_sources_exactly_archived':archived,'original_sources_missing':missing,
        'sqlite':sqlite_checks,'coverage':narrative_coverage(),
        'env_sha256':hashlib.sha256(Path('.env').read_bytes()).hexdigest(),
        'free_disk_before_backup':shutil.disk_usage(folder).free}
    create_backup(final_backup)
    verified=verify_backup(final_backup)
    report.update(final_backup=str(final_backup),backup_complete=verified.get('complete'),
        backup_tables=len(verified['database']['tables']),
        backup_rows=sum(t['count'] for t in verified['database']['tables'].values()),
        free_disk_after_backup=shutil.disk_usage(folder).free)
    save_new(folder/'final_integrity.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in {'coverage','sql_original_rows','sqlite'}}),flush=True)


def evaluate(folder, identifiers, offline=False,research_name='research'):
    from django.conf import settings
    from django.test import override_settings
    from core.bibliographic_http_probe import run_conversation
    from core.literary_enrichment import narrative_coverage
    frozen = json.loads((folder/'frozen.json').read_text(encoding='utf-8'))
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,30}',research_name):
        raise ValueError('Nombre de perfil local inválido.')
    private = folder/research_name
    private.mkdir(exist_ok=True)
    memory = private/'memory.sqlite3'
    if not memory.exists():
        sqlite_snapshot(folder/'initial_memory.sqlite3',memory)
    overrides = {'LITMATE_LITERARY_MEMORY_DB':memory}
    for key in (*STORES[1:], 'LITMATE_AI_RUNTIME_DB','LITMATE_AI_STREAM_DB','LITMATE_AI_ANSWER_CACHE_DB'):
        # Existing public library/knowledge stores remain readable, isolated copies.
        target = private/(key.lower()+'.sqlite3')
        original = getattr(settings,key,'')
        if key in STORES and not target.exists() and original and Path(original).is_file():
            sqlite_snapshot(Path(original),target)
        overrides[key] = target
    original_counts=sql_counts()
    if offline:
        # Prove evidence reuse in a new session, not merely exact-answer replay.
        overrides['LITMATE_AI_ANSWER_CACHE_DB']=private/f'offline_answers_{time.monotonic_ns()}.sqlite3'
        # SearXNG is localhost, but its container can still reach the Internet.
        # Blocking only public sockets in this Python process is insufficient.
        overrides.update(LITMATE_AI_USE_WEB=False,LITMATE_AI_USE_SEARXNG=False,
            LITMATE_AI_USE_OPENLIBRARY=False,LITMATE_AI_USE_WIKIDATA=False,
            LITMATE_USE_GOOGLE_BOOKS_API=False)
    with override_settings(**overrides), ExitStack() as stack:
        from core import ai_narrative_answers as narrative
        original_retrieve,original_synthesize=narrative.retrieve_sources,narrative.synthesize_answer
        traces=[]
        def retrieved(*args,**kwargs):
            value=original_retrieve(*args,**kwargs)
            traces.append({'stage':'retrieved_public_evidence','sources':value})
            return value
        def synthesized(*args,**kwargs):
            traces.append({'stage':'generation_sources','sources':args[2]})
            kwargs['trace']=lambda stage,value:traces.append({'stage':stage,'output':value})
            return original_synthesize(*args,**kwargs)
        stack.enter_context(patch.object(narrative,'retrieve_sources',side_effect=retrieved))
        stack.enter_context(patch.object(narrative,'synthesize_answer',side_effect=synthesized))
        if offline:
            original_connect, original_resolve = socket.socket.connect, socket.getaddrinfo
            local={'127.0.0.1','::1','localhost'}
            def connect(sock,address):
                if not isinstance(address,tuple) or address[0] not in local:
                    raise OSError('offline_campaign_public_network_disabled')
                return original_connect(sock,address)
            def resolve(host,*args,**kwargs):
                if host not in local:
                    raise OSError('offline_campaign_public_network_disabled')
                return original_resolve(host,*args,**kwargs)
            stack.enter_context(patch.object(socket.socket,'connect',connect))
            stack.enter_context(patch.object(socket,'getaddrinfo',resolve))
        for identifier in identifiers:
            traces.clear()
            case=frozen['cases'][identifier-1]
            suffix='offline' if offline else 'online'
            existing=list(folder.glob(f'case_{identifier:02}_{suffix}_*.json'))
            output=folder/f'case_{identifier:02}_{suffix}_{len(existing)+1}.json'
            question = ('Explica el contenido de ' if case['kind']=='no_ficcion' else 'Dime la trama de ')+case['title']+' de '+case['author']
            before=narrative_coverage(database=memory)
            started=time.monotonic()
            turns=run_conversation([question])
            # Strip the full-catalog per_work map from each checkpoint.
            after=narrative_coverage(database=memory)
            report={'case':case,'offline':offline,'turns':turns,'seconds':round(time.monotonic()-started,3),
                'research_profile':research_name,
                'offline_guard_version':2 if offline else None,
                'public_research_trace':traces,
                'coverage_before':{k:v for k,v in before.items() if k!='per_work'},
                'coverage_after':{k:v for k,v in after.items() if k!='per_work'},
                'mysql_counts_unchanged':sql_counts()==original_counts,
                'knowledge_scope':'isolated persistent research copy; not global ingestion',
                'answer_cache_mode':'new_empty_store' if offline else 'persistent_exact_cache',
                'google_books_enabled':bool(settings.LITMATE_USE_GOOGLE_BOOKS_API),
                'factual_review_pending':True}
            save_new(output,report)
            print(json.dumps({'case':identifier,'offline':offline,**{key:turns[0].get(key) for key in
                ('status','seconds','answer')}},ensure_ascii=True),flush=True)


def enrich(folder, maximum, backup, candidates=None):
    """Bounded public work selection; existing worker owns storage and retries."""
    from core import literary_memory as memory
    from core.continuous_knowledge import run_continuous_batch
    from core.literary_enrichment import narrative_coverage
    from core.ai_narrative_answers import work_type
    from core.database_transfer import verify_backup
    from scripts.knowledge.continuous_worker import verify_additive_sql
    from core.literary_identity import normalize_identity
    if not 20 <= maximum <= 100:
        raise ValueError('La campaña admite entre 20 y 100 candidatas; cada trabajo conserva sus límites.')
    manifest=verify_backup(backup)
    verify_additive_sql(backup,manifest)
    plan_path=folder/'enrichment_plan.json'
    if not plan_path.exists():
        # Evaluation identities stay out of the pilot, including known controls.
        frozen_path=folder/'frozen.json'
        if not frozen_path.is_file() and candidates:
            frozen_path=folder.parent/'frozen.json'
        frozen=json.loads(frozen_path.read_text(encoding='utf-8'))
        excluded={normalize_identity(c['title']) for c in frozen['cases']}
        with memory._connection() as db:
            works=[json.loads(r['record']) for r in db.execute('SELECT record FROM memory_works ORDER BY work_id')]
        # Dataset selection, not production book-specific answering rules.
        preferred=('Dracula','Siddhartha','The Time Machine','Little Women','Naruto',
            'Hamlet','Pride and Prejudice','Cuentos de Amor de Locura y de Muerte',
            'The Renaissance: Studies in Art and Poetry','The Prince','The Republic',
            'A Defence of Poetry and Other Essays','Don Quijote','The Art of War',
            'Moby-Dick; or, The Whale','The Secret Garden','The Souls of Black Folk',
            'The Origin of Species','The Communist Manifesto','Meditations',
            'A princess of Mars','The Yellow Wallpaper','The Metamorphosis')
        works=[w for w in works if normalize_identity(w.get('title')) not in excluded]
        if candidates:
            requested=json.loads(candidates.read_text(encoding='utf-8'))
            identifiers=list(dict.fromkeys(w['work_id'] for w in requested))
            if not 20<=len(identifiers)<=100:
                raise ValueError('El corpus explícito debe contener entre 20 y 100 obras existentes.')
            works=[memory.get_work(identifier) for identifier in identifiers]
            if any(not w or normalize_identity(w['title']) in excluded for w in works):
                raise ValueError('Identidad desconocida o reservada para evaluación.')
        selected=works if candidates else candidate_selection(works,memory.usage_stats(),preferred=preferred)
        coverage=narrative_coverage(work_ids=[w['work_id'] for w in selected])
        save_new(plan_path,{'works':selected,'baseline':coverage,
            'selection':'explicit reviewed public corpus' if candidates else 'evaluation exclusions; demand; reader languages; wider coverage slot; author cap',
            'maximum':100,'no_factual_claim_from_selection':True})
        sqlite_snapshot(memory.default_path(),folder/'pre_enrichment_memory.sqlite3')
    plan=json.loads(plan_path.read_text(encoding='utf-8'))
    for i,work in enumerate(plan['works'][:maximum]):
        output=folder/f'enrichment_{i+1:03}.json'
        if output.exists():
            continue
        before=narrative_coverage(work_ids=[work['work_id']])
        detail=before['per_work'][work['work_id']]
        kind=work_type([work])
        requirement=('themes' if kind=='nonfiction' else
            'summary' if not detail['synopsis'] else
            'characters' if not detail['roles'] else
            'plot_development' if not detail['development_excerpt'] else 'relationships')
        batch=run_continuous_batch(maximum=1,work_ids=[work['work_id']],max_jobs=1,
            max_seconds=20,job_seconds=10,pause_seconds=1,reindex=False,project_mysql=False,
            max_rss_mb=768,requirements=(requirement,))
        after=narrative_coverage(work_ids=[work['work_id']])
        save_new(output,{'position':i+1,'work':work,'kind':kind,'requirement':requirement,
            'before':before,'batch':batch,'after':after,
            'coverage_changed':before!=after,'sql_projection':'existing evidence pointers; not copied prose'})
        print(json.dumps({'position':i+1,'title':work['title'],'requirement':requirement,
            'coverage_changed':before!=after,'batch':batch.get('batch',{})},ensure_ascii=True),flush=True)
        if batch.get('stopped') in {'free_disk','process_rss','stop_file','another_worker'}:
            break
        time.sleep(1)
    # Incremental existing index, bounded, no model inference or new datastore.
    from core.literary_memory_rag import build_memory_index,index_path
    result={'coverage':narrative_coverage(work_ids=[w['work_id'] for w in plan['works'][:maximum]]),
        'sql_integrity':verify_additive_sql(backup,manifest),
        'index':build_memory_index(maximum=500,max_seconds=30),
        'free_disk_bytes':shutil.disk_usage(folder).free,'maximum_requested':maximum}
    save_new(folder/f'enrichment_summary_{maximum}_{time.monotonic_ns()}.json',result)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('freeze','evaluate','enrich','review-absence','project','ingest-public','finalize'))
    parser.add_argument('--folder',type=Path,required=True)
    parser.add_argument('--case',type=int,action='append',choices=range(1,len(CASES)+1))
    parser.add_argument('--offline',action='store_true')
    parser.add_argument('--research-name',default='research',help='Perfil aislado nuevo para comparación fría con el mismo snapshot inicial.')
    parser.add_argument('--maximum',type=int,default=20)
    parser.add_argument('--backup',type=Path,default=Path('backups/volcados_20261030_03'))
    parser.add_argument('--candidates',type=Path,help='Corpus público revisado de identidades ya existentes; no importa hechos.')
    parser.add_argument('--final-backup',type=Path,help='Punto de recuperación nuevo; nunca se sobrescribe.')
    args=parser.parse_args()
    args.folder.mkdir(parents=True,exist_ok=True)
    from iniciar_mysql_local import local_database_environment
    password=getpass.getpass('Contraseña MySQL local (oculta): ')
    with local_database_environment(password,development_http=True):
        password=None
        os.environ.setdefault('DJANGO_SETTINGS_MODULE','litmate_project.settings')
        import django
        django.setup()
        if args.mode=='freeze':
            freeze(args.folder)
        elif args.mode=='evaluate':
            evaluate(args.folder,args.case or range(1,len(CASES)+1),args.offline,args.research_name)
        elif args.mode=='review-absence':
            review_absence(args.folder,args.backup)
        elif args.mode=='project':
            project(args.folder,args.backup)
        elif args.mode=='ingest-public':
            if not args.case:
                raise ValueError('Selecciona explícitamente un caso público revisado.')
            ingest_public_case(args.folder,args.case)
        elif args.mode=='finalize':
            if not args.final_backup:
                raise ValueError('Falta una ruta nueva para el respaldo final.')
            finalize(args.folder,args.backup,args.final_backup)
        else:
            enrich(args.folder,args.maximum,args.backup,args.candidates)


if __name__=='__main__':
    main()
