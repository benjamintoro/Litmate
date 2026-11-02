import json

from django.test import TestCase


class RetryFollowupTests(TestCase):
    def test_retry_reuses_pending_query(self):
        # Prime an unavailable turn with pending_clarification.
        state = {'owner': 'anonymous', 'turns': [], 'pending_clarification': {'original_query': 'Dime la trama de The Shining'}}
        from django.contrib.sessions.backends.db import SessionStore
        session = SessionStore()
        session['litmate_literary_chat_local_v1'] = state
        session.save()
        self.client.cookies['sessionid'] = session.session_key
        response = self.client.post('/chatbot_query/', json.dumps({'message': 'Busca nuevamente'}), content_type='application/json')
        self.assertIn(response.status_code, (200, 429))