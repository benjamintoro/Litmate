"""Metadatos controlados y SQLite de pruebas, sin servicios externos."""
from unittest.mock import patch
from django.test import SimpleTestCase,TestCase,override_settings
from .literary_genres import classify_categories,requested_categories,matches_categories
from .genre_recommendations import genre_answer,remember_recommendations
from .literary_conversation import resolve_topic_context,remember_topic
from .literary_identity import same_work


def source(index,categories=('Crime fiction',),**changes):
    return {'kind':'book','title':'Obra verificada '+str(index),'author':'Autora '+str(index),
        'source':'Wikidata','url':'https://www.wikidata.org/wiki/Q'+str(index+10000),
        'categories':list(categories),'description':'','language':'es',**changes}


class GenreTests(SimpleTestCase):
    def answer(self,message,pool=None,history=(),context=None):
        return genre_answer(message,history,context or {'subject':'crimen','intent':'recommend'},
                            candidates=pool if pool is not None else [source(i) for i in range(12)])

    def test_crime_returns_three_distinct_books(self):
        result=self.answer('Recomiéndame libros de crimen')
        self.assertEqual(len(result.books),3)
        self.assertTrue(result.diagnostics['audit']['claims'])
        self.assertNotIn('Fuentes de las fichas',result.text)

    def test_more_and_rejection_exclude_all_previous_variants(self):
        first=self.answer('Recomiéndame libros de crimen')
        state={};remember_recommendations(state,'Recomiéndame libros de crimen',{'intent':'recommend'},first)
        context={'subject':'crimen','intent':'recommend','followup':True,'recommendation_state':state['recommendations']}
        second=self.answer('Más libros de crimen',context=context)
        self.assertFalse({b['title'] for b in first.books}&{b['title'] for b in second.books})
        remember_recommendations(state,'Más libros de crimen',context,second)
        third=self.answer('Otro que no sea ese',context={**context,'recommendation_state':state['recommendations']})
        self.assertEqual(len(third.books),1)
        self.assertNotIn(third.books[0]['title'],{b['title'] for b in [*first.books,*second.books]})

    def test_verified_work_anchor_deduplicates_author_variants_not_homonyms(self):
        one=source(1,title='Crimen y castigo',author='Fiódor M. Dostoievski')
        other={**one,'title':'Crimen y Castigo','author':'Fiódor Dostoyevski'}
        self.assertTrue(same_work(one,other))
        self.assertFalse(same_work(one,{**other,'url':'https://www.wikidata.org/wiki/Q20000'}))
        result=self.answer('Dame tres libros de crimen',pool=[one,other,source(2),source(3)])
        self.assertEqual(len(result.books),3)

    def test_taxonomy_separates_magic_realism_from_fantasy_and_allows_hybrids(self):
        magical=source(1,('Magical realism',),description='Una fantasía con magia y dragones.')
        self.assertFalse(matches_categories(magical,['fantasy']))
        self.assertTrue(matches_categories(source(2,('Magical realism','Fantasy')),['fantasy','magical_realism']))
        self.assertIn('fantasy',classify_categories(['Dark fantasy']))
        self.assertEqual(requested_categories('fantasía oscura'),['dark_fantasy'])
        self.assertIn('epic_fantasy',classify_categories(['Fiction / Fantasy / Epic']))

    def test_manga_is_format_independent_of_theme_and_audience(self):
        result=classify_categories(['Comics & Graphic Novels / Manga / Fantasy','Young adult fiction'])
        self.assertIn('manga',result);self.assertIn('fantasy',result);self.assertIn('young_adult',result)
        self.assertFalse(matches_categories(source(1,('Manga',)),['fantasy']))

    def test_negative_genres_and_inherited_language_remain_constraints(self):
        pool=[source(1,('Fantasy','Horror')),source(2,('Fantasy',),language='en'),source(3,('Fantasy',),language='es')]
        result=self.answer('Más libros',pool=pool,context={'subject':'fantasía sin terror','intent':'recommend',
            'followup':True,'query':'libros de fantasía sin terror en español'})
        self.assertEqual([book['title'] for book in result.books],['Obra verificada 3'])

    def test_followups_and_genre_changes_keep_session_context(self):
        state={}
        for message in ['Recomiéndame libros de crimen','Más libros de crimen','Otro que no sea ese',
                        'Dame diferentes','Ya leí ese','No me gustó ninguno','Recomiéndame otros del mismo género']:
            context=resolve_topic_context(message,state)
            self.assertEqual(context['intent'],'recommend',message)
            self.assertIn('crimen',context['subject'],message)
            remember_topic(state,message,context)
        for genre in ['fantasía','romance']:
            message='Ahora de '+genre;context=resolve_topic_context(message,state)
            self.assertEqual(context['subject'],genre);remember_topic(state,message,context)

    def test_author_exclusion_and_session_isolation(self):
        pool=[source(1,author='Stephen King'),source(2),source(3),source(4)]
        result=self.answer('Que no sea de Stephen King',pool=pool,context={'subject':'crimen','intent':'recommend','followup':True})
        self.assertNotIn('Stephen King',[b['author'] for b in result.books])
        state={};remember_recommendations(state,'Que no sea de Stephen King',{'intent':'recommend'},result)
        self.assertEqual(state['recommendations']['excluded_authors'],['Stephen King'])
        self.assertEqual(len(self.answer('Recomiéndame libros de crimen').books),3)

    def test_no_candidates_is_honest_and_cards_keep_metadata(self):
        self.assertEqual(self.answer('Recomiéndame libros de crimen',pool=[]).status,'unavailable')
        from .ai_presentation import build_book_cards
        result=self.answer('Recomiéndame libros de crimen',pool=[source(1,
            image_url='https://covers.openlibrary.org/b/id/1-M.jpg',synopsis='Descripción en español.')])
        cards=build_book_cards(result)
        self.assertEqual(cards[0]['image_url'],'https://covers.openlibrary.org/b/id/1-M.jpg')
        self.assertEqual(cards[0]['synopsis'],'Descripción en español.')
        self.assertTrue({'Amazon','Buscalibre'}<={link['label'] for link in cards[0]['links']})

    def test_audit_failure_cannot_be_bypassed(self):
        with patch('core.literary_quality.validate_audit',side_effect=ValueError('rejected')):
            self.assertIsNone(self.answer('Recomiéndame libros de crimen'))

    def test_period_and_year_inside_a_bibliographic_title_are_not_plot_claims(self):
        result=self.answer('Recomiéndame libros de crimen',pool=[source(1,title='Una novela, No. 138. Año 1915')])
        self.assertIsNotNone(result)
        self.assertEqual(result.books[0]['title'],'Una novela, No. 138. Año 1915')

    def test_explicit_read_title_and_direct_genre_request(self):
        result=self.answer('Ya leí Obra verificada 1',context={'subject':'crimen','intent':'recommend','followup':True})
        self.assertNotIn('Obra verificada 1',[book['title'] for book in result.books])
        context=resolve_topic_context('Recomiéndame tres thrillers',{})
        self.assertEqual(context['intent'],'recommend')


@override_settings(LITMATE_STRUCTURED_KNOWLEDGE=True)
class GenreSQLTests(TestCase):
    @override_settings(LITMATE_AI_QUICK_ANSWERS=True,LITMATE_USE_EXISTING_QUOTAS=False,LITMATE_AI_LOCK_BACKEND='cache')
    def test_db_sessions_keep_recommendations_and_isolate_two_conversations(self):
        import json
        from django.test import Client
        from django.core.cache import cache
        from .literary_ai_views import HISTORY_KEY
        cache.clear()
        with patch('core.bibliographic_repository.genre_sources',return_value=[source(i) for i in range(15)]), \
             patch('core.genre_recommendations.local_genre_sources',return_value=[]), \
             patch('core.literary_ai_views.build_assistant') as model:
            for message in ['Recomiéndame libros de crimen','Más libros de crimen','Otro que no sea ese']:
                response=self.client.post('/chatbot_query/',data=json.dumps({'message':message}),content_type='application/json')
                self.assertEqual(response.status_code,200)
                if response.streaming:b''.join(response.streaming_content)
            state=self.client.session[HISTORY_KEY]
            self.assertEqual(len(state['recommendations']['seen']),7)
            other=Client()
            response=other.post('/chatbot_query/',data=json.dumps({'message':'Recomiéndame libros de crimen'}),content_type='application/json')
            if response.streaming:b''.join(response.streaming_content)
            self.assertEqual(len(other.session[HISTORY_KEY]['recommendations']['seen']),3)
            self.assertEqual(len(self.client.session[HISTORY_KEY]['recommendations']['seen']),7)
            model.assert_not_called()

    def test_classification_index_is_idempotent_and_lookup_has_bounded_query_count(self):
        from .knowledge_models import KBRecord,KBRelation
        from .bibliographic_repository import index_classifications,genre_sources
        from django.utils import timezone
        for i in range(8):
            KBRecord.objects.create(id=str(i).zfill(64),provider='gutenberg',external_id=str(i+1),
                kind='edition',label='Obra '+str(i),source_url='https://www.gutenberg.org/ebooks/'+str(i+1),
                policy='gutenberg-catalog-public-domain-v1',license='CC0-1.0',checksum='a'*64,
                retrieved_at=timezone.now(),payload={'categories':['Detective and mystery stories'],'author':'Autora '+str(i)})
        index_classifications();before=KBRelation.objects.count();index_classifications()
        self.assertEqual(KBRelation.objects.count(),before)
        with self.assertNumQueries(1):self.assertEqual(len(genre_sources(['crime'])),8)
        with self.assertNumQueries(1):self.assertEqual(len(genre_sources(['crime'],exclude_records=['0'*64])),7)

    def test_legacy_many_to_many_genres_keep_images_and_do_not_issue_n_plus_one(self):
        from .models import Genero,Autor,Libro
        from .genre_recommendations import local_genre_sources
        genre=Genero.objects.create(nombre='Fantasía')
        for index in range(4):
            author=Autor.objects.create(nombre='Autor '+str(index))
            book=Libro.objects.create(titulo='Libro '+str(index),autor=author,sinopsis='Descripción en español.',
                                     portada_url='https://covers.openlibrary.org/b/id/1-M.jpg')
            book.generos.add(genre)
        with self.assertNumQueries(3):
            sources=local_genre_sources(['fantasy'])
        self.assertEqual(len(sources),4)
        self.assertTrue(all(source['image_url'] for source in sources))
