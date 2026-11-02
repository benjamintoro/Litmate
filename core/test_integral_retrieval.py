"""General conversation regressions; synthetic works, no shared stores or network."""
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
from django.test import SimpleTestCase, override_settings
from .test_narrative_answers import BOOK, PAGE, history


class IntegralRetrievalTests(SimpleTestCase):
    def test_relationship_enrichment_rechecks_an_existing_bound_profile(self):
        from .literary_memory import remember_evidence
        from .literary_learning import _fetch_public_metadata, _covers_requirement
        profile = self.profile()
        profile['attribution'] = {**PAGE['attribution'],'title':profile['title'],'url':profile['url']}
        with TemporaryDirectory() as temporary, override_settings(
                LITMATE_LITERARY_MEMORY_DB=Path(temporary)/'memory.sqlite3'):
            remember_evidence([BOOK],[profile])
            with patch('core.literary_search.search_wikipedia',side_effect=lambda q:[profile] if q==profile['title'] else [PAGE]) as search:
                sources = _fetch_public_metadata(BOOK,'wikipedia',requirement='relationships')
            self.assertGreater(search.call_count,1)
            self.assertTrue(any(any(f.get('relation')=='creador' for f in source.get('literary_facts',[])) for source in sources))
            self.assertTrue(_covers_requirement(BOOK,[BOOK],sources,'relationships'))

    def test_model_request_counters_survive_different_clients_and_scopes(self):
        from .ai_progress import progress_scope, record_model_call, snapshot_metrics, merge_metrics
        with progress_scope():
            record_model_call(); record_model_call()
            first = snapshot_metrics()
        with progress_scope():
            record_model_call()
            second = snapshot_metrics()
        self.assertEqual(merge_metrics(first,second)['model_calls_started'],3)

    def test_catalogue_topics_are_not_a_plot_even_with_an_identity_prefix(self):
        from .ai_quick_answers import quick_answer
        from .books_google import source_synopsis
        source = {**BOOK,'policy':'gutenberg-catalog-public-domain-v1',
                  'description':'Cuaderno lunar, de Ana Robles. Temas del catálogo: Space -- Fiction.'}
        self.assertIsNone(quick_answer('Dime la trama de Cuaderno lunar.',history(),search=lambda q:[source]))
        self.assertEqual(source_synopsis(source),'')

    def test_prepended_story_is_not_the_plot_of_the_main_novel(self):
        from .ai_narrative_answers import _task_content
        from .literary_search import relevant_passage
        prefix = ('== Argumento ==\nEn algunas ediciones, la novela va precedida del cuento El umbral. '
                  'En él, Celia viaja sola por un bosque durante una noche de tormenta.\n')
        main = 'La novela comienza con Bruno en la estación lunar. Su objetivo es rescatar a su hermana.'
        self.assertFalse(_task_content({'task':'summary'},{**PAGE,'description':prefix}))
        text = relevant_passage(prefix+main,'"Cuaderno lunar" argumento')
        self.assertIn('Bruno',text)
        self.assertNotIn('El umbral',text)

    def test_verified_web_work_survives_a_new_retrieval_without_catalogue_card(self):
        from .ai_persistent_router import persist_sources
        from .literary_memory import retrieve_evidence
        with TemporaryDirectory() as temporary, override_settings(
                LITMATE_LITERARY_MEMORY_DB=Path(temporary)/'memory.sqlite3'):
            saved = persist_sources([PAGE])
            self.assertGreater(saved.get('sources',0),0)
            books, sources = retrieve_evidence(BOOK['title'],requirement='summary')
            self.assertTrue(sources)
            self.assertTrue(any('estación lunar' in source['description'] for source in sources))
            self.assertTrue(all(source.get('memory_verified') for source in sources))

    def test_cached_catalogue_anchor_does_not_discard_new_character_profile(self):
        from .ai_persistent_router import persist_sources
        from .literary_memory import retrieve_evidence
        with TemporaryDirectory() as temporary, override_settings(
                LITMATE_LITERARY_MEMORY_DB=Path(temporary)/'memory.sqlite3'):
            profile = self.profile()
            profile['attribution'] = {**PAGE['attribution'], 'title':profile['title'], 'url':profile['url']}
            saved = persist_sources([{**BOOK,'memory_verified':True}, profile])
            self.assertGreater(saved.get('sources',0),0)
            unused, sources = retrieve_evidence(BOOK['title'], requirement='relationships')
            self.assertTrue(any(source.get('literary_facts') for source in sources))

    def test_coverage_counts_explicit_main_character_as_well_as_protagonist(self):
        from .ai_persistent_router import persist_sources
        from .literary_enrichment import narrative_coverage
        text = 'Celia es el personaje principal de la novela Cuaderno lunar, escrita por Ana Robles.'
        page = {**PAGE, 'title':'Celia', 'description':text, 'identity_text':text,
                'url':'https://es.wikipedia.org/wiki/Celia',
                'attribution':{**PAGE['attribution'],'title':'Celia','url':'https://es.wikipedia.org/wiki/Celia'}}
        with TemporaryDirectory() as temporary, override_settings(
                LITMATE_LITERARY_MEMORY_DB=Path(temporary)/'memory.sqlite3'):
            persist_sources([BOOK,page])
            self.assertEqual(narrative_coverage()['works_with_explicit_protagonist'],1)

    def test_summary_keeps_whole_story_overview_after_opening_details(self):
        from .ai_narrative_answers import _sentences
        source = {**PAGE, 'description':'== Argumento == '
            'Celia busca una ciudad perdida con su hermano Bruno. '
            'La mañana de su partida prepara cuidadosamente su equipaje. '
            'Su madre le entrega un mapa antiguo antes de salir. '
            'El viaje comienza con una larga caminata por las montañas. '
            'Bruno encuentra un refugio donde descansan durante la noche. '
            'La historia principal sigue el crecimiento de Celia y sus amigos durante la búsqueda. '
            'Conforme transcurre la historia, Celia se relaciona con otros viajeros que la ayudan.'}
        lines = _sentences(source)
        self.assertLessEqual(len(lines),5)
        self.assertTrue(any('crecimiento' in line for line in lines))
        self.assertTrue(any('otros viajeros' in line for line in lines))

    def profile(self):
        return {**PAGE, 'title':'Autómata de Cuaderno lunar', 'url':'https://es.wikipedia.org/wiki/Automata_lunar',
            'work_title':BOOK['title'],'work_author':BOOK['author'],'work_binding_verified':True,
            'identity_text':'El autómata de Cuaderno lunar es un personaje de la novela Cuaderno lunar, de Ana Robles.',
            'description':'El autómata de Cuaderno lunar es un personaje de la novela Cuaderno lunar, de Ana Robles. '
            'Se trata de un ser construido con piezas diversas, al cual le es otorgada la vida por su creador, '
            'Bruno Salas, durante un experimento.'}

    def test_profile_relation_and_published_designation_answer_without_a_model(self):
        from .ai_character_answers import answer_from_sources, request_for
        story = {**PAGE, 'description':'== Argumento == El autómata, de cuya creación no se dan detalles, '
            'carece de nombre y es referido como "criatura" o "guardián".'}
        question = '¿Qué relación tiene Bruno Salas con la criatura?'
        result = answer_from_sources(question, request_for(question, history()), [BOOK, story, self.profile()])
        self.assertIsNotNone(result)
        self.assertIn('Bruno Salas', result.text)
        self.assertIn('vida', result.text)
        self.assertTrue(result.diagnostics.get('verified_relationship_answer'))
        self.assertEqual(result.diagnostics['character_count'], 2)

    def test_partial_creator_name_is_resolved_only_if_unique_in_the_work(self):
        from .ai_character_answers import answer_from_sources, request_for
        story = {**PAGE, 'description':'== Argumento == El autómata, de cuya creación no se dan detalles, '
            'carece de nombre y es referido como "criatura" o "guardián".'}
        question = '¿Qué relación tiene Bruno con la criatura?'
        request = request_for(question, history())
        result = answer_from_sources(question, request, [BOOK, story, self.profile()])
        self.assertIsNotNone(result)
        self.assertIn('Bruno Salas', result.text)
        another = {**PAGE, 'description':'Bruno Márquez: es el barquero de la estación.',
                   'character_facts':[{'name':'Bruno Márquez','role':'es el barquero de la estación.'}]}
        self.assertIsNone(answer_from_sources(question, request, [BOOK, story, self.profile(), another]))

    def test_relation_keeps_published_designation_when_many_character_snapshots_precede_it(self):
        from .ai_character_answers import answer_from_sources, request_for
        noise=[{**PAGE,'url':PAGE['url']+'?snapshot='+str(i),
                'description':'Elena: es la capitana de la nave.',
                'character_facts':[{'name':'Elena','role':'es la capitana de la nave.'}]} for i in range(10)]
        story={**PAGE,'description':'== Argumento == El autómata, de cuya creación no se dan detalles, '
               'carece de nombre y es referido como "criatura" o "guardián".'}
        question='¿Qué relación tiene Bruno con la criatura?'
        result=answer_from_sources(question,request_for(question,history()),[BOOK,*noise,self.profile(),story])
        self.assertIsNotNone(result)
        self.assertIn('Bruno Salas',result.text)

    def test_epic_profile_with_zero_subject_and_plural_heroes_is_bound(self):
        from .ai_character_answers import bind_character_profile, answer_from_sources, request_for
        text = ('Ión o Ionio (nombre antiguo) fue uno de los héroes legendarios de la mitología griega. '
                'Aparece especialmente como protagonista epónimo de Cuaderno lunar pero también es un '
                'personaje destacado de Otra obra, ambas obras atribuidas a Ana Robles.')
        page = {**PAGE, 'title':'Ión', 'description':text, 'identity_text':text,
                'url':'https://es.wikipedia.org/wiki/Ion'}
        bound = bind_character_profile(page, BOOK)
        self.assertIsNotNone(bound)
        question = '¿Quiénes son los personajes principales?'
        result = answer_from_sources(question, request_for(question, history()), [BOOK,bound])
        self.assertIsNotNone(result)
        self.assertIn('Ión',result.text)

    def test_author_creation_and_negative_experiment_are_not_story_creator_relations(self):
        from .literary_entity_facts import profile_creation_relations
        for text in ('Fue creado por la escritora Ana Robles en su novela.',
                     'Se trata de un ser que nunca recibe vida de su creador, Bruno Salas, durante un experimento.'):
            source = self.profile(); source['description'] = source['description'].split('. ')[0]+'. '+text
            self.assertEqual(profile_creation_relations(source), [])

    def test_profile_zero_subject_role_keeps_the_work_and_not_the_next_character(self):
        from .literary_entity_facts import profile_topic_facts
        source = {**self.profile(), 'title':'Ión', 'description':'Ión fue un héroe legendario. '
            'Aparece especialmente como protagonista de Cuaderno lunar pero también en Otra obra.'}
        facts = profile_topic_facts(source)
        self.assertEqual(len(facts), 1)
        self.assertNotIn('Otra obra', facts[0]['role'])
        source['description'] = 'Ión fue un héroe legendario. Bruno aparece como protagonista de Cuaderno lunar.'
        self.assertEqual(profile_topic_facts(source), [])
    def test_explicit_relationship_with_con_keeps_two_participants_and_active_work(self):
        from .ai_character_answers import request_for
        for question in ('¿Qué relación tiene Ana Robles con Bruno Salas?',
                         '¿Qué relación mantiene Ana Robles con la criatura?'):
            request = request_for(question, history())
            self.assertIsNotNone(request)
            self.assertEqual(request['task'], 'relationship')
            self.assertEqual(request['title'], BOOK['title'])
            self.assertEqual(len(request['names']), 2)

    def test_structural_api_keeps_every_returned_character_proof_in_its_passage(self):
        from .literary_search import _search_wikipedia
        intro = 'Cuaderno lunar es un poema épico de Ana Robles. Narra el regreso del héroe marino Ión.'
        article = {'pageid':42, 'title':BOOK['title'], 'extract':intro, 'fullurl':PAGE['url']}
        responses = [
            {'query':{'pages':{'42':article}}},
            {'query':{'pages':{'42':{**article,'extract':'== Argumento ==\nIón vuelve a casa.'}}}},
            {'parse':{'pageid':42,'title':BOOK['title'],'revid':123,
                'text':{'*':'<p>Narra el regreso del héroe marino <a href="/wiki/Ion">Ión</a>.</p>'
                    '<h2>Argumento</h2><p><a href="/wiki/Celia">Celia</a>, la reina de la isla, ayuda al viajero.</p>'
                    '<p><a href="/wiki/Bruno">Bruno</a>, el capitán de la nave, protege la entrada.</p>'}}}]
        with patch('core.literary_search._wikipedia_fetch', side_effect=responses), \
                patch('core.literary_search.reserve_page', return_value=True):
            found = _search_wikipedia('"Cuaderno lunar" personajes')
        self.assertTrue(found)
        self.assertIn('Ión', [fact['name'] for fact in found[0]['character_facts']])
        for fact in found[0]['character_facts']:
            self.assertIn(fact['evidence'], found[0]['description'])

    def test_article_variation_is_only_a_search_candidate_not_a_stored_alias(self):
        from .literary_search import _search_wikipedia
        page = {'pageid':42,'title':'Travesía','extract':'La Travesía es un poema épico de Ana Robles. '
            'Narra la historia de una viajera que busca a su familia.', 'fullurl':'https://es.wikipedia.org/wiki/Travesia'}
        replies = [{'query':{}}, {'query':{'pages':{'42':page}}},
                   {'query':{'pages':{'42':{**page,'extract':'== Argumento ==\nAna viaja para buscar a su familia.'}}}}]
        with patch('core.literary_search._wikipedia_fetch', side_effect=replies) as fetch, \
                patch('core.literary_search.reserve_page', return_value=True):
            found = _search_wikipedia('"La Travesía" argumento')
        self.assertTrue(found)
        self.assertEqual(found[0]['title'], 'Travesía')
        self.assertFalse(found[0].get('confirmed_aliases'))
