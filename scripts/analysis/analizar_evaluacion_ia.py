"""Resume una ejecución de evaluar_litmate con criterios explícitos por caso.

No convierte una abstención segura en un acierto factual. Separa:
- estado aceptado (la ruta no se equivocó de tipo de respuesta),
- contenido mínimo (sólo si hubo respuesta publicada),
- seguridad (frases prohibidas),
- latencias y motivos de abstención.

Uso:
  python analizar_evaluacion_ia.py --matrix datos_evaluacion_ia_v2.json \
      --report reportes/evaluacion_v2_20261022
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics
import unicodedata


def normalize(value):
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(char for char in text if unicodedata.category(char) != 'Mn')
    return ' '.join(text.casefold().split())


def load_case_output(report_dir, case_id):
    path = report_dir / case_id / 'conversacion.json'
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding='utf-8'))


def pct(values, percentile):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((percentile / 100) * (len(ordered) - 1))))
    return ordered[index]


def classify(case, row):
    status = row.get('status') or 'missing'
    answer = row.get('answer') or ''
    expected_status = set(case.get('expected_status') or ['answered'])
    status_ok = status in expected_status
    must_include = case.get('must_include') or []
    missing = [term for term in must_include if normalize(term) not in normalize(answer)]
    content_ok = status != 'answered' or not missing
    if case.get('min_answer_chars') and status == 'answered':
        content_ok = content_ok and len(answer) >= case['min_answer_chars']
    # Las frases prohibidas sólo se evalúan en respuestas publicadas. Una
    # negativa o una abstención puede mencionar el término para rechazarlo.
    forbidden = ([term for term in (case.get('must_not_include') or [])
                  if normalize(term) in normalize(answer)]
                 if status == 'answered' else [])
    safety_ok = not forbidden
    # Una abstención en un caso que no requería respuesta publicada es segura.
    overall_ok = status_ok and content_ok and safety_ok
    return {
        'status': status,
        'status_ok': status_ok,
        'missing_terms': missing,
        'content_ok': content_ok,
        'forbidden_terms': forbidden,
        'safety_ok': safety_ok,
        'overall_ok': overall_ok,
        'answer_chars': len(answer),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--matrix', default='datos_evaluacion_ia_v2.json')
    parser.add_argument('--report', required=True)
    parser.add_argument('--output')
    args = parser.parse_args()

    matrix = json.loads(Path(args.matrix).read_text(encoding='utf-8-sig'))
    report_dir = Path(args.report)
    summary = json.loads((report_dir / 'resumen.json').read_text(encoding='utf-8'))
    summaries = {case['id']: case for case in summary.get('cases', [])}
    cases = []
    status_counts = Counter()
    category_counts = defaultdict(lambda: Counter())
    category_turns = Counter()
    latencies = []
    safety_failures = []
    content_failures = []
    status_failures = []
    for case in matrix['cases']:
        rows = load_case_output(report_dir, case['id'])
        if not rows:
            continue
        category = case.get('category', 'regresion')
        category_turns[category] += len(rows)
        for index, row in enumerate(rows, start=1):
            result = classify(case, row)
            status_counts[result['status']] += 1
            category_counts[category][result['status']] += 1
            seconds = row.get('seconds')
            if isinstance(seconds, (int, float)):
                latencies.append(float(seconds))
            item = {
                'id': case['id'], 'turn': index, 'category': category,
                'question': row.get('question', ''),
                'answer': row.get('answer', ''),
                **result,
            }
            cases.append(item)
            if not result['safety_ok']:
                safety_failures.append(item)
            if not result['content_ok']:
                content_failures.append(item)
            if not result['status_ok']:
                status_failures.append(item)

    total = len(cases)
    summary_data = {
        'report': str(report_dir),
        'matrix': str(args.matrix),
        'turns_executed': total,
        'turns_with_answer': status_counts['answered'],
        'status_counts': dict(status_counts),
        'category_turns': dict(category_turns),
        'category_statuses': {key: dict(value) for key, value in category_counts.items()},
        'latency_seconds': {
            'p50': round(statistics.median(latencies), 3) if latencies else None,
            'p95': round(pct(latencies, 95), 3) if latencies else None,
            'max': round(max(latencies), 3) if latencies else None,
        },
        'status_failures': len(status_failures),
        'content_failures': len(content_failures),
        'safety_failures': len(safety_failures),
        'overall_pass': sum(1 for item in cases if item['overall_ok']),
        'cases': cases,
    }
    print(json.dumps({key: value for key, value in summary_data.items() if key != 'cases'},
                     ensure_ascii=False, indent=2))
    if args.output:
        Path(args.output).write_text(json.dumps(summary_data, ensure_ascii=False, indent=2),
                                     encoding='utf-8')
    for label, failures in (('STATUS', status_failures), ('CONTENT', content_failures),
                            ('SAFETY', safety_failures)):
        if failures:
            print(f'\n{label} failures:')
            for item in failures:
                detail = ','.join(item['missing_terms'] or item['forbidden_terms'] or [])
                print(f"- {item['id']} turn {item['turn']}: {item['status']} {detail}")


if __name__ == '__main__':
    main()
