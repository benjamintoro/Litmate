"""Inferencia exclusivamente local: ninguna clave ni proveedor de pago."""
import json
import re
import copy
import time
from urllib.error import HTTPError, URLError
from .ai_http import local_origin, read_json_url
from .literary_ai import (ANSWER_SCHEMA, REVIEW_SCHEMA, ROUTE_SCHEMA,
                          ProviderUnavailable)
from .literary_quality import PLAN_SCHEMA, AUDIT_SCHEMA, character_names, evidence_words
from .ai_budget import BudgetExpired


class OllamaJSON:
    provider = 'ollama-local'

    def __init__(self, base_url='http://127.0.0.1:11434', *, timeout=240,
                 context=16384, thinking=False, answer_tokens=2048, total_timeout=300):
        self.base_url = base_url
        self.timeout = max(30, min(int(timeout), 600))
        self.context = max(8192, min(int(context), 32768))
        self.thinking = thinking is True
        self.answer_tokens = max(1024, min(int(answer_tokens), 4096))
        self.deadline = time.monotonic() + max(60, min(int(total_timeout), 600))
        self.usage = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
        self.calls = 0
        self.last_error = ''
        self._models = {}
        self.stage_timings = []

    def _remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ProviderUnavailable('tiempo_total_agotado')
        return max(0.1, min(self.timeout, remaining))

    def _fit_context(self, prompt, data, output_tokens):
        context = copy.deepcopy(data)
        # Estimación conservadora para español; Ollama no expone aquí un tokenizer.
        limit = min(30000, int((self.context - output_tokens - 700) * 2.5))
        def size():
            return len(prompt) + len(json.dumps(context, ensure_ascii=False, separators=(',', ':')))
        history = context.get('accepted_history') if isinstance(context, dict) else None
        if isinstance(history, list):
            for turn in history:
                if isinstance(turn, dict):
                    turn['sources'] = []  # Las fuentes actuales están en context.sources.
            while len(history) > 1 and size() > limit:
                history.pop(0)
        sources = context.get('sources') if isinstance(context, dict) else None
        if isinstance(sources, list):
            for source in sources:
                if isinstance(source, dict):
                    # La portada y los enlaces pertenecen a la interfaz, no al prompt.
                    if not source.get('description') and source.get('synopsis'):
                        source['description'] = source['synopsis']
                    for field in ('image_url', 'synopsis', 'preview_url', 'read_url', 'retrieved_at'):
                        source.pop(field, None)
        if size() > limit and isinstance(sources, list):
            for maximum in (750, 500, 300):
                for source in sources:
                    if isinstance(source, dict) and source.get('kind') != 'excerpt':
                        source['description'] = str(source.get('description', ''))[:maximum]
                if size() <= limit:
                    break
        # Nunca corta el mensaje, las citas originales ni el borrador que será revisado.
        if size() > limit:
            raise ProviderUnavailable('contexto_demasiado_extenso')
        return json.dumps(context, ensure_ascii=False, separators=(',', ':'))

    def inspect_model(self, model):
        if (not isinstance(model, str)
                or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,100}', model)
                or 'cloud' in model.lower() or '://' in model or '..' in model):
            raise ProviderUnavailable('modelo_local_invalido')
        if model in self._models:
            return self._models[model]
        try:
            origin = local_origin(self.base_url)
            info = read_json_url(origin + '/api/show', payload={'model': model},
                headers={'Content-Type': 'application/json'}, timeout=min(15, self._remaining()), local=True)
            details = info.get('details') or {}
            metadata = info.get('model_info') or {}
            if (info.get('remote_model') or info.get('remote_host')
                    or details.get('remote_model') or details.get('remote_host')
                    or 'cloud' in (info.get('capabilities') or [])
                    or details.get('format') != 'gguf'
                    or not metadata.get('general.architecture')):
                raise ProviderUnavailable('se_requiere_modelo_descargado_localmente')
            if 'completion' not in (info.get('capabilities') or []):
                raise ProviderUnavailable('modelo_sin_chat')
            self._models[model] = info
            return info
        except HTTPError as exc:
            raise ProviderUnavailable('modelo_no_descargado' if exc.code == 404
                                      else 'ollama_no_disponible') from None
        except ProviderUnavailable:
            raise
        except BudgetExpired:
            raise ProviderUnavailable('tiempo_total_agotado') from None
        except (ValueError, TypeError, AttributeError):
            raise ProviderUnavailable('configuracion_local_invalida') from None
        except (URLError, OSError, TimeoutError):
            raise ProviderUnavailable('ollama_no_iniciado') from None

    def __call__(self, stage, prompt, data, model):
        started = time.monotonic()
        status = 'failed'
        try:
            result = self._generate(stage, prompt, data, model)
            status = 'ok'
            return result
        finally:
            self.stage_timings.append({'stage': stage, 'model': model,
                'elapsed_ms': round((time.monotonic() - started) * 1000), 'status': status})

    def _generate(self, stage, prompt, data, model):
        try:
            self._remaining()
            info = self.inspect_model(model)
            answer_stage = stage in {'answer', 'repair', 'answer_web'}
            schema = (ANSWER_SCHEMA if answer_stage else AUDIT_SCHEMA if stage == 'audit'
                      else PLAN_SCHEMA if stage == 'plan' else REVIEW_SCHEMA if stage == 'review' else ROUTE_SCHEMA)
            if answer_stage and isinstance(data, dict):
                schema = copy.deepcopy(schema)
                ids = [s['id'] for s in data.get('sources', []) if isinstance(s, dict) and type(s.get('id')) is int]
                schema['properties']['citations']['items'] = {'type': 'integer', 'enum': ids} if ids else {'type': 'integer'}
                if not ids:
                    schema['properties']['citations']['maxItems'] = 0
                book_ids = [s['id'] for s in data.get('sources', []) if isinstance(s, dict)
                            and s.get('kind') in {'book', 'excerpt'} and type(s.get('id')) is int]
                if not data.get('require_book_sources'):
                    book_ids = [0] + book_ids
                if book_ids:
                    schema['properties']['books']['items']['properties']['source_id']['enum'] = book_ids
                if data.get('require_book_sources') or data.get('ground_book_identity'):
                    identities = [s for s in data.get('sources', []) if isinstance(s, dict)
                                  and s.get('kind') in {'book', 'excerpt'}]
                    # Restringir cada campo por separado permite mezclar el título
                    # de una ficha con el autor/ID de otra. Cada alternativa mantiene
                    # unida la identidad completa; no se mezcla anyOf con properties.
                    alternatives = []
                    for source in identities:
                        if all(isinstance(source.get(name), str) for name in ('title', 'author')):
                            alternatives.append({
                                'type': 'object', 'properties': {
                                    'title': {'type': 'string', 'const': source['title']},
                                    'author': {'type': 'string', 'const': source['author']},
                                    'source_id': {'type': 'integer', 'const': source['id']},
                                }, 'required': ['title', 'author', 'source_id'],
                                'additionalProperties': False,
                            })
                    if alternatives:
                        schema['properties']['books']['items'] = {'anyOf': alternatives}
            if stage == 'audit' and isinstance(data, dict):
                schema = copy.deepcopy(schema)
                draft_text = str((data.get('draft') or {}).get('text', ''))
                statements = [part.strip()[:400] for part in re.split(r'(?<=[.!?])\s+|\n', draft_text)
                              if len(part.strip()) >= 8][:24]
                evidence_by_source = {}
                cited = set((data.get('draft') or {}).get('citations', []))
                for source in data.get('sources', []):
                    if isinstance(source, dict) and source.get('id') in cited:
                        evidence = []
                        for name in ('title', 'author', 'description'):
                            value = str(source.get(name, ''))
                            if len(value.strip()) >= 8:
                                evidence.extend(value[start:start + 300] for start in range(0, min(len(value), 1800), 250)
                                                if len(value[start:start + 300].strip()) >= 8)
                        if evidence:
                            evidence_by_source[source['id']] = list(dict.fromkeys(evidence))
                from .ai_privacy import user_excerpt
                excerpt = user_excerpt(data.get('message', ''))
                if excerpt:
                    evidence_by_source[0] = [excerpt[start:start + 300] for start in range(0, min(len(excerpt), 1200), 250)
                                             if len(excerpt[start:start + 300].strip()) >= 8]
                statement_schema = {'type': 'string'}
                if statements:
                    statement_schema['enum'] = list(dict.fromkeys(statements))
                alternatives = []
                for identifier, evidence in evidence_by_source.items():
                    groups = [(statement_schema, evidence)]
                    if data.get('facts_only') and statements:
                        groups = []
                        for statement in statement_schema['enum']:
                            names = character_names(statement)
                            proofs = [proof for proof in evidence if not names or names <= evidence_words(proof)]
                            if proofs:
                                groups.append(({'type': 'string', 'const': statement}, proofs))
                    for claim_statement, proofs in groups:
                        alternatives.append({'type': 'object', 'properties': {
                            'statement': copy.deepcopy(claim_statement),
                            'verdict': {'type': 'string', 'const': 'supported'},
                            'source_id': {'type': 'integer', 'const': identifier},
                            'evidence': {'type': 'string', 'enum': proofs},
                        }, 'required': ['statement', 'verdict', 'source_id', 'evidence'],
                            'additionalProperties': False})
                alternatives.append({'type': 'object', 'properties': {
                    'statement': copy.deepcopy(statement_schema),
                    'verdict': {'type': 'string', 'enum': ['inference', 'unverified', 'contradicted']},
                    'source_id': {'type': 'integer', 'enum': list(dict.fromkeys([0] + list(cited)))},
                    'evidence': {'type': 'string', 'const': ''},
                }, 'required': ['statement', 'verdict', 'source_id', 'evidence'],
                    'additionalProperties': False})
                schema['properties']['claims']['items'] = {'anyOf': alternatives}
                schema['properties']['claims']['maxItems'] = 6
                question_count = len((data.get('plan') or {}).get('questions', []))
                if question_count:
                    schema['properties']['coverage'].update(minItems=question_count, maxItems=question_count)
                    schema['properties']['coverage']['items']['properties']['question_id']['enum'] = list(range(1, question_count + 1))
            output_tokens = self.answer_tokens if answer_stage else 2048 if stage == 'audit' else 1024
            content = self._fit_context(prompt, data, output_tokens)
            payload = {
                'model': model, 'stream': False, 'format': schema, 'keep_alive': '10m',
                'messages': [{'role': 'system', 'content': prompt},
                             {'role': 'user', 'content': content}],
                'options': {'temperature': 0.1 if answer_stage else 0,
                            'num_ctx': self.context,
                            'num_predict': output_tokens},
            }
            if 'thinking' in (info.get('capabilities') or []):
                payload['think'] = self.thinking if answer_stage else False
            self.calls += 1
            result = read_json_url(local_origin(self.base_url) + '/api/chat',
                payload=payload, headers={'Content-Type': 'application/json'},
                timeout=self._remaining(), local=True)
            prompt_tokens, completion_tokens = result.get('prompt_eval_count', 0), result.get('eval_count', 0)
            if type(prompt_tokens) is int and prompt_tokens >= 0:
                self.usage['prompt_tokens'] += prompt_tokens
            if type(completion_tokens) is int and completion_tokens >= 0:
                self.usage['completion_tokens'] += completion_tokens
            self.usage['total_tokens'] = self.usage['prompt_tokens'] + self.usage['completion_tokens']
            if result.get('done') is not True or result.get('done_reason') != 'stop':
                raise ProviderUnavailable('respuesta_local_incompleta')
            raw = (result.get('message') or {}).get('content', '')
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError('Respuesta JSON inválida')
            return parsed
        except ProviderUnavailable as exc:
            self.last_error = exc.code
            raise
        except BudgetExpired:
            self.last_error = 'tiempo_total_agotado'
            raise ProviderUnavailable(self.last_error) from None
        except HTTPError as exc:
            self.last_error = {404: 'modelo_no_descargado', 503: 'ollama_ocupado',
                               400: 'actualiza_ollama_o_revisa_modelo'}.get(exc.code, 'ollama_no_disponible')
            raise ProviderUnavailable(self.last_error) from None
        except (URLError, OSError, TimeoutError, ValueError, TypeError, KeyError, AttributeError):
            self.last_error = 'ollama_sin_respuesta_valida'
            raise ProviderUnavailable(self.last_error) from None
