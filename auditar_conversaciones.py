"""Auditor limitado/reanudable sobre el HTTP/SSE real del evaluador existente.

Cada conversación conserva las cookies reales entre sus turnos. Si un proceso
se interrumpe, una conversación incompleta se REINICIA y sus turnos se cuentan
otra vez: nunca se simula haber restaurado la sesión de Django.
"""
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from core.conversation_audit import (DEFAULT_LIMITS, VERSION, atomic_json, evaluate_turn,
    fingerprint, load_bank, pick_message, select_cases, summarize)


def main(argv=None):
    base = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bank', type=Path, default=base / 'core/data/conversation_audit_cases.json')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=20261027)
    parser.add_argument('--case', action='append', default=[])
    parser.add_argument('--max-conversations', type=int, default=DEFAULT_LIMITS['conversations'])
    parser.add_argument('--max-turns', type=int, default=DEFAULT_LIMITS['turns'])
    parser.add_argument('--max-seconds', type=float, default=DEFAULT_LIMITS['seconds'])
    parser.add_argument('--model', default='litmate-qwen35-text:9b-q4_K_M')
    parser.add_argument('--context', type=int, default=16384)
    parser.add_argument('--chat-budget', type=float, default=36)
    parser.add_argument('--response-budget', type=float, default=42)
    parser.add_argument('--library', type=Path)
    parser.add_argument('--library-index', type=Path)
    parser.add_argument('--library-semantic', action='store_true')
    parser.add_argument('--no-web', action='store_true')
    parser.add_argument('--prewarm', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--plan-only', action='store_true', help='Valida plan y límites, sin HTTP ni Ollama.')
    args = parser.parse_args(argv)
    if (not 1 <= args.max_conversations <= 30 or not 1 <= args.max_turns <= 600
            or not 1 <= args.max_seconds <= 14400 or args.response_budget <= args.chat_budget
            or args.chat_budget <= 0):
        parser.error('Límites inválidos: conversaciones1..30, turnos1..600, segundos1..14400, respuesta>trabajo>0.')
    bank = load_bank(args.bank)
    output = args.output_dir.resolve()
    state_path = output / 'estado.json'
    config = {'bank_sha256': fingerprint(bank), 'seed': args.seed, 'cases': args.case,
        'model': args.model, 'context': args.context, 'chat_budget': args.chat_budget,
        'response_budget': args.response_budget, 'web': not args.no_web,
        'library': str(args.library.resolve()) if args.library else None,
        'library_index': str(args.library_index.resolve()) if args.library_index else None,
        'library_semantic': args.library_semantic}
    signature = fingerprint(config)
    if state_path.exists():
        if not args.resume:
            parser.error('El lote ya existe; usa --resume o un directorio nuevo.')
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if state.get('version') != VERSION or state.get('configuration_sha256') != signature:
            parser.error('La configuración o el banco cambió; crea otro lote para una comparación honesta.')
    else:
        if args.resume:
            parser.error('No existe un estado que reanudar.')
        if output.exists() and any(output.iterdir()):
            parser.error('El directorio contiene archivos ajenos al lote; usa uno nuevo.')
        state = {'version': VERSION, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
                 'configuration': config, 'configuration_sha256': signature, 'runs': [],
                 'completed_cases': [], 'turns_executed': 0,
                 'resumption_policy': 'restart_incomplete_conversation_counting_replay_turns'}
    selected = select_cases(bank, cases=args.case, maximum=args.max_conversations,
                            completed=state['completed_cases'])
    selected = selected[:max(0, args.max_conversations - len(state['completed_cases']))]
    already_spent = state.get('turns_executed', 0)
    plan = {'selected_cases': [case['id'] for case in selected],
            'planned_turns': sum(len(case['messages']) for case in selected),
            'turn_budget_remaining': max(0, args.max_turns - already_spent),
            'max_conversations': args.max_conversations, 'max_turns': args.max_turns,
            'max_seconds': args.max_seconds, 'dry_run': args.plan_only}
    state['last_plan'] = plan
    atomic_json(state_path, state)
    print(json.dumps(plan, ensure_ascii=True), flush=True)
    if args.plan_only or not selected or already_spent >= args.max_turns:
        return 0

    number = len(state['runs']) + 1
    capture_path = output / f'captura_{number:03}.json'
    matrix_path = output / f'matriz_{number:03}.json'
    if capture_path.exists() or matrix_path.exists():
        parser.error('Un archivo de la siguiente ejecución ya existe; revisa el estado antes de reanudar.')
    atomic_json(matrix_path, {'cases': selected})
    run = {'id': number, 'capture': capture_path.name,
           'started_at_utc': datetime.now(timezone.utc).isoformat(), 'turns': [], 'completed': False,
           'replayed_cases': [case['id'] for case in selected if any(
               row.get('case') == case['id'] for previous in state['runs'] for row in previous['turns'])]}
    state['runs'].append(run)
    atomic_json(state_path, state)
    started = time.monotonic()
    by_id = {case['id']: case for case in selected}

    def select(case, index, item, previous):
        return pick_message(case, index, item, previous, seed=args.seed)

    def allowed(report, case, index):
        remaining = args.max_seconds - (time.monotonic() - started)
        turn_count = already_spent + len(report['turns'])
        # No iniciar un turno que por sí solo pueda agotar el presupuesto global.
        if turn_count >= args.max_turns or remaining < args.response_budget:
            run['stop_reason'] = 'turn_limit' if turn_count >= args.max_turns else 'time_limit'
            return False
        return True

    def observe(report, row):
        item = by_id[row['case']]['messages'][row['turn'] - 1]
        trace = next((entry for entry in reversed(report.get('audit_traces', []))
                      if entry.get('question') == row['question']), None)
        row['evaluation'] = evaluate_turn(row, item, trace=trace)
        row['conversation_id'] = f'run-{number}:{row["case"]}'
        row['scenario_turn'] = item.get('id', str(row['turn']))
        row['selection'] = {'seed': args.seed, 'actual_question': row['question'],
                            'base_question': item['text'], 'dynamic_or_variant': row['question'] != item['text']}
        run['turns'].append(copy.deepcopy(row))
        state['turns_executed'] = already_spent + len(run['turns'])
        if row['turn'] == len(by_id[row['case']]['messages']):
            if row['case'] not in state['completed_cases']:
                state['completed_cases'].append(row['case'])
        state['summary'] = summarize([turn for previous in state['runs'] for turn in previous['turns']])
        atomic_json(state_path, state)

    arguments = ['--matrix', str(matrix_path), '--output', str(capture_path), '--progressive',
                 '--trace-audit', '--trace-narrative', '--trace-characters', '--model', args.model,
                 '--context', str(args.context), '--chat-budget', str(args.chat_budget),
                 '--response-budget', str(args.response_budget)]
    for enabled, flag in [(args.no_web, '--no-web'), (args.prewarm, '--prewarm'),
                          (args.library_semantic, '--library-semantic')]:
        if enabled:
            arguments.append(flag)
    for value, flag in [(args.library, '--library'), (args.library_index, '--library-index')]:
        if value:
            arguments.extend([flag, str(value)])
    code = 1
    try:
        import evaluar_chat_http
        code = evaluar_chat_http.main(arguments, message_selector=select,
                                     turn_observer=observe, continue_run=allowed)
        run['completed'] = all(case['id'] in state['completed_cases'] for case in selected)
        run['capture_exit_code'] = code
    except KeyboardInterrupt:
        run['stop_reason'] = 'interrupted'
        code = 130
    except Exception as error:
        # El tipo permite diagnosticar el fallo sin volcar URLs/credenciales de una excepción.
        run['stop_reason'] = 'infrastructure_error'
        run['error_type'] = type(error).__name__
        raise
    finally:
        run['seconds'] = round(time.monotonic() - started, 3)
        state['summary'] = summarize([turn for previous in state['runs'] for turn in previous['turns']])
        atomic_json(state_path, state)
        atomic_json(output / 'conversaciones_evaluadas.json', {
            'version': VERSION, 'configuration': config, 'runs': state['runs'], 'summary': state['summary']})
        incidents = []
        for previous in state['runs']:
            for row in previous['turns']:
                for finding in row.get('evaluation', {}).get('findings', []):
                    incidents.append({'id': f'{previous["id"]}:{row["case"]}:{row["turn"]}:{finding["code"]}',
                        'case': row['case'], 'turn': row['turn'], 'question': row['question'],
                        'finding': finding, 'status': 'needs_reproduction_and_root_cause',
                        'cause': None, 'correction': None})
        atomic_json(output / 'errores_detectados.json', {'incidents': incidents,
            'classification': 'automated_partial_findings_require_review'})
    return code


if __name__ == '__main__':
    raise SystemExit(main())
