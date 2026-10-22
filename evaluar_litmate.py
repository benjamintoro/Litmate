"""Ejecuta la matriz literaria en procesos aislados, sin cargar .env ni TiDB.

Cada caso conserva su conversación en verificar_investigacion.py. Una respuesta
publicada no se cuenta como correcta: su revisión factual queda pendiente.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


BASE = Path(__file__).resolve().parent


def read_matrix(path):
    raw = Path(path).read_bytes()
    matrix = json.loads(raw.decode('utf-8-sig'))
    cases = matrix.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError('La matriz debe incluir casos.')
    identifiers = set()
    for case in cases:
        identifier = case.get('id', '')
        if (not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', identifier)
                or identifier in identifiers or case.get('mode') not in {'live', 'controlled'}
                or not isinstance(case.get('messages'), list) or not case['messages']
                or any(not isinstance(message, dict) or not isinstance(message.get('text'), str)
                       or not message['text'].strip() for message in case['messages'])):
            raise ValueError('Caso inválido, duplicado o sin mensajes: ' + str(identifier))
        identifiers.add(identifier)
    return matrix, hashlib.sha256(raw).hexdigest()


def select_cases(matrix, identifiers=None):
    wanted = set(identifiers or [])
    available = {case['id'] for case in matrix['cases']}
    if wanted - available:
        raise ValueError('Casos desconocidos: ' + ', '.join(sorted(wanted - available)))
    return [case for case in matrix['cases'] if not wanted or case['id'] in wanted]


def conversation_command(case, model, output):
    command = [sys.executable, '-B', str(BASE / 'verificar_investigacion.py'),
               '--live', '--web', '--public-catalog', '--trace', '--model', model,
               '--output', str(output)]
    for message in case['messages']:
        command.extend(['--message', message['text']])
    return command


def summarize_turns(case, rows):
    turns = []
    for index, expected in enumerate(case['messages']):
        row = rows[index] if index < len(rows) and isinstance(rows[index], dict) else {}
        diagnostics = row.get('diagnostics') or {}
        route = next((item.get('draft', {}) for item in row.get('drafts_for_local_review', [])
                      if isinstance(item, dict) and item.get('stage') == 'route'), {})
        turns.append({
            'turn': index + 1, 'question': expected['text'], 'observed_question': row.get('question'),
            'question_matches': row.get('question') == expected['text'],
            'expected': {key: value for key, value in expected.items() if key != 'text'},
            'status': row.get('status', 'missing'), 'seconds': row.get('seconds'),
            'answer': row.get('answer', ''),
            'answer_chars': len(row.get('answer') or ''),
            'observed_intent': route.get('intent'),
            'observed_topic': diagnostics.get('requested_subject'),
            'reported_coverage': diagnostics.get('coverage'),
            'external_searches': diagnostics.get('web_searches'),
            'source_count': len(row.get('sources_used', [])),
            'source_urls': list(dict.fromkeys(source['url'] for source in row.get('sources_used', [])
                                              if isinstance(source, dict) and source.get('url'))),
            'factual_review': 'pending_independent_review', 'correct': None,
        })
    return turns


def run_case(case, model, outputdir, *, timeout=None, runner=subprocess.run):
    identifier = case['id']
    if case['mode'] != 'live':
        return {'id': identifier, 'mode': case['mode'], 'execution_status': 'not_run_controlled',
                'reason': 'Requiere condiciones simuladas; no se contabiliza como prueba real.',
                'expected_turns': len(case['messages']), 'turns': []}
    folder = Path(outputdir) / identifier
    folder.mkdir(parents=True, exist_ok=True)
    result_path = folder / 'conversacion.json'
    if result_path.exists():
        raise ValueError('El destino ya contiene resultados; usa otra carpeta: ' + str(folder))
    command = conversation_command(case, model, result_path)
    (folder / 'caso.json').write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding='utf-8')
    environment = os.environ.copy()
    environment.pop('DJANGO_SETTINGS_MODULE', None)
    environment['PYTHONIOENCODING'] = 'utf-8'
    started = time.monotonic()
    timed_out = False
    exit_code = None
    stdout, stderr = '', ''
    try:
        completed = runner(command, cwd=str(BASE), env=environment, capture_output=True,
                           text=True, encoding='utf-8', errors='replace',
                           timeout=timeout or (len(case['messages']) * 420 + 60), check=False)
        exit_code, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout, stderr = exc.stdout or '', exc.stderr or ''
        stdout = stdout.decode('utf-8', 'replace') if isinstance(stdout, bytes) else stdout
        stderr = stderr.decode('utf-8', 'replace') if isinstance(stderr, bytes) else stderr
    except OSError as exc:
        stderr = type(exc).__name__ + ': no se pudo iniciar el verificador aislado.'
    (folder / 'stdout.txt').write_text(stdout, encoding='utf-8')
    (folder / 'stderr.txt').write_text(stderr, encoding='utf-8')
    read_error, rows = None, []
    try:
        rows = json.loads(result_path.read_text(encoding='utf-8'))
        if not isinstance(rows, list):
            raise ValueError('El informe de conversación no es una lista.')
    except (OSError, ValueError):
        read_error = 'missing_or_invalid_conversation_report'
        rows = []
    turns = summarize_turns(case, rows)
    execution_status = ('timed_out' if timed_out else 'report_error' if read_error else
                        'complete' if len(rows) == len(case['messages']) else 'incomplete')
    return {'id': identifier, 'mode': 'live', 'execution_status': execution_status,
            'process_exit_code': exit_code, 'seconds': round(time.monotonic() - started, 3),
            'report_error': read_error, 'expected_turns': len(case['messages']),
            'observed_turns': len(rows), 'conversation_report': str(result_path),
            'stdout': str(folder / 'stdout.txt'), 'stderr': str(folder / 'stderr.txt'),
            'turns': turns}


def report_metrics(cases):
    turns = [turn for case in cases if case['mode'] == 'live' for turn in case['turns']]
    published = sum(turn['status'] == 'answered' for turn in turns)
    return {'requested_turns': len(turns), 'published_answers': published,
            'publication_coverage': published / len(turns) if turns else None,
            'unavailable_turns': sum(turn['status'] == 'unavailable' for turn in turns),
            'missing_turns': sum(turn['status'] == 'missing' for turn in turns),
            'controlled_cases_not_run': sum(case['mode'] == 'controlled' for case in cases),
            'independently_reviewed_turns': 0, 'correct_answers': None, 'incorrect_answers': None,
            'factual_error_rate': None,
            'warning': 'Publicación y cobertura técnica no equivalen a exactitud factual.'}


def compare_reports(before, after):
    """Compara todos los IDs, incluidos los ausentes; no infiere exactitud."""
    previous = {case['id']: case for case in before.get('cases', [])}
    current = {case['id']: case for case in after.get('cases', [])}
    rows = []
    for identifier in sorted(set(previous) | set(current)):
        left, right = previous.get(identifier), current.get(identifier)
        rows.append({'id': identifier,
            'present_before': left is not None, 'present_after': right is not None,
            'statuses_before': [turn['status'] for turn in (left or {}).get('turns', [])],
            'statuses_after': [turn['status'] for turn in (right or {}).get('turns', [])],
            'seconds_before': (left or {}).get('seconds'), 'seconds_after': (right or {}).get('seconds'),
            'factual_correctness_change': None})
    return {'same_matrix': before.get('matrix_sha256') == after.get('matrix_sha256'),
            'model_before': before.get('model'), 'model_after': after.get('model'),
            'cases': rows, 'warning': 'Comparación de ejecución; revisión factual independiente pendiente.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--matrix', type=Path, default=BASE / 'datos_evaluacion_ia.json')
    parser.add_argument('--case', action='append', dest='identifiers', help='ID repetible; sin selección incluye toda la matriz.')
    parser.add_argument('--model', default='qwen3.5:9b-q4_K_M')
    parser.add_argument('--outputdir', type=Path, default=BASE / 'reportes' /
                        ('evaluacion-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')))
    parser.add_argument('--before', type=Path, help='Resumen anterior de este ejecutor para comparar todos los casos.')
    parser.add_argument('--timeout', type=int, help='Máximo de segundos por conversación; por defecto 420 por turno + 60.')
    parser.add_argument('--dry-run', action='store_true', help='Muestra la selección sin ejecutar modelos ni HTTP.')
    args = parser.parse_args(argv)
    matrix, digest = read_matrix(args.matrix)
    cases = select_cases(matrix, args.identifiers)
    if (not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,100}', args.model)
            or 'cloud' in args.model.lower() or '..' in args.model or '://' in args.model):
        parser.error('Se requiere un modelo descargado localmente.')
    if args.timeout is not None and not 30 <= args.timeout <= 7200:
        parser.error('--timeout debe estar entre 30 y 7200 segundos.')
    if args.dry_run:
        print(json.dumps({'model': args.model, 'matrix_sha256': digest,
              'cases': [{'id': case['id'], 'mode': case['mode'], 'turns': len(case['messages'])}
                        for case in cases]}, ensure_ascii=True, indent=2))
        return 0
    outputdir = args.outputdir.resolve()
    outputdir.mkdir(parents=True, exist_ok=True)
    summary_path = outputdir / 'resumen.json'
    if summary_path.exists():
        parser.error('El destino ya tiene un resumen; elige una carpeta nueva para conservar el anterior.')
    report = {'created_at_utc': datetime.now(timezone.utc).isoformat(), 'model': args.model,
              'matrix_path': str(args.matrix.resolve()), 'matrix_sha256': digest,
              'factual_review': 'pending_independent_review',
              'review_criteria': matrix.get('review_criteria', []), 'cases': []}
    for case in cases:
        print(json.dumps({'case_started': case['id'], 'mode': case['mode']}, ensure_ascii=True), flush=True)
        result = run_case(case, args.model, outputdir, timeout=args.timeout)
        report['cases'].append(result)
        report['metrics'] = report_metrics(report['cases'])
        summary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'case_finished': case['id'], 'execution_status': result['execution_status'],
                          'statuses': [turn['status'] for turn in result['turns']]}, ensure_ascii=True), flush=True)
    if args.before:
        previous = json.loads(args.before.read_text(encoding='utf-8'))
        comparison = compare_reports(previous, report)
        (outputdir / 'comparacion.json').write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding='utf-8')
    print(str(summary_path), flush=True)
    return int(any(case['mode'] == 'live' and (case['execution_status'] != 'complete'
                   or case.get('process_exit_code') != 0) for case in report['cases']))


if __name__ == '__main__':
    raise SystemExit(main())
