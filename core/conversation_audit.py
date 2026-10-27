"""Planificación y comprobaciones observables de conversaciones de prueba.

No llama a un LLM para calificarse. Una mención correcta o ``answered`` no
certifica todas las afirmaciones: las dimensiones sin evidencia quedan en null.
Los oráculos son controles parciales declarados, con referencias independientes.
"""
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import unicodedata

VERSION = 'conversation-audit-v1'
DIMENSIONS = ('factualidad', 'relevancia', 'completitud', 'coherencia', 'contexto',
              'fuentes', 'naturalidad', 'concisión', 'latencia', 'incertidumbre')
DEFAULT_LIMITS = {'conversations': 3, 'turns': 30, 'seconds': 900}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def normal(value):
    value = ''.join(character for character in unicodedata.normalize('NFKD', str(value).casefold())
                    if not unicodedata.combining(character))
    return re.sub(r'\s+', ' ', value).strip()


def contains(value, phrase):
    return bool(re.search(r'(?<!\w)' + re.escape(normal(phrase)) + r'(?!\w)', normal(value)))


def validate_bank(bank):
    if not isinstance(bank, dict) or bank.get('version') != 1:
        raise ValueError('El banco requiere version: 1.')
    cases = bank.get('cases')
    if not isinstance(cases, list) or not 1 <= len(cases) <= 100:
        raise ValueError('El banco debe contener entre una y cien conversaciones.')
    identifiers = set()
    for case in cases:
        if (not isinstance(case, dict) or not re.fullmatch(r'[a-z0-9_-]{1,80}', case.get('id', ''))
                or case['id'] in identifiers or case.get('mode') != 'live'
                or case.get('level') not in {1, 2, 3, 4}
                or not isinstance(case.get('messages'), list) or not 1 <= len(case['messages']) <= 30):
            raise ValueError('Conversación inválida, duplicada o fuera de límites.')
        identifiers.add(case['id'])
        for item in case['messages']:
            if not isinstance(item, dict) or not isinstance(item.get('text'), str) or not 1 <= len(item['text']) <= 1200:
                raise ValueError('Cada turno requiere una pregunta de hasta 1200 caracteres.')
            variants = item.get('variants', [])
            if (not isinstance(variants, list) or len(variants) > 8
                    or any(not isinstance(value, str) or not 1 <= len(value) <= 1200 for value in variants)):
                raise ValueError('Variantes inválidas.')
            conditional = item.get('if_previous')
            if conditional is not None and (not isinstance(conditional, dict)
                    or conditional.get('status') not in {'answered', 'clarification', 'unavailable', 'refused'}
                    or not isinstance(conditional.get('text'), str) or not 1 <= len(conditional['text']) <= 1200):
                raise ValueError('Seguimiento condicional inválido.')
            oracle = item.get('oracle', {})
            if not isinstance(oracle, dict):
                raise ValueError('Oráculo inválido.')
            references = oracle.get('references', [])
            if (not isinstance(references, list) or len(references) > 8
                    or any(not isinstance(url, str) or not url.startswith('https://') for url in references)):
                raise ValueError('La evidencia de referencia debe contener URLs públicas HTTPS.')
            for key in ('required_any', 'required_all'):
                groups = oracle.get(key, [])
                if not isinstance(groups, list) or len(groups) > 15:
                    raise ValueError('Controles léxicos fuera de límite.')
                if any(not isinstance(group, list) or not group or len(group) > 10
                       or any(not isinstance(label, str) or not 1 <= len(label) <= 150 for label in group)
                       for group in groups):
                    raise ValueError('Cada control debe declarar alternativas textuales limitadas.')
            patterns = oracle.get('forbidden_assertions', [])
            if not isinstance(patterns, list) or len(patterns) > 10:
                raise ValueError('Controles de contradicción fuera de límite.')
            for value in patterns:
                if not isinstance(value, str) or len(value) > 300:
                    raise ValueError('Patrón de contradicción inválido.')
                re.compile(value)
    return bank


def load_bank(path):
    path = Path(path)
    if path.stat().st_size > 2_000_000:
        raise ValueError('Banco demasiado grande.')
    return validate_bank(json.loads(path.read_text(encoding='utf-8-sig')))


def select_cases(bank, *, cases=(), maximum=3, completed=()):
    validate_bank(bank)
    if type(maximum) is not int or not 1 <= maximum <= 30:
        raise ValueError('Máximo de conversaciones entre 1 y 30.')
    by_id = {case['id']: case for case in bank['cases']}
    wanted = list(cases) or list(bank.get('default_cases', []))
    if not wanted:
        wanted = list(by_id)
    if len(wanted) != len(set(wanted)) or any(identifier not in by_id for identifier in wanted):
        raise ValueError('Conversaciones desconocidas o duplicadas.')
    return [by_id[identifier] for identifier in wanted if identifier not in set(completed)][:maximum]


def pick_message(case, index, item, previous, *, seed):
    conditional = item.get('if_previous')
    if previous and conditional and previous[-1].get('status') == conditional['status']:
        return conditional['text']
    variants = [item['text'], *item.get('variants', [])]
    number = int(fingerprint([seed, case['id'], index])[:16], 16)
    return variants[number % len(variants)]


def _score(value=None, basis='Requiere revisión independiente; no se infiere del estado HTTP.'):
    return {'score': value, 'basis': basis}


def evaluate_turn(row, item, *, trace=None):
    """Controles parciales, sin alterar respuesta, afirmaciones ni fragmentos."""
    answer = row.get('answer', '')
    oracle = item.get('oracle', {})
    status = row.get('status')
    scores = {dimension: _score() for dimension in DIMENSIONS}
    findings, checks = [], []
    completed = row.get('http_status') == 200 and row.get('completed_sse') is True
    if not completed:
        findings.append({'code': 'incomplete_transport', 'severity': 'high',
                         'evidence': {'http_status': row.get('http_status'), 'completed_sse': row.get('completed_sse')}})
    seconds = row.get('seconds')
    if type(seconds) in {int, float} and math.isfinite(seconds) and seconds >= 0:
        score = 5 if seconds <= 5 else 4 if seconds <= 10 else 3 if seconds <= 30 else 2 if seconds <= 45 else 1 if seconds <= 90 else 0
        scores['latencia'] = _score(score, f'{seconds:.3f} s medidos en HTTP/SSE; no mide exactitud.')
        if seconds > 30:
            findings.append({'code': 'latency_over_30s', 'severity': 'medium', 'evidence': seconds})
    expectations = oracle.get('expected_statuses', ['answered'])
    if status not in expectations:
        findings.append({'code': 'unexpected_status', 'severity': 'high',
                         'evidence': {'expected': expectations, 'observed': status}})
    required = oracle.get('required_all', [])
    required_any = oracle.get('required_any', [])
    for alternatives in required:
        matched = [label for label in alternatives if contains(answer, label)]
        checks.append({'kind': 'required_concept', 'alternatives': alternatives, 'matched': matched,
                       'passed': bool(matched), 'scope': 'mention_only_not_factual_certification'})
    if required_any:
        matched = [label for alternatives in required_any for label in alternatives if contains(answer, label)]
        checks.append({'kind': 'at_least_one_concept', 'alternatives': required_any,
                       'matched': matched, 'passed': bool(matched), 'scope': 'mention_only_not_factual_certification'})
    if checks:
        count = sum(check['passed'] for check in checks)
        if status == 'answered':
            scores['relevancia'] = _score(4 if count == len(checks) else 2 if count else 0,
                f'{count}/{len(checks)} conceptos esperados mencionados; no acredita todas las afirmaciones.')
            scores['completitud'] = _score(4 if count == len(checks) else 2 if count else 0,
                'Cobertura de los controles explícitos de este turno; revisión semántica pendiente.')
        if count != len(checks) and status == 'answered':
            findings.append({'code': 'missing_requested_concepts', 'severity': 'high',
                             'evidence': [check for check in checks if not check['passed']]})
    false_claims = []
    for pattern in oracle.get('forbidden_assertions', []):
        for sentence in re.split(r'(?<=[.!?])\s+|\n+', answer):
            # Una negación o una pregunta no confirma una premisa falsa.
            if '?' in sentence or re.search(r'\b(?:no|nunca|tampoco|falso|incorrecto|err[oó]ne[oa])\b', sentence, re.I):
                continue
            match = re.search(pattern, normal(sentence), re.I)
            if match:
                false_claims.append({'statement': sentence, 'matched': match.group(0), 'rule': pattern})
    if false_claims:
        scores['factualidad'] = _score(0, 'Contradicción explícita con el oráculo referenciado; revisar el pasaje guardado.')
        findings.append({'code': 'explicit_false_assertion', 'severity': 'critical', 'evidence': false_claims})
    elif oracle.get('references'):
        scores['factualidad'] = _score(None, 'Referencias/oráculos disponibles; ausencia de contradicción detectada no certifica verdad.')
    if oracle.get('expects_uncertainty_or_correction'):
        correction = bool(re.search(r'\b(?:no (?:puedo|pude|hay|existe|aparece|pertenece|es|tiene)|'
            r'nunca|no tengo|no dispongo|no encuentro|no logre|no consegui|no esta|no se|no corresponde|'
            r'otra obra|obras diferentes|universos diferentes|personajes de obras distintas|'
            r'necesito|puedes (?:compartir|indicar)|podrias|no seria correcto|inventad|fictici|'
            r'premisa|confirmar|verificar|mas pistas)\b', normal(answer)))
        if correction and not false_claims:
            scores['incertidumbre'] = _score(4, 'Reconoce límite/corrección; la corrección específica aún requiere revisión.')
        elif false_claims:
            scores['incertidumbre'] = _score(0, 'Confirma una afirmación identificada como falsa.')
        else:
            findings.append({'code': 'uncertainty_not_observable', 'severity': 'high', 'evidence': answer[:500]})
    wrapper = re.search(r'(?i)encontr[eé] estas referencias relacionadas|pasaje recuperado|fragmento del buscador', answer)
    if wrapper and status == 'answered' and not oracle.get('allow_reference_fallback'):
        scores['naturalidad'] = _score(1, 'Se detectó envoltura de recuperación en una pregunta de contenido.')
        findings.append({'code': 'references_instead_of_answer', 'severity': 'high', 'evidence': wrapper.group(0)})
    paragraphs = [normal(value) for value in answer.split('\n\n') if len(value.strip()) >= 80]
    if len(paragraphs) != len(set(paragraphs)):
        scores['concisión'] = _score(1, 'Un párrafo de al menos 80 caracteres se repite literalmente.')
        findings.append({'code': 'duplicate_paragraph', 'severity': 'medium', 'evidence': 'literal paragraph repetition'})
    sources = (trace or {}).get('sources', [])
    diagnostics = (trace or {}).get('diagnostics', row.get('diagnostics', {}))
    audit = diagnostics.get('audit', {}) if isinstance(diagnostics, dict) else {}
    claims = audit.get('claims', []) if isinstance(audit, dict) else []
    literal_checks = []
    by_id = {source.get('id'): source for source in sources if isinstance(source, dict)}
    for claim in claims:
        if not isinstance(claim, dict) or claim.get('verdict') != 'supported':
            continue
        source = by_id.get(claim.get('source_id'))
        proof = claim.get('evidence', '')
        literal = bool(source and isinstance(proof, str) and len(proof.strip()) >= 8 and
                       any(proof in str(source.get(field, '')) for field in ('description', 'title', 'author', 'year')))
        literal_checks.append({'source_id': claim.get('source_id'), 'statement': claim.get('statement'),
                               'evidence': proof, 'literal_in_source': literal})
        if not literal and sources:
            findings.append({'code': 'audit_evidence_not_literal', 'severity': 'critical',
                             'evidence': literal_checks[-1]})
    if literal_checks and all(check['literal_in_source'] for check in literal_checks):
        scores['fuentes'] = _score(3, 'Los pasajes auditados existen literalmente; no demuestra que impliquen toda la afirmación.')
    elif row.get('source_urls'):
        scores['fuentes'] = _score(1, 'Enlaces presentes; consulta y respaldo semántico no comprobados por este control.')
    if oracle.get('context_required') and checks:
        count = sum(check['passed'] for check in checks)
        scores['contexto'] = _score(4 if count == len(checks) and status == 'answered' else 1,
            'Control parcial de entidades esperadas en la continuación; no compara estilo.')
    return {'version': VERSION, 'scores': scores, 'checks': checks,
            'literal_evidence_checks': literal_checks, 'findings': findings,
            'references': oracle.get('references', []), 'review_status': 'partial_deterministic_review',
            'factual_certification': False, 'original_answer_sha256': hashlib.sha256(answer.encode()).hexdigest()}


def summarize(rows):
    times = [row['seconds'] for row in rows if type(row.get('seconds')) in {int, float}]
    ordered = sorted(times)
    findings = [finding for row in rows for finding in row.get('evaluation', {}).get('findings', [])]
    return {'turns': len(rows), 'mean_seconds': statistics.mean(times) if times else None,
            'p50_seconds': statistics.median(times) if times else None,
            'p95_seconds': ordered[max(0, math.ceil(.95 * len(ordered)) - 1)] if ordered else None,
            'max_seconds': max(times) if times else None,
            'under_5_seconds': sum(value <= 5 for value in times),
            'under_10_seconds': sum(value <= 10 for value in times),
            'under_30_seconds': sum(value <= 30 for value in times),
            'model_calls': sum(row.get('model_calls') or 0 for row in rows),
            'findings_by_severity': {label: sum(finding['severity'] == label for finding in findings)
                                     for label in ('critical', 'high', 'medium')},
            'factual_accuracy': None, 'scope': 'finite_partial_checks_not_error_rate_estimate'}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
    temporary.replace(path)
