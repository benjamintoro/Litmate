"""Pruebas focalizadas de continuidad, borrado y presencia con cuentas sintéticas."""
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from core.literary_ai_views import HISTORY_KEY
from core.models import ConversacionIA, MensajeIA
from .models import QueryOperation, UsageBucket
from . import presence


class CurrentChatTests(TestCase):
    databases = {'accounts'}

    def setUp(self):
        self.user = User.objects.create_user('chat-owner', password='Synthetic-Only!')
        self.other = User.objects.create_user('chat-other', password='Synthetic-Only!')
        self.client.force_login(self.user)
        self.conversation = ConversacionIA.objects.create(usuario=self.user, titulo='Consulta sintética')
        MensajeIA.objects.create(conversacion=self.conversation, rol='user', contenido='Frankenstein')
        MensajeIA.objects.create(conversacion=self.conversation, rol='assistant', contenido='Mary Shelley')
        self.set_active(self.conversation)

    def set_active(self, conversation):
        session = self.client.session
        session[HISTORY_KEY] = {'owner': 'user:' + str(self.user.pk),
                               'conversation_id': conversation.pk, 'turns': []}
        session.save()

    def test_current_chat_is_restored_after_navigation(self):
        self.client.get('/about/')
        response = self.client.get('/api/chat/actual/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([m['text'] for m in response.json()['messages']], ['Frankenstein', 'Mary Shelley'])

    def test_foreign_chat_id_does_not_expose_messages(self):
        foreign = ConversacionIA.objects.create(usuario=self.other, titulo='PRIVATE')
        MensajeIA.objects.create(conversacion=foreign, rol='user', contenido='SECRET')
        self.set_active(foreign)
        self.assertEqual(self.client.get('/api/chat/actual/').json()['messages'], [])
        response = self.client.post('/api/chat/borrar/', {'confirm': 'delete-current-conversation',
                                                         'conversation_id': foreign.pk})
        self.assertEqual(response.status_code, 409)
        self.assertTrue(ConversacionIA.objects.filter(pk=foreign.pk).exists())

    def test_deletion_requires_confirmation_and_csrf(self):
        self.assertEqual(self.client.post('/api/chat/borrar/').status_code, 400)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post('/api/chat/borrar/', {'confirm': 'delete-current-conversation'}).status_code, 403)
        self.assertEqual(self.client.get('/api/chat/borrar/').status_code, 405)

    def operation(self, status):
        bucket = UsageBucket.objects.create(actor='u:' + str(self.user.pk), period='2026-11-11', used=3)
        operation = QueryOperation.objects.create(bucket=bucket, actor=bucket.actor, request_id=uuid4().hex,
            fingerprint='synthetic', status=status, result={'response': 'Mary Shelley'},
            expires_at=timezone.now() + timezone.timedelta(minutes=2))
        self.conversation.mensajes.filter(rol='user').update(metadata_json={'reader_operation': operation.pk})
        return operation, bucket

    def test_deletion_preserves_quota_and_other_conversations(self):
        operation, bucket = self.operation('completed')
        other = ConversacionIA.objects.create(usuario=self.user, titulo='Otro chat')
        response = self.client.post('/api/chat/borrar/', {'confirm': 'delete-current-conversation',
                                                         'conversation_id': self.conversation.pk})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ConversacionIA.objects.filter(pk=self.conversation.pk).exists())
        self.assertTrue(ConversacionIA.objects.filter(pk=other.pk).exists())
        self.assertEqual(self.client.get('/api/chat/actual/').json()['messages'], [])
        operation.refresh_from_db(); bucket.refresh_from_db()
        self.assertNotIn('Mary Shelley', str(operation.result))
        self.assertEqual(bucket.used, 3)
        self.assertNotIn(HISTORY_KEY, self.client.session)

    def test_pending_response_blocks_deletion(self):
        self.operation('pending')
        response = self.client.post('/api/chat/borrar/', {'confirm': 'delete-current-conversation',
                                                         'conversation_id': self.conversation.pk})
        self.assertEqual(response.status_code, 409)
        self.assertTrue(self.conversation.mensajes.exists())

    def test_stale_tab_cannot_delete_a_different_chat(self):
        response = self.client.post('/api/chat/borrar/', {'confirm': 'delete-current-conversation',
                                                         'conversation_id': '99999'})
        self.assertEqual(response.status_code, 409)

    def test_public_templates_have_no_search_button_or_team_photos(self):
        response = self.client.get('/about/')
        self.assertNotContains(response, 'id="navCmdSearchBtn"')
        self.assertNotContains(response, 'team-avatar-img')
        self.assertContains(response, 'René Muñoz')
        self.assertContains(response, 'id="litmate-online-count"')

    @override_settings(LITMATE_COMMUNITY_ENABLED=True)
    def test_json_heart_is_persistent_idempotent_and_removable(self):
        from .models import SocialPost, SocialProfile
        author = SocialProfile.objects.create(user=self.other, published=True)
        SocialProfile.objects.create(user=self.user, published=True)
        post = SocialPost.objects.create(author=author, submission_id=uuid4(), body='Lectura sintética', visibility='public')
        route = f'/comunidad/publicacion/{post.pk}/me-gusta/'
        for _ in range(2):
            response = self.client.post(route, {'action': 'add'}, HTTP_ACCEPT='application/json')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {'liked': True, 'count': 1})
        self.assertEqual(self.client.post(route, {'action': 'remove'}, HTTP_ACCEPT='application/json').json(),
                         {'liked': False, 'count': 0})


class PresenceTests(TestCase):
    databases = {'accounts'}

    def setUp(self):
        presence._seen.clear()
        self.client.get('/login/')  # Establece la cookie de visitante firmada.

    def test_count_deduplicates_tabs_and_expires(self):
        with patch('reader_accounts.presence.time.monotonic', return_value=100):
            self.assertEqual(self.client.post('/api/presencia/').json()['online'], 1)
            self.assertEqual(self.client.post('/api/presencia/').json()['online'], 1)
        other = Client(); other.get('/login/')
        with patch('reader_accounts.presence.time.monotonic', return_value=110):
            self.assertEqual(other.post('/api/presencia/').json()['online'], 2)
        with patch('reader_accounts.presence.time.monotonic', return_value=201):
            self.assertEqual(other.post('/api/presencia/').json()['online'], 1)

    def test_presence_requires_post_and_csrf(self):
        self.assertEqual(self.client.get('/api/presencia/').status_code, 405)
        self.assertEqual(Client(enforce_csrf_checks=True).post('/api/presencia/').status_code, 403)


class DemoCommunityTests(TestCase):
    databases = {'accounts'}

    def test_demo_seed_is_explicit_idempotent_and_identified(self):
        from .management.commands.seed_demo_community import seed_demo
        existing = User.objects.create_user('real-reader', email='private@example.invalid')
        original = existing.password
        first = seed_demo()
        self.assertEqual(first, {'synthetic_profiles': 30, 'posts': 30, 'comments': 60, 'likes': 90})
        self.assertEqual(seed_demo(), first)
        self.assertEqual(User.objects.count(), 31)
        self.assertTrue(all(not user.has_usable_password() for user in User.objects.filter(username__startswith='comunidad_demo_')))
        existing.refresh_from_db()
        self.assertEqual(existing.password, original)
