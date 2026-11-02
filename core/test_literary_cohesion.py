"""Regresiones generales de roles, secuencias y traducción; datos sintéticos."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from django.test import SimpleTestCase
from .test_narrative_answers import BOOK,PAGE


class CharacterCoverageTests(SimpleTestCase):
    def test_a_unique_given_name_can_resolve_a_relationship_without_merging_people(self):
        from .ai_character_answers import _task_facts
        facts=[{'name':'Ana Robles','role':'protagonista de esta novela.','aliases':[],
                'classification':'main','proof':'Ana Robles: protagonista de esta novela.'},
               {'name':'Diego Ríos','role':'joven amigo de Ana y compañero de viaje.','aliases':[],
                'classification':'','proof':'Diego Ríos: joven amigo de Ana y compañero de viaje.'}]
        request={'task':'relationship','focus':'all','names':['Diego Ríos','Ana Robles']}
        self.assertEqual(len(_task_facts(request,facts)),1)
        ambiguous=[*facts,{'name':'Ana Torres','role':'una exploradora lunar.','aliases':[],
            'classification':'','proof':'Ana Torres: una exploradora lunar.'}]
        self.assertEqual(_task_facts(request,ambiguous),[])

    def test_age_modifier_does_not_hide_an_explicit_relationship(self):
        from .ai_character_answers import _relationship_fact
        fact={'name':'Diego','role':'joven amigo de Ana y compañero de viaje.',
              'aliases':[],'proof':'Diego: joven amigo de Ana y compañero de viaje.'}
        self.assertTrue(_relationship_fact(fact,['Diego','Ana']))
        self.assertFalse(_relationship_fact({**fact,'role':'joven que escucha al amigo de Ana.'},['Diego','Ana']))

    def test_short_verified_roles_survive_persistence_in_a_new_read(self):
        from .literary_memory import remember_evidence,retrieve_character_entities
        with TemporaryDirectory() as directory:
            database=Path(directory)/'memory.sqlite3'
            page={**PAGE,'description':'== Personajes ==\nEl capitán Bruno',
                'work_title':BOOK['title'],'work_author':BOOK['author'],'work_binding_verified':True,
                'character_facts':[{'name':'Bruno','role':'capitán','evidence':'El capitán Bruno'}]}
            remember_evidence([BOOK],[BOOK,page],database=database)
            found=retrieve_character_entities(books=[BOOK],database=database)
            self.assertIn('Bruno',{entry['canonical_name'] for entry in found})

    def test_principal_list_can_separate_other_verified_roles_without_promoting_them(self):
        from .ai_character_answers import answer_from_sources,request_for
        lines=['Ana: protagonista de esta novela y exploradora lunar.',
               'Bruno: capitán del vehículo que ayuda a Ana.',
               'Diego: amigo de Ana y compañero de viaje.']
        page={**PAGE,'description':'== Personajes ==\n'+'\n'.join(lines),'character_facts':[
            {'name':line.split(': ')[0],'role':line.split(': ')[1]} for line in lines]}
        message='Dime los personajes principales de Cuaderno lunar'
        result=answer_from_sources(message,request_for(message),[BOOK,page])
        self.assertIn('**Bruno**',result.text)
        self.assertIn('Otros personajes documentados:',result.text)
        self.assertEqual(result.diagnostics['principal_character_count'],1)
        self.assertTrue(result.diagnostics['partial_evidence'])
        exclusive='Dime solo los personajes principales de Cuaderno lunar'
        # Parser intent may require the title supplied independently; the
        # presentation rule still respects the explicit word "solo".
        request=request_for(message)
        limited=answer_from_sources(exclusive,request,[BOOK,page])
        self.assertNotIn('**Bruno**',limited.text)

    def test_short_role_statements_are_facts_that_still_require_audit(self):
        from .literary_quality import required_fact_statements
        self.assertEqual(required_fact_statements('**Bruno**: es capitán.'),['**Bruno**: es capitán.'])
        self.assertEqual(required_fact_statements('Hola, gracias.'),[])

    def test_short_explicit_roles_survive_html_extraction_and_literal_validation(self):
        from .literary_web import character_content
        from .ai_character_answers import answer_from_sources,request_for
        html=('<p>Cuaderno lunar es una novela de Ana Robles.</p><h2>Argumento</h2>'
            '<p>El capitán <a href="/wiki/Bruno">Bruno</a> organiza el viaje con el '
            'arponero <a href="/wiki/Diego">Diego</a>.</p>'
            '<p>El narrador, <a href="/wiki/Lucas">Lucas</a>, es un joven que se une al barco.</p>'
            '<h2>Adaptaciones</h2><p>El capitán <a href="/wiki/Actor">Actor</a> aparece en la película.</p>')
        parsed=character_content(html,context=PAGE['identity_text'],title=BOOK['title'])
        self.assertEqual({f['name'] for f in parsed['character_facts']},{'Bruno','Diego','Lucas'})
        page={**PAGE,'description':parsed['passage'],'character_facts':parsed['character_facts']}
        result=answer_from_sources('Dime los personajes de Cuaderno lunar',request_for('Dime los personajes de Cuaderno lunar'),[BOOK,page])
        self.assertIsNotNone(result)
        self.assertIn('**Bruno**',result.text)
        self.assertNotIn('Actor',result.text)
        for claim in result.diagnostics['audit']['claims']:
            self.assertIn(claim['evidence'],parsed['passage'])

    def test_a_role_in_another_novel_is_not_the_role_in_the_active_work(self):
        from .ai_character_answers import answer_from_sources,request_for
        text=('Bruno: protagonista de la novela Estación lejana.\n'
              'Ana: protagonista de esta novela y exploradora de una estación lunar.\n'
              'Diego: capitán del vehículo que ayuda a Ana.')
        page={**PAGE,'description':'== Personajes ==\n'+text,'character_facts':[
            {'name':line.split(': ')[0],'role':line.split(': ')[1]} for line in text.splitlines()]}
        result=answer_from_sources('Dime los personajes de Cuaderno lunar',request_for('Dime los personajes de Cuaderno lunar'),[BOOK,page])
        self.assertNotIn('Estación lejana',result.text)
        self.assertIn('**Diego**',result.text)

    def test_one_of_the_main_characters_is_an_explicit_classification(self):
        from .ai_character_answers import _classification
        self.assertEqual(_classification({'name':'Bruno','role':'es uno de los personajes principales de la novela Cuaderno lunar.'},
            {**PAGE,'work_title':BOOK['title']}),'main')


class NarrativeSequenceTests(SimpleTestCase):
    def test_honorific_does_not_split_a_sentence_or_leave_a_false_subject(self):
        from .literary_quality import factual_statements
        for honorific in ('Mr.','Mrs.','Ms.','Dr.'):
            statement='En contra del consejo de '+honorific+' Robles, Ana organiza otro viaje.'
            self.assertEqual(factual_statements(statement),[statement])

    def test_a_long_relative_clause_can_use_a_complete_literal_main_clause(self):
        from .ai_narrative_answers import direct_answer,request_for
        first='Ana tarda varios años en regresar a la estación donde vive su familia'
        long=first+', período durante el cual '+('su hermano protege la estación y espera noticias de su viaje, ')*5+'sin abandonarla.'
        page={**PAGE,'description':'== Argumento == '+long}
        result=direct_answer('Dime la trama de Cuaderno lunar',request_for('Dime la trama de Cuaderno lunar'),[BOOK,page])
        self.assertIsNotNone(result)
        self.assertIn(first+'.',result.text)
        self.assertTrue(all(len(c['evidence'])<=300 for c in result.diagnostics['audit']['claims']))

    def test_narrative_keeps_the_action_without_appending_a_character_inventory(self):
        from .ai_narrative_answers import direct_answer,request_for
        sentence=('Ana y Bruno se embarcan en un vehículo para buscar una estación desaparecida; '
            'precisamente sus pilotos son Diego, Ernesto y Federico.')
        page={**PAGE,'description':'== Argumento == '+sentence}
        result=direct_answer('Dime la trama de Cuaderno lunar',request_for('Dime la trama de Cuaderno lunar'),[BOOK,page])
        self.assertIn('estación desaparecida.',result.text)
        self.assertNotIn('sus pilotos son',result.text)
        self.assertEqual(result.diagnostics['audit']['claims'][0]['evidence'],sentence)

    def test_editorial_preface_is_not_the_opening_of_the_story(self):
        from .literary_search import _plot_selection
        story='Ana busca a su hermano y emprende un viaje a una estación abandonada.'
        body='== Argumento ==\nSe expone un resumen según la edición publicada por una editorial.\n'+story+'\nElla recibe una carta que cambia el rumbo de su investigación.'
        selected=_plot_selection(body,800)
        self.assertIn(story,selected['passage'])
        self.assertNotIn('edición publicada',selected['passage'])

    def test_intro_keeps_a_complete_connected_conflict_instead_of_only_one_line(self):
        from .ai_narrative_answers import _sentences
        first='La novela narra el viaje de Ana para encontrar a su hermano desaparecido.'
        next_line='Mientras Ana busca ayuda, Bruno debe proteger la estación de unos invasores que intentan apoderarse de sus recursos.'
        source={**PAGE,'description':first+' '+next_line+' La autora ganó un premio de una revista.'}
        selected=_sentences(source)
        self.assertIn(first,selected)
        self.assertIn(next_line,selected)
        self.assertFalse(any('premio' in line for line in selected))

    def test_retrieval_preserves_adjacent_events_and_their_pronouns(self):
        from .literary_search import _plot_selection
        opening='Ana busca a su hermano en una estación abandonada y decide reparar su vehículo.'
        continuation='Ella recibe una carta de Bruno y descubre por qué se cerró la estación.'
        ending='Finalmente Ana descubre el secreto y regresa definitivamente a su hogar.'
        body='== Argumento ==\n'+opening+'\n'+continuation+'\n'+'\n'.join(
            'Diego prepara una expedición para explorar otra región de la luna.' for _ in range(12))+'\n'+ending
        selected=_plot_selection(body,420)
        self.assertIn(continuation,selected['passage'])
        self.assertNotIn(ending,selected['passage'])
        self.assertEqual(selected['scope'],'sequential_excerpt')

    def test_source_word_budget_keeps_whole_sentences_without_an_unrelated_inventory(self):
        from .ai_narrative_answers import _sentences
        sentences=['Ana '+('explora la estación y busca pistas sobre su hermano ')*4+'.',
                   'Bruno '+('prepara el vehículo para viajar con Ana ')*4+'.',
                   'Diego '+('organiza la expedición junto con los demás ')*4+'.',
                   'La tripulación '+('incluye muchos nombres y detalles de sus integrantes ')*9+'.']
        lines=_sentences({**PAGE,'description':'== Argumento == '+' '.join(sentences)})
        self.assertNotIn(sentences[-1],lines)
        self.assertTrue(all(line in sentences for line in lines))


class TranslationPrecisionTests(SimpleTestCase):
    def test_one_orphan_does_not_prove_that_the_other_children_are_orphans(self):
        from .literary_quality import unsupported_orphanhood_claim
        claim='Ada restaura el jardín con otros niños huérfanos.'
        proof='After her parents die, Ada restores a garden with her friends.'
        self.assertTrue(unsupported_orphanhood_claim(claim,proof))
        self.assertFalse(unsupported_orphanhood_claim(claim,
            'Ada restores a garden with other orphaned children.'))

    def test_a_title_that_contains_a_century_keeps_its_original_identity(self):
        from .literary_presentation_language import _protect
        masked,protected=_protect('20th Century Boys follows several friends.',['20th Century Boys'])
        self.assertIn('20th Century Boys',protected.values())
        self.assertNotIn('siglo XX',protected.values())

    def test_protecting_a_name_does_not_change_a_longer_distinct_name(self):
        from .literary_presentation_language import _protect
        masked,protected=_protect('Ann and Annabel travel together.',['Ann'])
        self.assertIn('Annabel',masked)
        self.assertNotIn('LMPROTECTED0Xabel',masked)

    def test_century_and_turn_of_century_are_not_left_to_numeric_guessing(self):
        from .literary_presentation_language import _protect
        masked,protected=_protect('At the turn of the 20th century, Ada travels. In the 19th century Bruno travels.',[])
        self.assertNotIn('20th',masked)
        self.assertIn('cambio al siglo XX',protected.values())
        self.assertIn('siglo XIX',protected.values())

    def test_named_relations_protect_spelling_without_creating_new_character_facts(self):
        from .literary_presentation_language import presentation_identities
        source={**BOOK,'description':'Memory, her sister, tells the story. Ada is mentioned. Clara Ríos es la madre de Bruno.',
                'literary_facts':[{'topic':'relationships','subject':'Clara Ríos','value':'Bruno',
                    'evidence':'Clara Ríos es la madre de Bruno.'}]}
        original=deepcopy(source)
        names=presentation_identities([source])
        self.assertIn('Memory',names)
        self.assertIn('Clara Ríos',names)
        self.assertNotIn('Ada',names)
        self.assertEqual(source,original)
