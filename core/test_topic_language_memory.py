"""La preferencia de idioma sobrevive a continuaciones sin copiar texto privado."""
from django.test import SimpleTestCase

from .literary_conversation import remember_topic, resolve_topic_context


class TopicLanguageMemoryTests(SimpleTestCase):
    def state(self, message='Recomiéndame libros sobre arte japonés'):
        state = {'turns': []}
        remember_topic(state, message, now=1000)
        return state

    def resolve_and_remember(self, state, message, now=1001):
        context = resolve_topic_context(message, state, now=now)
        remember_topic(state, message, context, now=now)
        return context

    def test_language_adjustment_survives_the_next_elliptical_recommendation(self):
        state = self.state()
        self.resolve_and_remember(state, 'Prefiero en español')
        context = resolve_topic_context('Recomiéndame otros', state, now=1002)
        self.assertEqual(state['topic']['subject'], 'arte japonés')
        self.assertEqual(state['topic']['language'], 'es')
        self.assertIn('en español', context['query'])
        self.assertEqual(context['language'], 'es')
        self.assertEqual(state['turns'], [])

    def test_each_supported_language_can_replace_the_previous_preference(self):
        for code, label in [('es', 'español'), ('en', 'inglés'), ('fr', 'francés'),
                            ('de', 'alemán'), ('pt', 'portugués'), ('ja', 'japonés')]:
            with self.subTest(language=code):
                state = self.state('Recomiéndame libros sobre arte japonés en español')
                context = self.resolve_and_remember(state, 'Ahora en ' + label)
                self.assertEqual(context['language'], code)
                self.assertEqual(state['topic']['language'], code)
                self.assertEqual(context['query'].count('en '), 1)
                following = resolve_topic_context('Recomiéndame otros', state, now=1002)
                self.assertIn('en ' + label, following['query'])

    def test_a_language_given_with_the_subject_is_not_part_of_the_subject(self):
        state = self.state('Recomiéndame libros sobre historia de Corea en español')
        self.assertEqual(state['topic']['subject'], 'historia de Corea')
        self.assertEqual(state['topic']['language'], 'es')
        context = resolve_topic_context('Recomiéndame libros sobre historia de Corea', state, now=1001)
        self.assertIn('en español', context['query'])

    def test_articles_do_not_make_the_same_subject_drop_its_language(self):
        state = self.state('Recomiéndame libros sobre la historia de Corea en español')
        context = resolve_topic_context('Recomiéndame libros sobre historia de Corea', state, now=1001)
        self.assertEqual(context['language'], 'es')
        self.assertIn('en español', context['query'])

    def test_a_short_polite_language_adjustment_keeps_the_subject(self):
        state = self.state()
        context = self.resolve_and_remember(state, 'En inglés, por favor')
        self.assertTrue(context['followup'])
        self.assertEqual(state['topic']['language'], 'en')
        self.assertEqual(context['subject'], 'arte japonés')

    def test_an_explicit_new_subject_clears_the_previous_language(self):
        state = self.state('Recomiéndame libros sobre historia de Corea en español')
        context = self.resolve_and_remember(state, 'Recomiéndame libros sobre astronomía')
        self.assertTrue(context['explicit_change'])
        self.assertNotIn('language', state['topic'])
        self.assertNotIn('español', context['query'])

    def test_a_new_subject_can_set_its_own_language(self):
        state = self.state('Recomiéndame libros sobre historia de Corea en español')
        context = self.resolve_and_remember(state, 'Recomiéndame libros sobre astronomía en francés')
        self.assertEqual(state['topic']['language'], 'fr')
        self.assertIn('en francés', context['query'])
        self.assertNotIn('español', context['query'])

    def test_returning_to_a_subject_restores_only_its_own_preference(self):
        state = self.state('Recomiéndame libros sobre historia de Corea en español')
        self.resolve_and_remember(state, 'Recomiéndame libros sobre arte japonés en inglés')
        context = resolve_topic_context('Volvamos a Corea', state, now=1002)
        self.assertEqual(context['language'], 'es')
        self.assertIn('en español', context['query'])
        self.assertNotIn('inglés', context['query'])
        changed = resolve_topic_context('Volvamos a Corea en francés', state, now=1002)
        self.assertEqual(changed['language'], 'fr')
        self.assertIn('en francés', changed['query'])

    def test_old_subject_only_sessions_do_not_repeat_two_conflicting_languages(self):
        state = {'turns': [], 'topic': {'subject': 'arte japonés en español',
                 'intent': 'recommend', 'updated_at': 1000}}
        context = self.resolve_and_remember(state, 'Ahora en inglés')
        self.assertEqual(state['topic']['subject'], 'arte japonés')
        self.assertEqual(state['topic']['language'], 'en')
        self.assertNotIn('español', context['query'])

    def test_only_the_language_enum_can_enter_memory(self):
        for invalid in ('https://private.example/secret', 'es secreto123', ['es'],
                        {'secret': 'abc'}, True):
            with self.subTest(value=invalid):
                state = self.state()
                context = {'subject': 'arte japonés', 'intent': 'recommend', 'language': invalid}
                remember_topic(state, '', context, now=1001)
                self.assertNotIn('language', state['topic'])
                self.assertNotIn('secret', str(state))

    def test_a_private_adjustment_keeps_only_the_safe_language_code(self):
        state = self.state()
        context = self.resolve_and_remember(state, 'Prefiero en inglés; mi contraseña es secreto123')
        self.assertEqual(context['language'], 'en')
        self.assertEqual(set(state['topic']), {'subject', 'intent', 'updated_at', 'language'})
        self.assertNotIn('secreto123', str(state))
        self.assertNotIn('contraseña', context['query'])

    def test_japanese_art_does_not_imply_a_japanese_language_edition(self):
        state = self.state()
        self.assertNotIn('language', state['topic'])
        context = resolve_topic_context('Recomiéndame otros', state, now=1001)
        self.assertNotIn('language', context)
        self.assertNotIn('en japonés', context['query'])
