"""Regresiones de la ampliación y de las referencias conversacionales."""
from unittest.mock import patch

from django.test import SimpleTestCase,TestCase

from .literary_constraints import explicit_author
from .literary_identity import resolve_followup_context
from .literary_genres import classify_categories,requested_categories
from .genre_recommendations import genre_answer

def packet_book(number,title,author):
    return {'kind':'book','book_id':'db_'+str(number),'source':'Catálogo LitMate','title':title,
            'author':author,'categories':['Packet Tracer','Computer networks','Cisco'],'language':'en',
            'description':'Información catalográfica; sin texto completo.','url':''}


class FinalCatalogueDialogueTests(SimpleTestCase):
    def test_packet_tracer_is_not_implicitly_an_author(self):
        self.assertEqual(explicit_author('Recomiéndame dos libros de Packet Tracer'),'')
        self.assertEqual(explicit_author('Recomiéndame libros de Cisco Packet Tracer'),'')

    def test_explicit_real_authors_are_kept(self):
        self.assertEqual(explicit_author('Recomiéndame libros de Cisco Networking Academy'),'Cisco Networking Academy')
        self.assertEqual(explicit_author('Recomiéndame libros de Mary Shelley'),'Mary Shelley')
        self.assertEqual(explicit_author('Recomiéndame libros del autor Packet Tracer'),'Packet Tracer')

    def test_network_subjects_preserve_the_specific_product(self):
        self.assertEqual(requested_categories('Libros sobre Packet Tracer'),['packet_tracer'])
        self.assertIn('networking',classify_categories(['Cisco','Packet Tracer']))

    def test_packet_tracer_recommendations_work_with_real_catalogue_identities(self):
        pool=[packet_book(1,'CCNA Hands-on Mastery with Packet Tracer','Anthony J. Sequeira, Ronald Wong'),
              packet_book(2,'Packet Tracer Network Simulator','Jesin A')]
        result=genre_answer('Recomiéndame dos libros de Packet Tracer',[],{},candidates=pool)
        self.assertIsNotNone(result);self.assertEqual(len(result.books),2)

    def test_technical_manual_request_is_not_routed_to_unrelated_fiction(self):
        result=genre_answer('Recomiéndame un manual para aprender Packet Tracer',[],{},
            candidates=[packet_book(2,'Packet Tracer Network Simulator','Jesin A')])
        self.assertIsNotNone(result);self.assertEqual(len(result.books),1)
        self.assertNotIn('versión del lenguaje',result.text)

    def test_missing_ordinal_is_marked_as_unresolved(self):
        self.assertEqual(resolve_followup_context('¿Quién escribió el segundo?',[])['reason'],'missing_ordinal')

    def test_second_sex_is_an_explicit_title_not_a_missing_ordinal(self):
        self.assertNotEqual(resolve_followup_context('¿Quién escribió El segundo sexo?',[])['reason'],'missing_ordinal')

    def test_missing_ordinal_never_calls_a_model_or_external_search(self):
        from .literary_ai_views import _compute_answer_impl
        with patch('core.literary_search.retrieve_web',side_effect=AssertionError('No buscar una referencia inexistente')):
            result,client=_compute_answer_impl('¿Quién escribió el segundo?',[],{})
        self.assertEqual(result.status,'clarification');self.assertEqual(client.calls,0)
        self.assertFalse(result.sources)

    def test_valid_ordinal_resolves_the_previous_list(self):
        first=packet_book(1,'CCNA Hands-on Mastery with Packet Tracer','Anthony J. Sequeira, Ronald Wong')
        second=packet_book(2,'Packet Tracer Network Simulator','Jesin A')
        context=resolve_followup_context('¿Quién escribió el segundo?',[
            {'question':'Recomiéndame dos libros de Packet Tracer','answer':'Dos referencias.',
             'books':[first,second],'intent':'recommend'}])
        self.assertEqual(context['books'][0]['author'],'Jesin A')


class MaterializationTests(TestCase):
    def test_bibliographic_author_order_does_not_duplicate_the_same_work(self):
        from scripts.knowledge.catalogue_materialization import CatalogueWriter
        metadata={'title':'Synthetic work','author':'Dante Alighieri','categories':[],
                  'source_url':'https://www.gutenberg.org/ebooks/123','language':'it'}
        first,_=CatalogueWriter().put(metadata)
        second,created=CatalogueWriter().put({**metadata,'author':'Alighieri, Dante'})
        self.assertFalse(created);self.assertEqual(first.pk,second.pk)

    def test_admitted_metadata_does_not_create_thousands_of_filter_options(self):
        from scripts.knowledge.catalogue_materialization import CatalogueWriter
        from .models import Genero
        writer=CatalogueWriter()
        metadata={'title':'Synthetic public catalogue work','author':'Synthetic Author',
                  'categories':['Poetry',*['Detailed subject '+str(i) for i in range(20)]],
                  'source_url':'https://www.gutenberg.org/ebooks/123','language':'en'}
        book,created=writer.put(metadata)
        self.assertTrue(created);self.assertLess(Genero.objects.count(),4)
        self.assertIn('Detailed subject',book.sinopsis)

    def test_repeated_import_keeps_an_existing_private_library_reference(self):
        from scripts.knowledge.catalogue_materialization import CatalogueWriter
        metadata={'title':'Synthetic public catalogue work','author':'Synthetic Author','categories':[],
                  'source_url':'https://www.gutenberg.org/ebooks/123','language':'en'}
        writer=CatalogueWriter();first,_=writer.put(metadata);second,created=writer.put(metadata)
        self.assertFalse(created);self.assertEqual(first.pk,second.pk)


class QualifiedTitleAndOrdinalEvidenceTests(SimpleTestCase):
    def source(self,number,title,author):
        return {'kind':'book','source':'Catálogo LitMate','book_id':'db_'+str(number),
                'title':title,'author':author,'description':'Metadatos bibliográficos.','categories':[],'url':''}

    def test_title_can_be_qualified_by_an_author_hint_without_a_model(self):
        from .ai_quick_answers import catalogue_lookup_answer
        source=self.source(1,'Infierno','Dante Alighieri')
        result=catalogue_lookup_answer('¿Quién escribió el Infierno de Dante?',[],lambda query:[source])
        self.assertIsNotNone(result);self.assertIn('Dante Alighieri',result.text)
        self.assertEqual(result.books[0]['title'],'Infierno')

    def test_partial_author_hint_does_not_resolve_two_authors(self):
        from .ai_quick_answers import catalogue_lookup_answer
        sources=[self.source(1,'Infierno','Dante Alighieri'),self.source(2,'Infierno','María Dante')]
        self.assertIsNone(catalogue_lookup_answer('¿Quién escribió el Infierno de Dante?',[],lambda query:sources))

    def test_wrong_author_hint_is_not_accepted(self):
        from .ai_quick_answers import catalogue_lookup_answer
        self.assertIsNone(catalogue_lookup_answer('¿Quién escribió el Infierno de Dante?',[],
                          lambda query:[self.source(1,'Infierno','Dan Brown')]))

    def test_identity_comparison_uses_both_verified_catalogue_references(self):
        from .ai_quick_answers import same_book_answer
        first=self.source(1,'Infierno','Dante Alighieri');second=self.source(2,'Inferno','Dan Brown')
        history=[{'accepted':True,'question':'¿Quién escribió Infierno?','answer':'Dante Alighieri',
                  'books':[first],'sources':[first]}]
        result=same_book_answer('¿Es la misma obra que Inferno de Dan Brown?',history,lambda query:[first,second])
        self.assertEqual(result.status,'answered');self.assertIn('distintas',result.text)
        self.assertIn('Dante Alighieri',result.text);self.assertIn('Dan Brown',result.text)
        self.assertNotIn('sexta',result.text)

    def test_identity_comparison_without_context_requests_the_missing_book(self):
        from .ai_quick_answers import same_book_answer
        search=patch('core.literary_search.search_catalog').start()
        try:
            result=same_book_answer('¿Es la misma obra que Inferno de Dan Brown?',[],search)
            self.assertEqual(result.status,'clarification');search.assert_not_called()
        finally:patch.stopall()

    def test_fourth_novel_does_not_support_sixth_novel(self):
        from .literary_quality import unsupported_ordinal_claim
        self.assertTrue(unsupported_ordinal_claim('Inferno es la sexta novela de la serie.',
                                                  'Inferno es la cuarta novela de la serie.'))
        self.assertFalse(unsupported_ordinal_claim('Inferno es la cuarta novela de la serie.',
                                                   'Inferno es la cuarta novela de la serie.'))

    def test_ordinal_of_a_recommendation_list_is_not_publication_chronology(self):
        from .literary_quality import unsupported_ordinal_claim
        self.assertFalse(unsupported_ordinal_claim('El segundo libro de la lista es Inferno.',
                                                   'Inferno es el cuarto libro de su serie.'))
