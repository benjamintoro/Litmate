"""Explicit published variants, never a prefix guessed from a saga title."""
from django.test import SimpleTestCase
from .literary_identity import same_work
from .literary_search import _wikipedia_page_rank


def page(title='El viajero o La ruta del norte', alias='El viajero'):
    url = 'https://es.wikipedia.org/wiki/El_viajero_o_La_ruta_del_norte'
    return {'title': title, 'kind': 'web', 'source': 'Wikipedia', 'author': 'Fuente web',
            'url': url, 'license': 'CC-BY-SA-4.0',
            'identity_text': title + ', o simplemente ' + alias + ' (título abreviado), es una novela de Ana Escritora.',
            'attribution': {'authors': 'Wikipedia contributors', 'url': url, 'title': title,
                            'revision_id': '123', 'license_url': 'https://creativecommons.org/licenses/by-sa/4.0/'}}


class PublishedTitleAliasTests(SimpleTestCase):
    def test_explicit_alternative_is_bound_with_same_author(self):
        self.assertTrue(same_work(page(), {'title': 'El viajero', 'author': 'Ana Escritora'}))

    def test_prefix_of_declared_variant_is_not_an_alias(self):
        self.assertFalse(same_work(page(alias='El viajero II'), {'title': 'El viajero', 'author': 'Ana Escritora'}))

    def test_wrong_author_and_unattributed_alias_remain_unbound(self):
        self.assertFalse(same_work(page(), {'title': 'El viajero', 'author': 'Otra Autora'}))
        unverified = page()
        unverified.pop('attribution')
        self.assertFalse(same_work(unverified, {'title': 'El viajero', 'author': 'Ana Escritora'}))

    def test_publication_type_prevents_year_only_adaptation_from_winning(self):
        novel = {'title': 'El viajero o La ruta del norte', 'extract': 'El viajero es una obra literaria de Ana Escritora.'}
        film = {'title': 'El viajero (1910)', 'extract': 'El viajero es un cortometraje basado en la novela de Ana Escritora.'}
        self.assertGreater(_wikipedia_page_rank(novel, 'El viajero', ('trama',)),
                           _wikipedia_page_rank(film, 'El viajero', ('trama',)))
