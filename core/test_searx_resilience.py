"""Fallas simuladas en SQLite temporal; ninguna consulta a buscadores."""
from pathlib import Path
from contextlib import closing
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs
from django.core.cache import cache
from django.test import SimpleTestCase,override_settings


@override_settings(CACHES={'default':{'BACKEND':'django.core.cache.backends.locmem.LocMemCache'}},
    LITMATE_AI_LOCK_BACKEND='sqlite',LITMATE_AI_USE_SEARXNG=True,LITMATE_AI_USE_WEB=True,
    LITMATE_SEARXNG_URL='http://127.0.0.1:8080',LITMATE_SEARXNG_WEB_ENGINES=('mwmbl','duckduckgo'),
    LITMATE_SEARXNG_ENGINES=('mwmbl',))
class SearxResilienceTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.folder=TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.runtime=Path(self.folder.name)/'runtime.sqlite3'
        self.override=override_settings(LITMATE_AI_RUNTIME_DB=self.runtime)
        self.override.enable();self.addCleanup(self.override.disable)

    def test_captcha_survives_cache_loss_and_does_not_block_other_engines(self):
        from .literary_search import search_searx,search_duckduckgo
        payload={'results':[{'title':'Una novela','url':'https://www.penguinlibros.com/es/novela',
                             'content':'Una descripción.','engines':['mwmbl']}],
                 'unresponsive_engines':[['duckduckgo','CAPTCHA (suspended_time=0)']]}
        with patch('core.literary_search.read_json_url',return_value=payload) as fetch:
            first=search_searx('Una novela',web=True)
            self.assertEqual(first.status,'partial')
            cache.clear()  # Simula perder LocMemCache o utilizar otro proceso.
            second=search_searx('Otra novela',web=True)
        self.assertEqual(len(second),1)
        self.assertEqual(parse_qs(urlsplit(fetch.call_args.args[0]).query)['engines'],['mwmbl'])
        with patch('core.literary_search.read_public_html',create=True) as html:
            self.assertEqual(search_duckduckgo('Una novela diferente').status,'cooldown')
        html.assert_not_called()

    def test_blocked_general_engine_can_use_the_configured_bibliographic_engines(self):
        from .literary_search import search_searx
        from .ai_concurrency import pause_provider
        pause_provider('litmate_ddg_cooldown',3600)
        with override_settings(LITMATE_SEARXNG_ENGINES=('wikipedia','openlibrary','mwmbl')), \
                patch('core.literary_search.read_json_url',return_value={'results':[],'unresponsive_engines':[]}) as fetch:
            search_searx('Una novela',web=True)
        engines=set(parse_qs(urlsplit(fetch.call_args.args[0]).query)['engines'][0].split(','))
        self.assertEqual(engines,{'mwmbl','wikipedia','openlibrary'})

    def test_pause_is_visible_in_a_new_process_and_expires_without_touching_work_leases(self):
        import subprocess,sys,time
        from .ai_concurrency import pause_provider,pause_active,acquire
        self.assertTrue(acquire('work-lease','worker-token',120))
        pause_provider('provider-control',3600)
        pause_provider('provider-control',10)  # No acortar la pausa fuerte.
        code=('from django.conf import settings;import sys;'
              'settings.configure(BASE_DIR=sys.argv[1],LITMATE_AI_LOCK_BACKEND="sqlite",'
              'LITMATE_AI_RUNTIME_DB=sys.argv[2]);'
              'from core.ai_concurrency import pause_active;print(pause_active("provider-control"))')
        result=subprocess.run([sys.executable,'-B','-c',code,self.folder.name,str(self.runtime)],
                              capture_output=True,text=True,timeout=10,check=True)
        self.assertEqual(result.stdout.strip(),'True')
        now=time.time()
        with patch('core.ai_concurrency.time.time',return_value=now+20):
            self.assertTrue(pause_active('provider-control'))
        with patch('core.ai_concurrency.time.time',return_value=now+3601):
            self.assertFalse(pause_active('provider-control'))
        import sqlite3
        with closing(sqlite3.connect(self.runtime)) as db:
            self.assertEqual(db.execute('SELECT owner FROM leases WHERE key=?',('work-lease',)).fetchone()[0],
                             'worker-token')

    def test_missing_search_provenance_does_not_grant_general_page_reading(self):
        from .literary_ai import canonical_sources
        source={'kind':'web','title':'Un resultado','url':'https://example.org/book',
                'source':'SearXNG (example.org)','search_engines':['invented','wikipedia',{}]}
        self.assertEqual(canonical_sources([source])[0]['search_engines'],['wikipedia'])

    def test_irrelevant_first_hits_do_not_hide_a_relevant_readable_page(self):
        from .literary_search import search_searx
        irrelevant=[{'title':'Noticias de otro tema','url':f'https://example.org/{i}',
                     'content':'Un resultado ajeno al libro.','engines':['mwmbl']} for i in range(5)]
        catalog=[{'title':'Cuaderno lunar','url':f'https://openlibrary.org/works/OL{i}W',
                  'content':'','engines':['openlibrary']} for i in range(100,105)]
        page={'title':'Cuaderno lunar - Editorial','url':'https://example.org/cuaderno-lunar',
              'content':'Cuaderno lunar es una novela de Ana Robles sobre una expedición.','engines':['mwmbl']}
        with patch('core.literary_search.read_json_url',return_value={
                'results':[*irrelevant,*catalog,page],'unresponsive_engines':[]}):
            found=search_searx('Cuaderno lunar',web=True)
        self.assertTrue(any(s['url']==page['url'] for s in found))
        self.assertLessEqual(sum('openlibrary.org' in s['url'] for s in found),2)

    def test_general_searx_results_still_reject_private_targets_and_unsafe_schemes(self):
        from .literary_search import search_searx
        urls=['https://127.0.0.1/admin','https://10.0.0.1/secret','https://localhost/admin',
              'http://example.org/book','file:///etc/passwd','https://user:secret@example.org/book']
        with patch('core.literary_search.read_json_url',return_value={
                'results':[{'title':'Una novela','url':u,'content':'','engines':['mwmbl']} for u in urls],
                'unresponsive_engines':[]}):
            self.assertEqual(search_searx('Una novela',web=True),[])

    def test_catalogue_links_do_not_exhaust_the_public_page_budget(self):
        from .literary_search import _retrieve_web
        from .literary_sources import SearchResults,research_scope
        sources=[{'title':'Cuaderno lunar','author':'Fuente web','kind':'web','description':'Ficha',
                  'source':'SearXNG (openlibrary.org)','search_engines':['openlibrary'],
                  'url':f'https://openlibrary.org/works/OL{i}W','read_mode':'fragmento del buscador'}
                 for i in range(100,103)]
        sources.append({**sources[0],'url':'https://literatura.example/book',
            'source':'SearXNG (literatura.example)','search_engines':['mwmbl']})
        with research_scope(pages=1),patch('core.literary_search.search_wikipedia',return_value=[]), \
                patch('core.literary_search.search_duckduckgo',return_value=[]), \
                patch('core.literary_search.search_searx',return_value=SearchResults(sources)), \
                patch('core.literary_search.read_public_web_page',return_value={'status':'ok',
                    'description':'Cuaderno lunar narra una expedición científica.'}) as read:
            found=_retrieve_web('Cuaderno lunar')
        read.assert_called_once()
        self.assertTrue(any(s['read_mode']=='pasaje de página pública' for s in found))

    def test_general_searx_hit_reaches_the_same_safe_reader_as_other_discovery(self):
        from .literary_search import _retrieve_web
        from .literary_sources import SearchResults,research_scope
        source={'kind':'web','title':'Cuaderno lunar','author':'Fuente web',
                'url':'https://literatura.example/novela','description':'Un fragmento del buscador.',
                'source':'SearXNG (literatura.example)','search_engines':['mwmbl'],
                'read_mode':'fragmento del buscador'}
        page={'status':'ok','description':'Cuaderno lunar es una novela de Ana Robles sobre una expedición.',
              'identity_text':'Cuaderno lunar, novela de Ana Robles.','title':'Cuaderno lunar',
              'injection_detected':False}
        with research_scope(),patch('core.literary_search.search_wikipedia',return_value=[]), \
                patch('core.literary_search.search_duckduckgo',return_value=[]), \
                patch('core.literary_search.search_searx',return_value=SearchResults([source])), \
                patch('core.literary_search.read_public_web_page',return_value=page) as read:
            found=_retrieve_web('Cuaderno lunar Ana Robles')
        read.assert_called_once()
        self.assertEqual(found[0]['read_mode'],'pasaje de página pública')
        self.assertIn('expedición',found[0]['description'])

