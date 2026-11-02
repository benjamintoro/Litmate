"""Regresiones generales: cobertura temática, aislamiento y métricas SSE."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from django.test import SimpleTestCase
from unittest.mock import patch
from .test_narrative_answers import BOOK, PAGE


class KnowledgeCoverageTests(SimpleTestCase):
    def test_interlanguage_alias_keeps_a_full_title_literally_published_in_the_original_lead(self):
        from .literary_search import _wikipedia_spanish_counterpart,_wikipedia_storage_metadata
        from .literary_identity import published_title_alias
        from .literary_sources import research_scope
        full='Lunar Notebook; or, The Return'
        english={'pageid':15,'title':'Lunar Notebook','extract':full+' is an 1891 novel by Ana Robles.',
            'fullurl':'https://en.wikipedia.org/wiki/Lunar_Notebook','revisions':[{'revid':111}],
            'pageprops':{'wikibase_item':'Q123'},'langlinks':[{'lang':'es','*':'Cuaderno lunar'}]}
        spanish={'pageid':25,'title':'Cuaderno lunar','extract':'Cuaderno lunar es una novela de Ana Robles.\n'
            '== Argumento ==\nAna viaja a una estación lunar para buscar a su hermano.',
            'fullurl':PAGE['url'],'revisions':[{'revid':222}],'pageprops':{'wikibase_item':'Q123'}}
        for requested,expected in [(full,True),('Lunar Notebook and the Stars',False)]:
            with research_scope(2,10,3),patch('core.literary_search._wikipedia_fetch',return_value={'query':{'pages':{'25':spanish}}}):
                found=_wikipedia_spanish_counterpart(english,query='"'+requested+'" Ana Robles argumento')
            source={**PAGE,**_wikipedia_storage_metadata(found),'identity_text':spanish['extract'],
                    'confirmed_aliases':found['confirmed_aliases']}
            self.assertEqual(published_title_alias(source,requested),expected)

    def test_http_probe_copies_the_default_memory_index_and_other_public_stores(self):
        from types import SimpleNamespace
        from contextlib import closing
        import sqlite3
        from scripts.knowledge.search_narrative_check import isolate_retrieval_stores
        with TemporaryDirectory() as directory:
            base=Path(directory)
            source=base/'data'/'literary_memory_rag.sqlite3'
            source.parent.mkdir()
            with closing(sqlite3.connect(source)) as db,db:
                db.execute('CREATE TABLE probe_data(value TEXT)')
                db.execute("INSERT INTO probe_data VALUES('original')")
            temporary=base/'probe';temporary.mkdir()
            overrides,originals=isolate_retrieval_stores(SimpleNamespace(BASE_DIR=base),temporary)
            target=overrides['LITMATE_LITERARY_MEMORY_RAG_DB']
            self.assertNotEqual(source,target)
            self.assertIn('LITMATE_LITERARY_MEMORY_RAG_DB',originals)
            with closing(sqlite3.connect(target)) as db,db:
                db.execute("INSERT INTO probe_data VALUES('only_the_copy')")
            with closing(sqlite3.connect(source)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM probe_data').fetchone()[0],1)

    def test_article_in_reader_title_does_not_discard_verified_spanish_work(self):
        from .literary_search import search_wikipedia
        from django.core.cache import cache
        cache.clear()
        page={**PAGE,'identity_text':'El Cuaderno lunar (en lengua antigua: Luna) es una novela de Ana Robles.'}
        with patch('core.literary_search._search_wikipedia',side_effect=[
                [page],[{**PAGE,'title':'Una película distinta','description':'Otra historia.'}]]) as fetch:
            result=search_wikipedia('"El Cuaderno lunar" argumento')
        self.assertEqual(result[0]['url'],PAGE['url'])
        self.assertEqual(fetch.call_count,1)

    def test_unique_created_being_is_a_context_reference_not_a_global_alias(self):
        from .ai_character_answers import profile_relationship_answer
        from .literary_ai import canonical_sources
        first='El autómata de Aurora es un personaje de ficción de la novela Cuaderno lunar de Ana Robles.'
        second='Se trata de un ser al cual le es otorgada la vida por su creador, Clara Ríos, durante un experimento.'
        source={**PAGE,'title':'Autómata de Aurora','description':first+' '+second,
            'work_title':BOOK['title'],'work_author':BOOK['author'],'work_binding_verified':True}
        request={'task':'relationship','names':['Clara Ríos','la criatura'],'title':BOOK['title']}
        sources=canonical_sources([BOOK,source])
        result=profile_relationship_answer('¿Qué relación tiene Clara Ríos con la criatura?',request,sources)
        self.assertIsNotNone(result)
        self.assertIn('Clara Ríos es su creador',result.text)
        self.assertFalse(any(s.get('confirmed_aliases') for s in result.sources))
        other={**source,'title':'Ser de la estación','description':first.replace('autómata de Aurora','ser de la estación')+' '+second,
            'url':'https://es.wikipedia.org/wiki/Ser_de_la_estacion'}
        self.assertIsNone(profile_relationship_answer('¿Qué relación tiene Clara Ríos con la criatura?',request,
            canonical_sources([BOOK,source,other])))
        self.assertIsNone(profile_relationship_answer('¿Qué relación tiene Clara Ríos con Elena?',
            {**request,'names':['Clara Ríos','Elena']},sources))

    def test_a_translation_cannot_change_the_documented_kinship_gender(self):
        from .literary_quality import unsupported_kinship_claim
        self.assertTrue(unsupported_kinship_claim('Ana fue enviada a vivir con su tía.',
            'Ana was sent to live with her maternal uncle.'))
        self.assertTrue(unsupported_kinship_claim('Bruno vive con su tío.',
            'Bruno lives with his aunt.'))
        self.assertFalse(unsupported_kinship_claim('Ana fue enviada a vivir con su tío.',
            'Ana was sent to live with her maternal uncle.'))
        self.assertFalse(unsupported_kinship_claim('Ana visita a su tía.',
            'Ana visits her aunt and her uncle.'))

    def test_a_specific_kinship_requires_evidence_even_if_the_auditor_approves(self):
        from .literary_quality import unsupported_kinship_claim
        self.assertTrue(unsupported_kinship_claim('Ana fue enviada por su tía a otro país.',
            'After a cholera epidemic kills her parents, Ana is left alone.'))
        self.assertFalse(unsupported_kinship_claim('Ana vive con su tío.',
            "Ana lives with her mother's brother."))
        self.assertFalse(unsupported_kinship_claim('Ana vive con su tía.',
            'Ana lives with her aunt.'))

    def test_identity_author_is_not_the_magazine_named_after_the_byline(self):
        from .literary_identity import _identity_author
        for text in ("Lunar Notebook is a children's novel by Ana Robles first published in The Literary Magazine.",
                     'Cuaderno lunar es una novela escrita por Ana Robles publicada por Editorial Central.'):
            self.assertEqual(_identity_author({'identity_text':text}),'Ana Robles')
        self.assertEqual(_identity_author({'identity_text':
            'La novela es una obra del escritor Premio Nobel de Literatura Ana Robles.'}), '')

    def test_spanish_counterpart_without_plot_does_not_replace_english_evidence(self):
        from .literary_search import _wikipedia_spanish_counterpart
        from .literary_sources import research_scope
        english={'pageid':15,'title':'Lunar Notebook','extract':'Lunar Notebook is a novel by Ana Robles.',
            'fullurl':'https://en.wikipedia.org/wiki/Lunar_Notebook','revisions':[{'revid':111}],
            'pageprops':{'wikibase_item':'Q123'},'langlinks':[{'lang':'es','*':'Cuaderno lunar'}]}
        spanish={'pageid':25,'title':'Cuaderno lunar','extract':'Cuaderno lunar es una novela de Ana Robles.\n'
            '== Personajes ==\nAda: Es una joven astronauta que busca a su hermano.',
            'fullurl':PAGE['url'],'revisions':[{'revid':222}],'pageprops':{'wikibase_item':'Q123'}}
        with research_scope(2,10,3),patch('core.literary_search._wikipedia_fetch',return_value={'query':{'pages':{'25':spanish}}}):
            self.assertIsNone(_wikipedia_spanish_counterpart(english,query='"Lunar Notebook" Ana Robles argumento'))
        spanish['extract']+='\n== Argumento ==\nAda viaja a una estación lunar para encontrar a su hermano desaparecido.'
        with research_scope(2,10,3),patch('core.literary_search._wikipedia_fetch',return_value={'query':{'pages':{'25':spanish}}}):
            found=_wikipedia_spanish_counterpart(english,query='"Lunar Notebook" Ana Robles argumento')
            self.assertTrue(found['_prefetched_document'])

    def test_official_interlanguage_identity_can_reuse_the_spanish_article(self):
        from .literary_search import _wikipedia_spanish_counterpart
        from .literary_identity import published_title_alias,same_work
        english={'pageid':15,'title':'Lunar Notebook','extract':'Lunar Notebook is a novel by Ana Robles.',
            'fullurl':'https://en.wikipedia.org/wiki/Lunar_Notebook','revisions':[{'revid':111}],
            'pageprops':{'wikibase_item':'Q123'},'langlinks':[{'lang':'es','*':'Cuaderno lunar'}]}
        spanish={'pageid':25,'title':'Cuaderno lunar','extract':'Cuaderno lunar es una novela de Ana Robles.',
            'fullurl':PAGE['url'],'revisions':[{'revid':222}],'pageprops':{'wikibase_item':'Q123'}}
        with patch('core.literary_search._wikipedia_fetch',return_value={'query':{'pages':{'25':spanish}}}):
            found=_wikipedia_spanish_counterpart(english)
        self.assertEqual(found['title'],'Cuaderno lunar')
        from .literary_search import _wikipedia_storage_metadata
        source={**PAGE,**_wikipedia_storage_metadata(found),'identity_text':spanish['extract'],
                'confirmed_aliases':found['confirmed_aliases']}
        self.assertTrue(published_title_alias(source,'Lunar Notebook'))
        self.assertTrue(same_work(source,{**BOOK,'title':'Lunar Notebook'}))
        for altered in ({**spanish,'pageprops':{'wikibase_item':'Q456'}},
                        {**spanish,'extract':'Cuaderno lunar es una novela de Carlos Robles.'},
                        {**spanish,'extract':'Cuaderno lunar es una película basada en una novela de Ana Robles.'}):
            with patch('core.literary_search._wikipedia_fetch',return_value={'query':{'pages':{'25':altered}}}):
                self.assertIsNone(_wikipedia_spanish_counterpart(english))
        for link in ({'lang':'es','*':'http://127.0.0.1/admin'}, {'lang':'de','*':'Cuaderno lunar'}):
            with patch('core.literary_search._wikipedia_fetch') as fetch:
                self.assertIsNone(_wikipedia_spanish_counterpart({**english,'langlinks':[link]}))
                fetch.assert_not_called()

    def test_licensed_foreign_plot_can_use_literal_audit_before_existing_translation(self):
        from django.test import override_settings
        from .ai_narrative_answers import direct_answer,request_for
        page={**PAGE,'description':'== Plot summary == A girl arrives at a distant house to find her brother. '
            'After an epidemic kills her parents, she begins a new life in the countryside.'}
        with override_settings(LITMATE_AI_FOREIGN_LITERAL=True):
            result=direct_answer('Dime la trama de Cuaderno lunar',request_for('Dime la trama de Cuaderno lunar'),[BOOK,page])
        self.assertIsNotNone(result)
        self.assertTrue(result.diagnostics.get('foreign_literal_summary'))
        self.assertIn('kills her parents',result.text)
        for claim in result.diagnostics['audit']['claims']:
            self.assertEqual(claim['verdict'],'supported')
            self.assertIn(claim['evidence'],page['description'])

    def test_explicit_ending_does_not_use_the_default_no_spoiler_synopsis_route(self):
        from .ai_narrative_answers import request_for
        self.assertIsNone(request_for('¿Cómo termina Cuaderno lunar?'))

    def test_parent_death_evidence_does_not_support_a_child_orphaned_by_own_death(self):
        from .literary_quality import unsupported_orphanhood_claim
        proof='After an epidemic kills her parents, Lucia is sent to another country.'
        wrong='Lucía es una niña que vive en una ciudad hasta que su muerte la deja huérfana.'
        self.assertTrue(unsupported_orphanhood_claim(wrong,proof))
        correct='Lucía es una niña que queda huérfana después de la muerte de sus padres.'
        self.assertFalse(unsupported_orphanhood_claim(correct,proof))
        ambiguous='Lucía vive con su madre hasta que su muerte la deja huérfana.'
        self.assertFalse(unsupported_orphanhood_claim(ambiguous,proof))

    def test_a_summary_does_not_publish_an_unrequested_closing_sentence(self):
        from .ai_narrative_answers import summary_without_ending
        first='La novela narra el viaje de Ana para encontrar a su hermano.'
        draft={'text':first+' La trama culmina con la derrota del antagonista.','citations':[2]}
        filtered,count=summary_without_ending(draft)
        self.assertEqual(filtered['text'],first)
        self.assertEqual(filtered['citations'],[2])
        self.assertEqual(count,1)
        self.assertIn('culmina',draft['text'])

    def test_english_intro_conflict_reaches_the_auditor_alongside_plot_passage(self):
        from .ai_narrative_answers import bound_sources,request_for
        premise="The book centers on Ada's expedition to rescue her missing brother."
        page={**PAGE,'identity_text':'Cuaderno lunar is an 1891 novel by Ana Robles. '+premise,
              'description':'== Plot == Ada reaches a distant station and meets a group of travellers.'}
        found=bound_sources(request_for('Dime la trama de Cuaderno lunar'),[BOOK,page])
        source=next(s for s in found if s['kind']=='web')
        self.assertIn(premise,source.get('narrative_context',''))
        self.assertIn('distant station',source['description'])
        self.assertNotIn('1891',source['narrative_context'])

    def test_english_plot_summary_heading_selects_story_instead_of_publication_notes(self):
        from .literary_search import relevant_passage
        intro='A Garden is a novel published in 1901 by Ana Robles.'
        plot=('Alicia arrives at a distant house to search for a missing relative.\n'
              'She discovers a locked garden and investigates a mysterious sound in the house.\n'
              'A gardener helps her restore the abandoned grounds and understand the family.')
        selected=relevant_passage(intro+'\n== Plot summary ==\n'+plot+'\n== Reception ==\nCritics liked it.',
            '"A Garden" Ana Robles argumento',with_details=True)
        self.assertIn('Alicia arrives',selected['passage'])
        self.assertNotIn('published',selected['passage'])
        self.assertNotIn('Critics',selected['passage'])
        self.assertEqual(selected.get('topic'),'plot')

    def test_alternative_title_punctuation_is_not_another_request(self):
        from .ai_narrative_answers import request_for
        from .literary_ai import simple_literary_route
        message='Dime la trama de El jardín; o, El regreso del autor Ana Robles.'
        request=request_for(message)
        self.assertIsNotNone(request)
        self.assertEqual(request['title'],'El jardín; o, El regreso')
        self.assertEqual(request['author_hint'],'Ana Robles')
        self.assertEqual(simple_literary_route(message)['intent'],'summary')
        for compound in ('Dime la trama de El jardín; dime también sus personajes.',
                         'Dime la trama de El jardín; o, El regreso; resume otra obra.'):
            self.assertIsNone(request_for(compound))
            self.assertIsNone(simple_literary_route(compound))

    def test_a_plot_premise_is_not_a_cut_word_or_only_publication_metadata(self):
        from .literary_memory import _literal_facts
        for text in ('da como una película que recibió otro título durante la preproducción.',
                     'El libro es una novela de Ana Robles publicada por primera vez en 1901.'):
            fact={'topic':'plot','scope':'premise','evidence':text}
            self.assertEqual(_literal_facts([fact],text,'literary_facts'),[])
        text='Publicada en 1901, la novela narra el viaje de Ana para encontrar a su hermano.'
        fact={'topic':'plot','scope':'premise','evidence':text}
        self.assertEqual(len(_literal_facts([fact],text,'literary_facts')),1)

    def test_new_campaign_selection_does_not_fill_the_batch_with_short_titles(self):
        from scripts.knowledge.knowledge_campaign import candidate_selection
        works=[{**BOOK,'title':f'Identidad extensa {i}','author':f'Autora {i}',
                'work_id':f'long-{i}','language':'es'} for i in range(4)]
        works += [{**BOOK,'title':'字','author':'Otra Autora','work_id':'short','language':'zh'}]
        selected=candidate_selection(works,[],maximum=5)
        self.assertEqual([w['language'] for w in selected],['es','es','es','es','zh'])
        self.assertEqual(len({w['work_id'] for w in selected}),5)

    def test_thematic_section_is_not_labelled_as_a_plot_fact(self):
        from .literary_search import relevant_passage,selected_section_facts
        text='== Temas == La obra examina la organización política y el papel de las instituciones en la sociedad.'
        selection=relevant_passage(text,'"Atlas lunar" Ana Robles temas',with_details=True)
        facts=selected_section_facts(selection)
        self.assertEqual(facts[0]['topic'],'themes')
        self.assertIn(facts[0]['evidence'],text)
        intro=relevant_passage('Atlas lunar es un libro publicado en 1901 por Ana Robles.',
                              'Atlas lunar argumento',with_details=True)
        self.assertEqual(selected_section_facts(intro),[])

    def test_nonfiction_metadata_is_not_treated_as_fiction_or_unknown(self):
        from .ai_narrative_answers import work_type
        for category in ('Political science','Philosophy','Essays','Economics'):
            self.assertEqual(work_type([{**BOOK,'categories':[category]}]),'nonfiction')
        self.assertEqual(work_type([{**BOOK,'categories':['Science fiction']}]),'fiction')
        book={**BOOK,'categories':['Biography']}
        self.assertEqual(work_type([book,{**PAGE,'description':'The book discusses fiction and memory.'}]),'nonfiction')

    def test_intro_summary_does_not_append_a_different_section_after_collapsing_headings(self):
        from .ai_narrative_answers import _sentences
        intro='El libro se centra en la memoria de una familia que reconstruye la vida de una pintora.'
        page={**PAGE,'description':intro+' == Título == Una obra anterior del autor explora la guerra y el exilio.'}
        self.assertEqual(_sentences(page),[intro])

    def test_plot_section_keeps_its_own_subsections_and_stops_before_reception(self):
        from .ai_narrative_answers import _sentences
        first='La novela narra el viaje de Ana hacia una estación lunar para encontrar a su hermano.'
        second='Bruno descubre una señal misteriosa que pone en peligro a los habitantes de la estación.'
        page={**PAGE,'description':'== Argumento == '+first+' === La llegada === '+second+
              ' == Recepción == Una crítica explica cómo otra novela presenta una guerra diferente.'}
        self.assertEqual(_sentences(page),[first,second])

    def test_unknown_character_does_not_make_a_known_book_disappear_from_clarification(self):
        from .ai_character_answers import _character_answer
        request={'task':'relationship','focus':'','title':BOOK['title'],'targets':[BOOK],
                 'names':[],'ambiguous':True,'object_name':'','author_hint':''}
        with patch('core.ai_character_answers.request_for',return_value=request):
            result=_character_answer('¿Qué relación tiene con los demás?',[])
        self.assertEqual(result.status,'clarification')
        self.assertIn(BOOK['title'],result.text)
        self.assertNotIn('¿De qué libro',result.text)

    def test_character_request_reuses_the_same_explicit_author_parser_as_plot_requests(self):
        from .ai_character_answers import request_for
        result=request_for('Dime los personajes de Cuaderno lunar de Ana Robles',[])
        self.assertEqual(result['title'],'Cuaderno lunar')
        self.assertEqual(result['author_hint'],'Ana Robles')
        title=request_for('Dime los personajes de La casa de los sueños',[])
        self.assertEqual(title['title'],'La casa de los sueños')
        self.assertEqual(title['author_hint'],'')

    def test_manga_source_persists_its_literal_evidence_and_license_for_a_later_session(self):
        from django.test import override_settings
        from .ai_persistent_router import persist_sources
        from .literary_memory import retrieve_evidence
        page={**PAGE,'title':'Jardín astral','identity_text':
            'Jardín astral es una serie de manga escrita e ilustrada por Ana Robles.',
            'attribution':{**PAGE['attribution'],'title':'Jardín astral'}}
        with TemporaryDirectory() as folder, override_settings(LITMATE_LITERARY_MEMORY_DB=Path(folder)/'memory.sqlite3'):
            result=persist_sources([page])
            self.assertEqual(result.get('sources'),1)
            books,sources=retrieve_evidence('Jardín astral',requirement='summary')
            self.assertEqual(books[0]['author'],'Ana Robles')
            self.assertEqual(sources[0]['description'],page['description'])
            self.assertEqual(sources[0]['attribution']['revision_id'],'1234')
            self.assertTrue(sources[0]['memory_verified'])

    def test_a_licensed_manga_article_can_anchor_persistent_retrieval_without_a_catalog_card(self):
        from .literary_identity import _verified_web_work
        page={**PAGE,'title':'Jardín astral','identity_text':
            'Jardín astral es una serie de manga escrita e ilustrada por Ana Robles.',
            'attribution':{**PAGE['attribution'],'title':'Jardín astral'}}
        identity=_verified_web_work(page)
        self.assertEqual(identity.get('author'),'Ana Robles')
        self.assertEqual(identity.get('title'),'Jardín astral')
        self.assertNotIn('isbn',identity)
        self.assertNotIn('kind',identity)
        anime={**page,'identity_text':'Jardín astral es una serie de anime creada por Ana Robles.'}
        self.assertEqual(_verified_web_work(anime),{})

    def test_english_literary_article_can_anchor_a_known_published_author(self):
        from .literary_identity import _verified_web_work
        page={**PAGE,'identity_text':'Cuaderno lunar is a novel written by Ana Robles.'}
        self.assertEqual(_verified_web_work(page).get('author'),'Ana Robles')

    def test_plain_imperative_content_request_uses_the_narrative_router(self):
        from .ai_narrative_answers import request_for
        request=request_for('Explica el contenido de Atlas lunar de Ana Robles',[])
        self.assertIsNotNone(request)
        self.assertEqual(request['task'],'summary')
        self.assertEqual(request['title'],'Atlas lunar')
        self.assertEqual(request['author_hint'],'Ana Robles')

    def test_partial_title_overlap_does_not_stop_the_second_wikipedia_language(self):
        from .literary_search import search_wikipedia
        wrong={**PAGE,'title':'The Harbour','identity_text':'The Harbour is a novel by Otra Autora.'}
        right={**PAGE,'title':'The Harbour; or, The Return'}
        with patch('core.literary_search._search_wikipedia',side_effect=[[wrong],[right]]) as fetch:
            found=search_wikipedia('"The Harbour; or, The Return" Ana Robles argumento')
        self.assertEqual(found[0]['title'],right['title'])
        self.assertEqual([call.kwargs['language'] for call in fetch.call_args_list],['es','en'])

    def test_full_published_intro_title_can_differ_from_short_article_heading(self):
        from .literary_identity import same_work
        book={**BOOK,'title':'The Harbour; or, The Return'}
        page={**PAGE,'title':'The Harbour','url':'https://en.wikipedia.org/wiki/The_Harbour',
            'identity_text':'The Harbour; or, The Return is a novel by Ana Robles.',
            'attribution':{**PAGE['attribution'],'title':'The Harbour',
                           'url':'https://en.wikipedia.org/wiki/The_Harbour'}}
        self.assertTrue(same_work(page,book))
        self.assertFalse(same_work(page,{**book,'title':'The Harbour; or, The Lost Return'}))
        self.assertFalse(same_work(page,{**book,'author':'Otra Escritora'}))
        dated={**page,'identity_text':'The Harbour; or, The Return is an 1891 historical novel by Ana Robles.'}
        self.assertTrue(same_work(dated,book))
        film={**page,'identity_text':'The Harbour; or, The Return is a film adaptation of a novel by Ana Robles.'}
        self.assertFalse(same_work(film,book))

    def test_shared_title_prefix_does_not_merge_sequel(self):
        from .literary_identity import same_work
        page={**PAGE,'title':'Cuaderno lunar: El regreso',
            'identity_text':'Cuaderno lunar: El regreso es una novela de Ana Robles.',
            'attribution':{**PAGE['attribution'],'title':'Cuaderno lunar: El regreso'}}
        self.assertFalse(same_work(page,BOOK))

    def test_subject_categories_do_not_complete_a_thematic_content_job(self):
        from .literary_learning import _covers_requirement
        catalog = {**BOOK, 'categories':['History','Europe'],
                   'policy':'openlibrary-minimal-metadata-v1'}
        self.assertFalse(_covers_requirement(BOOK,[BOOK],[catalog],'themes'))
        self.assertTrue(_covers_requirement(BOOK,[BOOK],[catalog],'genres'))

    def test_literal_thematic_passage_completes_themes_but_not_plot(self):
        from .literary_learning import _covers_requirement
        from .literary_enrichment import enrich_source
        from .literary_identity import bind_source
        text = 'La obra examina la organización de las ciudades y el papel del comercio en la sociedad medieval.'
        source = bind_source(enrich_source({**PAGE,'description':'== Temas == '+text},BOOK,'themes'),BOOK)
        self.assertTrue(_covers_requirement(BOOK,[BOOK],[source],'themes'))
        self.assertFalse(_covers_requirement(BOOK,[BOOK],[source],'historical_context'))

    def test_unbacked_or_conflicting_thematic_claim_is_not_completed(self):
        from .literary_learning import _covers_requirement
        source={**PAGE,'literary_facts':[{'topic':'themes','evidence':'An invented quotation.'}]}
        self.assertFalse(_covers_requirement(BOOK,[BOOK],[source],'themes'))
        source={**PAGE,'description':'La obra estudia el comercio en las ciudades.',
                'literary_facts':[{'topic':'themes','evidence':'La obra estudia el comercio en las ciudades.'}],
                'conflicts_with':['another-source']}
        self.assertFalse(_covers_requirement(BOOK,[BOOK],[source],'themes'))

    def test_freeze_checkpoint_never_overwrites_a_previous_experiment(self):
        from scripts.knowledge.knowledge_campaign import save_new
        with TemporaryDirectory() as folder:
            path=Path(folder)/'frozen.json'
            save_new(path,{'original':True})
            with self.assertRaises(FileExistsError):
                save_new(path,{'original':False})
            self.assertEqual(json.loads(path.read_text()),{'original':True})


class StreamingMeasurementTests(SimpleTestCase):
    def test_first_progress_is_not_reported_as_verified_answer(self):
        from .bibliographic_http_probe import read_sse
        times=iter([1.2,1.8,2.3])
        response=iter([b'data: {"phase":"search"}\n',b'\n',
                       b'data: {"ready":"token"}\n',b'\n',b'data: [DONE]\n'])
        stream,events,metrics=read_sse(response,1.0,clock=lambda:next(times))
        self.assertEqual(events,[{'phase':'search'},{'ready':'token'}])
        self.assertAlmostEqual(metrics['first_progress_seconds'],.2)
        self.assertAlmostEqual(metrics['verified_ready_seconds'],.8)
        self.assertIsNone(metrics['first_verified_text_seconds'])
        self.assertIn('[DONE]',stream)
