"""Regresiones de recuperación, citas y presupuestos; no miden un LLM real."""
import base64
import copy
import io
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.request import Request, ProxyHandler, build_opener
from django.test import SimpleTestCase, override_settings
from .literary_ai import LiteraryAssistant, ProviderUnavailable, canonical_sources, ChatResult
from .literary_evidence import validate_evidence, exact_context_available
from .local_embeddings import OllamaEmbeddings
from .local_llm import OllamaJSON
from .local_rag import index_documents, retrieve_fragments
from .literary_search import retrieve_book_content, retrieve_web, search_searx
from .test_literary_ai import BOOK, ROUTE, DRAFT, FakeLLM, REVIEW
from .test_local_ai import SHOW, response

QUOTE = 'La protagonista comprende que la memoria une su infancia con la vida frente al mar.'
EXCERPT = {**BOOK, 'description': QUOTE, 'kind': 'excerpt', 'locator': 'página 1 del PDF'}


class QuoteTests(unittest.TestCase):
    def draft(self, text, basis='sources'):
        return {**copy.deepcopy(DRAFT), 'text': text, 'basis': basis}

    def test_fabricated_quote_is_withheld(self):
        with self.assertRaises(ValueError):
            validate_evidence(self.draft('“Esta frase fue inventada y no existe en el texto original” [1].'),
                              canonical_sources([EXCERPT]), 'Analiza el libro')

    def test_literal_quote_is_allowed(self):
        validate_evidence(self.draft('“' + QUOTE + '” [1].'), canonical_sources([EXCERPT]),
                          'Dame una cita textual del libro')

    def test_paraphrase_is_not_a_literal_quote(self):
        with self.assertRaises(ValueError):
            validate_evidence(self.draft('“La protagonista conecta su pasado con los recuerdos del océano” [1].'),
                              canonical_sources([EXCERPT]), 'Dame una cita textual')

    def test_short_literal_quote_also_needs_a_source(self):
        with self.assertRaises(ValueError):
            validate_evidence(self.draft('“Una frase inexistente” [1].'),
                              canonical_sources([EXCERPT]), 'Dame una cita textual')

    def test_user_excerpt_can_be_quoted_without_catalog(self):
        draft = {**self.draft('"' + QUOTE + '" muestra una relación con la memoria.', 'excerpt'),
                 'citations': [], 'books': []}
        validate_evidence(draft, [], 'Analiza este fragmento: ' + QUOTE)

    def test_user_excerpt_quote_comparison_ignores_case(self):
        excerpt = 'Elena encontro un cuaderno azul. Ese cuaderno conservaba la memoria.'
        message = 'Lee este fragmento: "' + excerpt + '" ¿Quién conserva la memoria?'
        draft = {**self.draft("El texto indica que 'ese cuaderno conservaba la memoria'.",
                              'excerpt'), 'citations': [], 'books': []}
        validate_evidence(draft, [], message)

    def test_no_answer_is_required_when_exact_quote_missing(self):
        validate_evidence({**DRAFT, 'status': 'clarify'}, [], 'Dame una cita textual')

    def test_web_quote_limit_is_cumulative(self):
        first = ' '.join('primero' for _ in range(15))
        second = ' '.join('segundo' for _ in range(15))
        sources = canonical_sources([{**BOOK, 'kind': 'web', 'description': first + ' ' + second}])
        with self.assertRaises(ValueError):
            validate_evidence(self.draft('“' + first + '” y “' + second + '” [1].'), sources,
                              'Dame citas textuales')

    def test_page_cannot_come_from_model_memory(self):
        with self.assertRaises(ValueError):
            validate_evidence(self.draft('En la página 99 ocurre el encuentro [1].'),
                              canonical_sources([EXCERPT]), 'Analiza la novela')

    def test_pdf_page_locator_can_be_used(self):
        validate_evidence(self.draft('En la página 1 del PDF se relacionan memoria y mar [1].'),
                          canonical_sources([EXCERPT]), 'Analiza el pasaje')

    def test_chapter_summary_is_not_inferred_from_one_passage(self):
        self.assertFalse(exact_context_available('Resume el capítulo 2', canonical_sources([EXCERPT])))

    def test_wrong_page_does_not_qualify_as_exact_context(self):
        self.assertFalse(exact_context_available('Analiza la página 99', canonical_sources([EXCERPT])))
        self.assertTrue(exact_context_available('Analiza la página 1', canonical_sources([EXCERPT])))

    def test_page_claim_without_accent_still_requires_evidence(self):
        with self.assertRaises(ValueError):
            validate_evidence(self.draft('El conflicto termina en la pagina 99 [1].'),
                              canonical_sources([EXCERPT]), 'Analiza el libro')

    def test_missing_excerpt_citation_is_not_an_excerpt_answer(self):
        draft = {**self.draft('La memoria aparece como tema.', 'excerpt'), 'citations': [], 'books': []}
        with self.assertRaises(ValueError):
            validate_evidence(draft, canonical_sources([EXCERPT]), 'Analiza la obra')


class FakeEmbeddings:
    def __init__(self, fail=False, digest='a' * 64):
        self.calls = 0
        self.fail = fail
        self.digest = digest

    def identity(self):
        return 'embeddinggemma:latest', self.digest

    def embed(self, texts, query=False):
        self.calls += 1
        if self.fail:
            raise OSError('Ollama no disponible')
        return [[1., 0., 0.] if query or 'melancolía' in text else [0., 1., 0.] for text in texts]


class HybridTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.folder = self.root / 'libros'
        self.folder.mkdir()
        self.db = self.root / 'rag.sqlite3'
        (self.folder / 'Horizonte__Autora.txt').write_text(
            'La protagonista contempla el horizonte y siente melancolía ante la ausencia de su familia. ' * 5)
        (self.folder / 'Ciudad__Otro autor.txt').write_text(
            'Los personajes conversan sobre jardines, avenidas y edificios del centro de la ciudad. ' * 5)

    def tearDown(self):
        self.tmp.cleanup()

    def test_semantic_paraphrase_recovers_passage_without_shared_words(self):
        embedder = FakeEmbeddings()
        index_documents(self.folder, self.db, embedder=embedder)
        result = retrieve_fragments('añoranza', self.db, embedder=embedder)
        self.assertTrue(result)
        self.assertEqual(result[0]['title'], 'Horizonte')
        self.assertIn('melancolía', result[0]['description'])

    def test_explicit_book_is_not_replaced_by_semantically_similar_book(self):
        embedder = FakeEmbeddings()
        index_documents(self.folder, self.db, embedder=embedder)
        result = retrieve_fragments('Añoranza en Ciudad', self.db, embedder=embedder)
        self.assertTrue(result)
        self.assertTrue(all(row['title'] == 'Ciudad' for row in result))

    def test_unknown_title_does_not_use_other_books(self):
        index_documents(self.folder, self.db)
        self.assertEqual(retrieve_fragments('familia', self.db, book_titles=['Obra inexistente']), [])

    def test_reindex_reuses_unchanged_embeddings(self):
        first = FakeEmbeddings()
        index_documents(self.folder, self.db, embedder=first)
        second = FakeEmbeddings()
        index_documents(self.folder, self.db, embedder=second)
        self.assertGreater(first.calls, 0)
        self.assertEqual(second.calls, 0)

    def test_failed_embeddings_keep_previous_working_index(self):
        index_documents(self.folder, self.db, embedder=FakeEmbeddings())
        before = self.db.read_bytes()
        (self.folder / 'Nuevo__Autora nueva.txt').write_text('Un personaje atraviesa el bosque al amanecer. ' * 4)
        with self.assertRaises(OSError):
            index_documents(self.folder, self.db, embedder=FakeEmbeddings(fail=True))
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(list(self.root.glob('litmate-rag-*')), [])

    def test_embedding_model_change_falls_back_to_lexical_without_mixing_vectors(self):
        index_documents(self.folder, self.db, embedder=FakeEmbeddings())
        changed = FakeEmbeddings(digest='b' * 64)
        self.assertTrue(retrieve_fragments('melancolía', self.db, embedder=changed))
        self.assertEqual(changed.calls, 0)

    def test_page_without_identified_book_is_ambiguous(self):
        index_documents(self.folder, self.db)
        self.assertEqual(retrieve_fragments('Analiza página 1', self.db), [])

    def test_content_query_never_calls_public_search(self):
        index_documents(self.folder, self.db)
        with (override_settings(LITMATE_RAG_DB=self.db, LITMATE_RAG_SEMANTIC=False),
              patch('core.literary_search.read_json_url') as network):
            result = retrieve_book_content('¿Qué expresa la melancolía en Horizonte?',
                                           [{'title': 'Horizonte', 'author': 'Autora'}])
        network.assert_not_called()
        self.assertTrue(result)


class LocalEmbeddingsTests(unittest.TestCase):
    def run_embed(self, vectors):
        show = {'details': {'format': 'gguf'}, 'model_info': {'general.architecture': 'gemma3'},
                'capabilities': ['embedding']}
        tags = {'models': [{'name': 'embeddinggemma:latest', 'digest': 'a' * 64}]}
        with patch('core.local_embeddings.read_json_url', side_effect=[show, tags, {'embeddings': vectors}]) as fetch:
            result = OllamaEmbeddings().embed(['añoranza'], query=True)
        return result, fetch

    def test_embeddings_are_local_normalized_and_use_query_prompt(self):
        result, fetch = self.run_embed([[3, 4]])
        self.assertEqual(result, [[0.6, 0.8]])
        self.assertEqual(fetch.call_args.args[0], 'http://127.0.0.1:11434/api/embed')
        self.assertTrue(fetch.call_args.kwargs['local'])
        self.assertTrue(fetch.call_args.kwargs['payload']['input'][0].startswith('task: search result'))
        self.assertNotIn('Authorization', fetch.call_args.kwargs['headers'])

    def test_nonfinite_and_zero_embeddings_are_rejected(self):
        for vectors in ([[float('nan'), 1]], [[float('inf'), 1]], [[0, 0]]):
            with self.subTest(vectors=vectors), self.assertRaises(ValueError):
                self.run_embed(vectors)

    def test_remote_model_is_rejected_before_embedding(self):
        with patch('core.local_embeddings.read_json_url', return_value={'remote_host': 'https://ollama.com'}) as fetch:
            with self.assertRaises(ProviderUnavailable):
                OllamaEmbeddings().embed(['Texto de prueba'])
        self.assertEqual(fetch.call_count, 1)

    def test_remote_origin_and_cloud_model_cannot_be_used(self):
        for args in ({'base_url': 'https://api.example.com:443'}, {'model': 'embeddinggemma:cloud'}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                OllamaEmbeddings(**args)


class EngineAndBudgetTests(unittest.TestCase):
    def test_user_excerpt_cannot_be_sent_to_public_catalog_by_router(self):
        message = 'Analiza este fragmento: ' + QUOTE
        route = {**ROUTE, 'intent': 'analysis', 'queries': [QUOTE]}
        draft = {**DRAFT, 'text': 'El pasaje conecta memoria e infancia.', 'basis': 'excerpt',
                 'citations': [], 'books': []}
        search, web = Mock(), Mock()
        result = LiteraryAssistant(FakeLLM(route=route, answer=draft), search, web_search=web).reply(message)
        self.assertEqual(result.status, 'answered')
        search.assert_not_called()
        web.assert_not_called()

    def test_active_markdown_link_is_not_published_even_if_reviewer_approves(self):
        draft = {**DRAFT, 'text': 'Lee [esta recomendación](javascript:alert(1)) [1].'}
        llm = FakeLLM(answer=draft, repair=draft, review=REVIEW)
        result = LiteraryAssistant(llm, lambda q: [BOOK]).reply('Recomiéndame un libro')
        self.assertEqual(result.status, 'unavailable')
        self.assertNotIn('javascript:', result.text)

    def test_programming_book_title_with_colon_remains_allowed(self):
        from .literary_ai import forbidden_output
        self.assertFalse(forbidden_output('JavaScript: The Definitive Guide es un libro de programación.'))

    def test_roman_chapter_number_without_text_gets_clarification(self):
        llm = FakeLLM(route={**ROUTE, 'intent': 'summary'})
        result = LiteraryAssistant(llm, lambda q: []).reply('Resume el capítulo IV de 1984')
        self.assertEqual(result.status, 'clarification')
        self.assertEqual(llm.calls, 1)

    def test_content_retrieval_prevents_unnecessary_web_lookup(self):
        route = {**ROUTE, 'intent': 'analysis', 'queries': [BOOK['title']]}
        draft = {**DRAFT, 'text': 'El pasaje relaciona la memoria con la infancia [1].', 'basis': 'sources'}
        llm, web = FakeLLM(route=route, answer=draft), Mock(return_value=[])
        content = Mock(return_value=[EXCERPT])
        result = LiteraryAssistant(llm, lambda q: [BOOK], web_search=web,
                                   content_search=content).reply('Analiza el contenido del libro')
        self.assertEqual(result.status, 'answered')
        web.assert_not_called()
        content.assert_called_once()

    def test_indexed_quote_can_be_answered_instead_of_always_requesting_upload(self):
        route = {**ROUTE, 'intent': 'analysis'}
        draft = {**DRAFT, 'text': '“' + QUOTE + '” [1].', 'basis': 'excerpt'}
        llm = FakeLLM(route=route, answer=draft)
        result = LiteraryAssistant(llm, lambda q: [], content_search=lambda m, c: [EXCERPT]).reply(
            'Dame una cita textual del libro')
        self.assertEqual(result.status, 'answered')
        self.assertIn(QUOTE, result.text)

    def test_unrepairable_fabricated_quote_is_never_published(self):
        route = {**ROUTE, 'intent': 'analysis'}
        text = '“Esta frase inventada nunca apareció en el libro ni en los fragmentos recibidos” [1].'
        draft = {**DRAFT, 'text': text}
        llm = FakeLLM(route=route, answer=draft, repair=draft)
        result = LiteraryAssistant(llm, lambda q: [], content_search=lambda m, c: [EXCERPT]).reply(
            'Dame una cita textual del libro')
        self.assertEqual(result.status, 'unavailable')
        self.assertNotIn('Esta frase inventada', result.text)

    def test_completed_provider_deadline_does_not_make_more_requests(self):
        client = OllamaJSON()
        client.deadline = time.monotonic() - 1
        with patch('core.local_llm.read_json_url') as network, self.assertRaises(ProviderUnavailable):
            client('review', 'JSON', {}, 'qwen3.5:4b-q4_K_M')
        network.assert_not_called()

    def test_context_reduction_preserves_latest_turn_and_original_input(self):
        client = OllamaJSON(context=8192)
        data = {'message': '¿Y el segundo libro?', 'accepted_history': [
            {'question': 'antes', 'answer': 'x' * 15000, 'sources': []},
            {'question': 'ahora', 'answer': 'Obra A y Obra B', 'books': [{'title': 'Obra B'}], 'sources': []}]}
        original = copy.deepcopy(data)
        fitted = json.loads(client._fit_context('JSON', data, 2048))
        self.assertEqual(data, original)
        self.assertEqual(len(fitted['accepted_history']), 1)
        self.assertEqual(fitted['accepted_history'][0]['books'][0]['title'], 'Obra B')
        self.assertEqual(fitted['message'], '¿Y el segundo libro?')

    def test_full_draft_is_not_truncated_to_get_reviewer_approval(self):
        client = OllamaJSON(context=8192)
        with self.assertRaises(ProviderUnavailable):
            client._fit_context('JSON', {'draft': {'text': 'x' * 40000}}, 768)


class SearchWithoutContainersTests(SimpleTestCase):
    @override_settings(LITMATE_AI_USE_SEARXNG=False)
    def test_disabling_searxng_does_not_connect_to_container(self):
        with patch('core.literary_search.read_json_url') as network:
            self.assertEqual(search_searx('1984'), [])
        network.assert_not_called()

    @override_settings(LITMATE_AI_USE_SEARXNG=False)
    def test_wikipedia_remains_available_without_containers(self):
        from django.core.cache import cache
        cache.clear()
        with (patch('core.literary_search.search_wikipedia', return_value=[
                  {**BOOK, 'kind': 'web', 'source': 'Wikipedia'}]) as wiki,
              patch('core.literary_search.search_searx') as searx):
            self.assertTrue(retrieve_web('Sin novedad en el frente'))
        wiki.assert_called_once()
        searx.assert_not_called()
