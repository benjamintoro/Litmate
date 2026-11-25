"""Regresiones dirigidas de contacto y persistencia, con usuarios sintéticos."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import DatabaseError
from django.test import Client, RequestFactory, TestCase, override_settings

from core.models import MensajeContacto, MensajeIA, ConversacionIA
from core.literary_ai import ChatResult
from core.literary_ai_views import HISTORY_KEY, persist_turn_records
from reader_accounts.chat_history import record_input, contains_secret
from reader_accounts.usage import reserve, finish


class ContactRestoreTests(TestCase):
    databases = {'accounts'}

    def setUp(self):
        folder = self.enterContext(TemporaryDirectory(dir=Path.cwd()/'.testtmp'))
        self.enterContext(override_settings(LITMATE_AI_RUNTIME_DB=Path(folder)/'runtime.sqlite3'))
        cache.clear()

    def test_original_fields_are_reachable(self):
        response = self.client.get('/contact/')
        self.assertEqual(response.status_code, 200)
        for field in ('name', 'email', 'phone', 'message'):
            self.assertContains(response, 'name="' + field + '"')
        self.assertContains(response, 'bandeja privada')

    def test_valid_message_is_saved_in_accounts_without_email(self):
        with patch('core.views.send_mail') as mail:
            response = self.client.post('/contact/', {
                'name':'Lector sintético', 'email':'reader@example.invalid',
                'phone':'', 'message':'Una consulta literaria de prueba',
            }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'quedó registrado')
        self.assertEqual(MensajeContacto.objects.count(), 1)
        self.assertEqual(MensajeContacto.objects.first()._state.db, 'accounts')
        mail.assert_not_called()

    def test_bad_email_is_rejected_and_values_preserved(self):
        response = self.client.post('/contact/', {'name':'Lector', 'email':'incorrecto', 'message':'Conservar este texto'})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'Conservar este texto', status_code=400)
        self.assertFalse(MensajeContacto.objects.exists())

    def test_database_error_does_not_show_success(self):
        with patch('reader_accounts.contact.MensajeContacto.objects.create', side_effect=DatabaseError('PRIVATE DB')):
            response = self.client.post('/contact/', {'name':'Lector', 'email':'a@example.invalid', 'message':'Mensaje'})
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, 'quedó registrado', status_code=503)
        self.assertNotContains(response, 'PRIVATE DB', status_code=503)

    def test_honeypot_does_not_fake_success(self):
        response = self.client.post('/contact/', {'name':'Bot', 'email':'bot@example.invalid', 'message':'Mensaje', 'website':'spam'})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(MensajeContacto.objects.exists())

    def test_csrf_and_http_method(self):
        self.assertEqual(Client(enforce_csrf_checks=True).post('/contact/', {}).status_code, 403)
        self.assertEqual(self.client.put('/contact/', '{}', content_type='application/json').status_code, 405)


class ChatHistoryRestoreTests(TestCase):
    databases = {'accounts'}

    def setUp(self):
        self.user = User.objects.create_user('history-synthetic', password='Synthetic-Only-Password!')
        self.other = User.objects.create_user('history-other', password='Synthetic-Only-Password!')
        from suscripciones.models import PlanSuscripcion, SuscripcionUsuario
        plan = PlanSuscripcion.objects.create(nombre='Gratuito', slug='gratis', precio=0, limite_consultas_ia_diarias=15)
        SuscripcionUsuario.objects.create(usuario=self.user, plan=plan, estado='activa')
        self.request = RequestFactory().post('/chatbot_query/')
        self.request.user = self.user
        self.request.session = self.client.session
        self.message = '¿Quién escribió Frankenstein?'
        self.op, _ = reserve('u:'+str(self.user.pk), self.user, uuid4().hex, self.message)
        self.client_info = SimpleNamespace(usage={},provider='synthetic',calls=0)

    def test_input_is_saved_before_generation_and_retry_is_unique(self):
        record_input(self.request,self.op,self.message)
        record_input(self.request,self.op,self.message)
        self.assertEqual(MensajeIA.objects.count(),1)
        self.assertEqual(ConversacionIA.objects.first().usuario_id,self.user.pk)
        self.assertEqual(ConversacionIA.objects.first().total_mensajes,1)

    def test_completed_response_appends_once_to_the_existing_input(self):
        record_input(self.request,self.op,self.message)
        state=self.request.session[HISTORY_KEY]
        self.request.reader_operation_id=self.op.pk
        answer=ChatResult('Mary Shelley.','answered',True,intent='author')
        persist_turn_records(self.request,state,self.message,answer,1,self.client_info)
        persist_turn_records(self.request,state,self.message,answer,1,self.client_info)
        finish(self.op.pk,{'response':answer.text})
        self.assertEqual(MensajeIA.objects.count(),2)
        self.assertEqual(ConversacionIA.objects.first().total_mensajes,2)
        self.assertEqual(MensajeIA.objects.get(rol='user').metadata_json['delivery_status'],'completed')

    def test_generation_failure_keeps_the_question_without_partial_answer(self):
        record_input(self.request,self.op,self.message)
        finish(self.op.pk,{'error':'technical_failure'},failed=True)
        self.assertEqual(MensajeIA.objects.count(),1)
        self.assertEqual(MensajeIA.objects.first().contenido,self.message)
        self.assertEqual(MensajeIA.objects.first().metadata_json['delivery_status'],'failed')

    def test_foreign_conversation_is_not_reused(self):
        conv=ConversacionIA.objects.create(usuario=self.other,titulo='Privado')
        self.request.session[HISTORY_KEY]={'owner':'user:'+str(self.other.pk),'conversation_id':conv.pk,'turns':[]}
        record_input(self.request,self.op,self.message)
        self.assertEqual(MensajeIA.objects.first().conversacion.usuario_id,self.user.pk)
        self.client.force_login(self.other)
        own=MensajeIA.objects.first().conversacion_id
        self.assertEqual(self.client.get(f'/cuenta/conversaciones/{own}/').status_code,404)

    def test_explicit_secrets_are_rejected_without_rejecting_literature(self):
        for text in ('mi contraseña es secreto-real','api_key=privado','Bearer abcdefghijklmnopqrstuvwxyz'):
            self.assertTrue(contains_secret(text))
        self.assertFalse(contains_secret('¿Quién escribió El secreto?'))
        self.client.force_login(self.user)
        response=self.client.post('/chatbot_query/',json.dumps({'message':'password=secreto','request_id':uuid4().hex}),content_type='application/json')
        self.assertEqual(response.status_code,400)
        self.assertFalse(MensajeIA.objects.exists())

    def test_missing_session_state_reuses_recorded_conversation(self):
        record_input(self.request, self.op, self.message)
        self.request.reader_operation_id = self.op.pk
        state = {}
        persist_turn_records(self.request, state, self.message,
                             ChatResult('Mary Shelley.', 'answered', True), 1, self.client_info)
        self.assertEqual(ConversacionIA.objects.count(), 1)
        self.assertEqual(MensajeIA.objects.count(), 2)

    def test_storage_error_is_reported_when_reservation_cannot_be_finished(self):
        self.client.force_login(self.user)
        with patch('reader_accounts.chat_history.record_input', side_effect=DatabaseError), \
                patch('reader_accounts.chat.finish', side_effect=DatabaseError):
            response = self.client.post('/chatbot_query/', json.dumps({
                'message': self.message, 'request_id': uuid4().hex,
            }), content_type='application/json')
        self.assertEqual(response.status_code, 503)
        self.assertFalse(MensajeIA.objects.exists())

    def test_local_greeting_is_also_saved_without_a_partial_response(self):
        self.client.force_login(self.user)
        response = self.client.post('/chatbot_query/', json.dumps({
            'message': 'Hola', 'request_id': uuid4().hex,
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        b''.join(response.streaming_content)
        self.assertEqual(MensajeIA.objects.filter(rol='user').count(), 1)
        self.assertEqual(MensajeIA.objects.filter(rol='assistant').count(), 1)
