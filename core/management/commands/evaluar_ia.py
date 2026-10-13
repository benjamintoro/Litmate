"""Evaluación con el modelo REAL. Los criterios automáticos no dan una nota."""
import json
import re
import time
import unicodedata
from pathlib import Path
from datetime import datetime, timezone
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test.utils import override_settings
from core.literary_ai import build_assistant


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower())
                   if unicodedata.category(c) != 'Mn')


def check_result(case, result):
    failures = []
    if result.status not in case['expected_status']:
        failures.append('estado inesperado: ' + result.status)
    # Son anclas observables; una coincidencia no demuestra verdad ni calidad.
    body = normalized(result.text)
    for group in case.get('contains_any', []):
        if not any(normalized(word) in body for word in group):
            failures.append('falta mencionar: ' + ' / '.join(group))
    for word in case.get('must_not_contain', []):
        if normalized(word) in body:
            failures.append('contenido inesperado: ' + word)
    if case.get('requires_citations') and not result.sources:
        failures.append('faltan referencias recuperadas')
    if len(result.books) < case.get('min_books', 0):
        failures.append('faltan obras concretas con título y autor')
    if re.search(r'<(?:script|iframe|img)\b|javascript:\s*alert|```', result.text, re.I):
        failures.append('salida activa o código no permitido')
    if result.status in {'rejected', 'blocked_output'} and result.remember:
        failures.append('un rechazo no debe entrar al contexto aceptado')
    return failures


class Command(BaseCommand):
    help = 'Ejecuta casos reproducibles en Ollama local y guarda respuestas para revisión humana.'

    def add_arguments(self, parser):
        parser.add_argument('--live', action='store_true')
        parser.add_argument('--casos', default=str(Path(settings.BASE_DIR) / 'evaluacion_ia.json'))
        parser.add_argument('--salida', default=str(Path(settings.BASE_DIR) / 'reportes' / 'evaluacion_ia.json'))
        parser.add_argument('--limit', type=int, default=0)
        parser.add_argument('--id', default='')
        parser.add_argument('--modelo', default='')
        parser.add_argument('--sin-web', action='store_true')

    def handle(self, *args, **options):
        try:
            data = json.loads(Path(options['casos']).read_text(encoding='utf-8'))
            cases = data['cases']
            if not isinstance(cases, list) or not cases or len(cases) > 100:
                raise ValueError('Se requieren de 1 a 100 casos.')
            identifiers = set()
            for c in cases:
                if (not isinstance(c, dict) or not isinstance(c.get('id'), str) or c['id'] in identifiers
                        or not isinstance(c.get('message'), str) or not c['message'].strip()
                        or len(c['message']) > 6000 or not isinstance(c.get('expected_status'), list)
                        or not c['expected_status'] or not all(isinstance(s, str) for s in c['expected_status'])):
                    raise ValueError('Formato de caso inválido o ID duplicado.')
                groups = c.get('contains_any', [])
                if (not isinstance(groups, list) or any(not isinstance(g, list) or not g
                        or any(not isinstance(w, str) or not w for w in g) for g in groups)
                        or not isinstance(c.get('must_not_contain', []), list)
                        or any(not isinstance(w, str) for w in c.get('must_not_contain', []))
                        or type(c.get('min_books', 0)) is not int or not 0 <= c.get('min_books', 0) <= 5):
                    raise ValueError('Criterios del caso inválidos.')
                identifiers.add(c['id'])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CommandError('No se pudieron leer los casos: ' + str(exc)) from None
        if options['id']:
            cases = [c for c in cases if c['id'] == options['id']]
            if not cases:
                raise CommandError('No existe ese ID de caso.')
        if options['limit'] < 0:
            raise CommandError('--limit debe ser 0 o positivo.')
        if options['limit']:
            cases = cases[:options['limit']]
        if not options['live']:
            self.stdout.write(f'{len(cases)} casos preparados. Añade --live para usar tu Ollama local.')
            return
        config = {'LITMATE_AI_QUALITY_CHECKS': True}
        if options['modelo']:
            config.update(LITMATE_LOCAL_MODEL=options['modelo'], LITMATE_LOCAL_GUARD_MODEL=options['modelo'])
        if options['sin_web']:
            # Sin web implica también sin catálogos públicos en esta evaluación.
            config.update(LITMATE_AI_USE_WEB=False, LITMATE_AI_USE_SEARXNG=False,
                          LITMATE_AI_USE_OPENLIBRARY=False, LITMATE_USE_GOOGLE_BOOKS_API=False)
        rows = []
        with override_settings(**config):
            for case in cases:
                assistant, client = build_assistant(settings)
                started = time.monotonic()
                result = assistant.reply(case['message'], case.get('history', []))
                failures = check_result(case, result)
                rows.append({'id': case['id'], 'message': case['message'], 'status': result.status,
                    'response': result.text, 'sources': result.sources, 'books': result.books,
                    'model': assistant.answer_model, 'guard_model': assistant.guard_model,
                    'latency_ms': round((time.monotonic() - started) * 1000),
                    'provider_calls': client.calls, 'usage_local': client.usage,
                    'diagnostics': result.diagnostics, 'automated_checks_passed': not failures,
                    'failures': failures, 'manual_review_required': True,
                    'review_focus': case.get('review_focus', '')})
                self.stdout.write(case['id'] + ': ' + ('OK' if not failures else 'REVISAR')
                                  + ' (' + result.status + ')')
        report = {'created_at': datetime.now(timezone.utc).isoformat(),
            'kind': 'local_model_acceptance', 'mocked_inference': False,
            'notice': 'Estos criterios no certifican exactitud, seguridad absoluta ni una calificación.',
            'total': len(rows), 'passed': sum(r['automated_checks_passed'] for r in rows),
            'cases': rows}
        output = Path(options['salida'])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        self.stdout.write('Reporte con respuestas para revisión humana: ' + str(output))
        if report['passed'] != report['total']:
            raise CommandError(f'{report["total"] - report["passed"]} caso(s) requieren revisión. Consulta el reporte.')
