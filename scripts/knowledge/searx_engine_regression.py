"""Regresiones offline dentro de la imagen SearXNG fijada por Compose.

Ejecutar con el Python del contenedor, no requiere consultas a proveedores.
"""
from datetime import datetime
from types import SimpleNamespace
import unittest
import importlib
import os

openlibrary = importlib.import_module('searx.engines.' + os.environ.get('LITMATE_TEST_ENGINE', 'openlibrary'))
from searx.results import ResultContainer


class OpenLibraryRegressionTests(unittest.TestCase):
    def test_search_requests_a_small_projection_instead_of_every_editions_isbn(self):
        from urllib.parse import urlsplit, parse_qs
        params={'pageno':1,'headers':{}}
        # SearXNG injects logger when it loads an engine; the offline import does not.
        from unittest.mock import patch,Mock
        with patch.object(openlibrary,'logger',Mock(),create=True):
            openlibrary.request('historia cultural',params)
        query=parse_qs(urlsplit(params['url']).query)
        self.assertEqual(query['limit'],['5'])
        fields=query['fields'][0].split(',')
        self.assertIn('first_sentence',fields)
        self.assertNotIn('isbn',fields)
        self.assertNotIn('publish_date',fields)

    def result(self, **values):
        document = {'key': '/works/OL123W', 'title': 'Obra controlada', **values}
        results = openlibrary.response(SimpleNamespace(json=lambda: {'docs': [document]}))
        container = ResultContainer()
        # Aquí fallaba la imagen original: list.strftime en normalize_result_fields.
        container.extend('openlibrary', results)
        return list(results)[0]

    def test_unparseable_dates_without_year_do_not_leave_a_list(self):
        result = self.result(publish_date=['sin fecha conocida'])
        self.assertIsNone(result.publishedDate)

    def test_unparseable_dates_fall_back_to_the_original_year(self):
        result = self.result(publish_date=['sin fecha conocida'], first_publish_year=1984)
        self.assertEqual(result.publishedDate.year, 1984)

    def test_valid_dates_are_still_preserved(self):
        result = self.result(publish_date=['2001', '1994'])
        self.assertIsInstance(result.publishedDate, datetime)
        self.assertEqual(result.publishedDate.year, 1994)

    def test_scalar_date_and_malformed_optional_fields_do_not_break_normalization(self):
        result = self.result(publish_date='1984', first_sentence=None, author_name=None, isbn=[None, '123'], subject={})
        self.assertEqual(result.publishedDate.year, 1984)
        self.assertEqual(result.authors, [])
        self.assertEqual(result.url, 'https://openlibrary.org/works/OL123W')

    def test_invalid_document_does_not_discard_a_valid_neighbour(self):
        payload = {'docs': [None, {'title': 'Invalid', 'key': 'https://127.0.0.1/'},
                            {'title': 'Valid', 'key': '/works/OL456W'}]}
        results = openlibrary.response(SimpleNamespace(json=lambda: payload))
        ResultContainer().extend('openlibrary', results)
        self.assertEqual(len(list(results)), 1)

    def test_malformed_envelope_is_an_error_not_an_empty_search(self):
        with self.assertRaises(ValueError):
            openlibrary.response(SimpleNamespace(json=lambda: {'docs': {}}))


if __name__ == '__main__':
    unittest.main()
