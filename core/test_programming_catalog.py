"""Materias técnicas: las fichas no equivalen a haber leído el libro."""
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from .genre_recommendations import genre_answer
from .literary_genres import classify_categories, requested_categories, matches_categories


def source(number, categories):
    return {'kind':'book', 'title':f'Programming reference volume {number}',
        'author':f'Example Author {number}', 'book_id':f'sqlkb:{number}',
        'source':'Open Library', 'url':f'https://openlibrary.org/works/OL{number}W',
        'categories':categories, 'description':'', 'synopsis':'',
        'policy':'openlibrary-minimal-metadata-v1', 'language':'en'}


class ProgrammingCatalogueTests(SimpleTestCase):
    def test_python_catalogue_category_is_a_subject_with_programming_parent(self):
        actual = classify_categories(['Python (Computer program language)'])
        self.assertIn('python_programming', actual)
        self.assertIn('programming', actual)

    def test_python_title_does_not_prove_subject(self):
        actual = classify_categories(['Reptiles', 'Natural history'])
        self.assertNotIn('python_programming', actual)

    def test_java_and_javascript_remain_distinct(self):
        self.assertEqual(requested_categories('Recomiéndame libros de JavaScript'), ['javascript_programming'])
        self.assertNotIn('java_programming', classify_categories(['JavaScript (Computer program language)']))

    def test_cross_language_metadata_does_not_override_an_explicit_title(self):
        mixed={**source(1,['Python (Computer program language)','Java (Computer program language)']),
               'title':'Sams Teach Yourself Python in 24 Hours'}
        self.assertFalse(matches_categories(mixed,['java_programming']))
        self.assertTrue(matches_categories(mixed,['python_programming']))

    def test_existing_fantasy_and_horror_classifications_survive(self):
        actual = classify_categories(['Fantasy fiction', 'Horror fiction'])
        self.assertIn('fantasy', actual)
        self.assertIn('horror', actual)
        self.assertNotIn('programming', actual)

    def test_metadata_recommendation_has_real_source_ids_and_discloses_limits(self):
        candidates = [source(i, ['Computer programming']) for i in range(1,4)]
        result = genre_answer('Recomiéndame tres libros de programación', [], {}, candidates=candidates)
        self.assertIsNotNone(result)
        self.assertEqual(len(result.books), 3)
        self.assertIn('no del texto completo', result.text)
        self.assertTrue(all(book['source_id'] > 0 for book in result.books))

    def test_learning_python_filters_out_other_languages(self):
        candidates = [source(1,['Python (Computer program language)']), source(2,['Java (Computer program language)'])]
        result = genre_answer('Recomiéndame libros para aprender Python', [], {}, candidates=candidates)
        self.assertIsNotNone(result)
        self.assertEqual([book['title'] for book in result.books], [candidates[0]['title']])

    def test_does_not_invent_beginner_level(self):
        self.assertIsNone(genre_answer('Recomiéndame libros de programación para principiantes', [], {},
                                      candidates=[source(1,['Computer programming'])]))

    def test_prefers_learning_reference_to_conference_proceedings(self):
        conference={**source(1,['Computer programming','Congresses']), 'title':'Conference proceedings on programming'}
        tutorial={**source(2,['Computer programming']), 'title':'Introduction to programming'}
        result=genre_answer('Recomiéndame un libro de programación', [], {}, candidates=[conference,tutorial])
        self.assertEqual(result.books[0]['title'], tutorial['title'])

    def test_explicit_language_is_still_checked(self):
        result = genre_answer('Recomiéndame libros de programación en español', [], {},
                              candidates=[source(1,['Computer programming'])])
        self.assertEqual(result.status, 'unavailable')

    def test_exact_chapter_request_does_not_use_bibliographic_answer(self):
        self.assertIsNone(genre_answer('Copia el capítulo 3 del segundo libro de Python', [], {},
                                      candidates=[source(1,['Python (Computer program language)'])]))


@override_settings(LITMATE_STRUCTURED_KNOWLEDGE=True)
class ProgrammingImportedAuthorsTests(TestCase):
    def create_records(self, *, author_status='source_metadata', with_author=True):
        from .bibliographic_repository import digest, index_classifications
        from .knowledge_models import KBRecord
        defaults={'provider':'openlibrary','checksum':'a'*64,'retrieved_at':timezone.now(),
                  'policy':'openlibrary-minimal-metadata-v1','license':'Bibliographic facts'}
        if with_author:
            KBRecord.objects.create(**defaults,id=digest('openlibrary','/authors/OL123A'),
                external_id='/authors/OL123A',kind='author',label='Catalogued Example Author',
                source_url='https://openlibrary.org/authors/OL123A',payload={},status=author_status)
        KBRecord.objects.create(**defaults,id=digest('openlibrary','/works/OL123W'),
            external_id='/works/OL123W',kind='work',label='Python programming example',
            source_url='https://openlibrary.org/works/OL123W',payload={
                'author_keys':['/authors/OL123A'],'categories':['Python (Computer program language)']})
        index_classifications()

    def test_imported_author_keys_are_resolved_in_a_batch(self):
        from .bibliographic_repository import genre_sources
        self.create_records()
        with self.assertNumQueries(2):
            found=genre_sources(['python_programming'])
        self.assertEqual(found[0]['author'],'Catalogued Example Author')
        self.assertEqual(found[0]['description'],'')

    def test_missing_author_is_not_fabricated(self):
        from .bibliographic_repository import genre_sources
        self.create_records(with_author=False)
        self.assertEqual(genre_sources(['python_programming']),[])

    def test_conflicted_author_is_not_published(self):
        from .bibliographic_repository import genre_sources
        self.create_records(author_status='conflict')
        self.assertEqual(genre_sources(['python_programming']),[])


class CatalogueDisplayEvidenceTests(SimpleTestCase):
    def test_search_links_do_not_present_estimated_prices_as_quotes(self):
        from .services import catalogue_offers
        data=catalogue_offers({'tiendas':[{'precio_clp':14990,'precio_formateado':'$14.990 CLP','url':'https://example.org/search'}]})
        self.assertEqual(data['precio_desde'],'Precio por consultar')
        self.assertIsNone(data['tiendas'][0]['precio_clp'])
        self.assertEqual(data['tiendas'][0]['url'],'https://example.org/search')

    def test_verified_quote_is_kept(self):
        from .services import catalogue_offers
        data=catalogue_offers({'tiendas':[{'precio_clp':10000,'precio_formateado':'$10.000 CLP','precio_verificado':True}]})
        self.assertEqual(data['precio_desde'],'$10.000 CLP')

    def test_description_does_not_become_a_fabricated_book_excerpt(self):
        from .services import generar_demo_extracto
        metadata='Información catalográfica; sin texto completo. Fuente: https://openlibrary.org/works/OL123W'
        text=generar_demo_extracto(sinopsis=metadata,titulo='Programming example')
        self.assertIn(metadata,text)
        self.assertIn('no es un extracto',text)
        self.assertNotIn('«',text)

    def test_missing_description_is_disclosed(self):
        from .services import generar_demo_extracto
        self.assertIn('No hay un fragmento',generar_demo_extracto(titulo='Unknown text'))


class CatalogueImportedDisplayTests(TestCase):
    def test_imported_book_displays_unknown_values_without_fabrication(self):
        from .models import Autor, Libro
        from .services import buscar_libros_hibrido
        author=Autor.objects.create(nombre='Example technical author')
        Libro.objects.create(titulo='Verified programming example',autor=author,genero='Programación')
        result=buscar_libros_hibrido(query='Verified programming example',max_results=1)[0]
        self.assertIsNone(result['calificacion'])
        self.assertEqual(result['total_resenas'],0)
        self.assertIsNone(result['paginas'])
        self.assertEqual(result['editorial'],'Editorial no informada')
        self.assertEqual(result['precio_desde'],'Precio por consultar')
