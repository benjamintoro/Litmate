"""Resume un informe de ``evaluar_chat_http.py`` sin certificar sus hechos.

El informe de entrada contiene preguntas y respuestas reales. Este resumen sólo
publica agregados de latencia, estados y etapas; no copia respuestas ni textos
del lector. Sirve para comparar matrices con las mismas condiciones.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics


def _number(value):
    return type(value) in {int, float} and math.isfinite(value) and value >= 0


def _p95(values):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * .95) - 1)]


def _median(values):
    return statistics.median(values) if values else None


def _round(value):
    return round(value, 3) if _number(value) else None


def _progress(turn):
    diagnostics = turn.get('diagnostics')
    value = diagnostics.get('progress_metrics') if isinstance(diagnostics, dict) else None
    return value if isinstance(value, dict) else {}


def _stage_totals(turn):
    progress = _progress(turn)
    value = progress.get('stage_totals_ms')
    if not isinstance(value, dict):
        value = turn.get('stage_totals_ms')
    if not isinstance(value, dict):
        return {}
    return {str(stage): float(ms) for stage, ms in value.items()
            if isinstance(stage, str) and _number(ms)}


def _model_rows(turn):
    diagnostics = turn.get('diagnostics')
    rows = diagnostics.get('stage_timings') if isinstance(diagnostics, dict) else None
    return rows if isinstance(rows, list) else []


def _model_calls(turn):
    value = turn.get('model_calls')
    if value is None:
        diagnostics = turn.get('diagnostics')
        value = diagnostics.get('model_calls') if isinstance(diagnostics, dict) else None
    return int(value) if _number(value) and int(value) == value else None


def _delivery_ms(turn):
    value = turn.get('delivery_overhead_ms')
    if _number(value):
        return float(value)
    work_ms = _progress(turn).get('elapsed_ms')
    seconds = turn.get('seconds')
    if _number(work_ms) and _number(seconds):
        return max(0., seconds * 1000 - work_ms)
    return None


def summarize(rows):
    seconds = [float(row['seconds']) for row in rows if _number(row.get('seconds'))]
    answered = [float(row['seconds']) for row in rows
                if row.get('status') == 'answered' and _number(row.get('seconds'))]
    first_progress = [float(row['first_progress_seconds']) for row in rows
                      if _number(row.get('first_progress_seconds'))]
    first_text = [float(row['first_text_seconds']) for row in rows
                  if _number(row.get('first_text_seconds'))]
    delivery = [value for row in rows for value in [_delivery_ms(row)] if value is not None]
    stages = defaultdict(float)
    stage_turns = Counter()
    for row in rows:
        for stage, milliseconds in _stage_totals(row).items():
            stages[stage] += milliseconds
            stage_turns[stage] += 1
    model_stages = defaultdict(float)
    model_stage_calls = Counter()
    models = defaultdict(float)
    for row in rows:
        for item in _model_rows(row):
            if not isinstance(item, dict):
                continue
            stage, milliseconds = item.get('stage'), item.get('elapsed_ms')
            if not isinstance(stage, str) or not _number(milliseconds):
                continue
            model_stages[stage] += float(milliseconds)
            model_stage_calls[stage] += 1
            model = item.get('model')
            if isinstance(model, str) and model:
                models[model] += float(milliseconds)
    calls = [_model_calls(row) for row in rows]
    rss = [row.get('resources', {}).get('rss_mb') for row in rows
           if isinstance(row.get('resources'), dict)]
    peak = [row.get('resources', {}).get('peak_rss_mb') for row in rows
            if isinstance(row.get('resources'), dict)]
    cpu = [row.get('resources', {}).get('cpu_seconds') for row in rows
           if isinstance(row.get('resources'), dict)]
    return {
        'turns': len(rows),
        'statuses': dict(Counter(str(row.get('status', 'unknown')) for row in rows)),
        'p50_seconds': _round(_median(seconds)),
        'mean_seconds': _round(statistics.mean(seconds)) if seconds else None,
        'p95_seconds': _round(_p95(seconds)),
        'max_seconds': _round(max(seconds)) if seconds else None,
        'under_5_seconds': sum(value < 5 for value in seconds),
        'under_10_seconds': sum(value < 10 for value in seconds),
        'under_30_seconds': sum(value < 30 for value in seconds),
        'answered_under_5_seconds': sum(value < 5 for value in answered),
        'answered_under_10_seconds': sum(value < 10 for value in answered),
        'answered_under_30_seconds': sum(value < 30 for value in answered),
        'first_progress_p50_seconds': _round(_median(first_progress)),
        'first_text_p50_seconds': _round(_median(first_text)),
        'delivery_overhead_p50_ms': _round(_median(delivery)),
        'model_calls': sum(value for value in calls if value is not None),
        'model_calls_unknown_turns': sum(value is None for value in calls),
        'exact_answer_cache_hits': sum(
            row.get('diagnostics', {}).get('exact_answer_cache_hit') is True for row in rows
            if isinstance(row.get('diagnostics'), dict)),
        'max_rss_mb': _round(max((value for value in rss if _number(value)), default=None)),
        'peak_rss_mb': _round(max((value for value in peak if _number(value)), default=None)),
        'cpu_seconds': _round(sum(value for value in cpu if _number(value))) if cpu else None,
        'stage_totals_ms': {stage: _round(value) for stage, value in sorted(stages.items())},
        'stage_turns': dict(sorted(stage_turns.items())),
        'model_stage_totals_ms': {stage: _round(value)
                                  for stage, value in sorted(model_stages.items())},
        'model_stage_calls': dict(sorted(model_stage_calls.items())),
        'model_totals_ms': {model: _round(value) for model, value in sorted(models.items())},
    }


def _markdown(report):
    lines = ['# Resumen del benchmark literario', '',
             f"- Fuente: `{report['source']}`",
             f"- Generado: `{report['generated_at_utc']}`",
             '- Certificación factual: `not_independently_certified`', '']
    overall = report['global']
    lines += ['## Global', '',
              '| Métrica | Valor |', '|---|---:|',
              f"| Turnos | {overall['turns']} |",
              f"| Estados | {overall['statuses']} |",
              f"| p50 | {overall['p50_seconds']} s |",
              f"| Media | {overall['mean_seconds']} s |",
              f"| p95 | {overall['p95_seconds']} s |",
              f"| Máximo | {overall['max_seconds']} s |",
              f"| Bajo 5 s | {overall['under_5_seconds']} |",
              f"| Bajo 10 s | {overall['under_10_seconds']} |",
              f"| Bajo 30 s | {overall['under_30_seconds']} |",
              f"| Publicadas bajo 30 s (no certifica cobertura ni exactitud) | {overall['answered_under_30_seconds']} |",
              f"| Primer progreso (p50) | {overall['first_progress_p50_seconds']} s |",
              f"| Primer texto (p50) | {overall['first_text_p50_seconds']} s |",
              f"| Sobrecarga de entrega (p50) | {overall['delivery_overhead_p50_ms']} ms |",
              f"| Llamadas al modelo conocidas | {overall['model_calls']} |",
              f"| Turnos con llamadas desconocidas | {overall['model_calls_unknown_turns']} |",
              f"| Aciertos de caché exacta | {overall['exact_answer_cache_hits']} |",
              f"| RSS máximo del servidor Python | {overall['max_rss_mb']} MB |",
              f"| CPU del servidor Python | {overall['cpu_seconds']} s |", '']
    lines += ['## Por categoría', '',
              '| Categoría | Turnos | Estados | p50 | p95 | Bajo 5 s | Bajo 30 s | Llamadas |',
              '|---|---:|---|---:|---:|---:|---:|---:|']
    for category, data in report['categories'].items():
        lines.append(f"| {category} | {data['turns']} | {data['statuses']} | "
                     f"{data['p50_seconds']} s | {data['p95_seconds']} s | "
                     f"{data['under_5_seconds']} | {data['under_30_seconds']} | "
                     f"{data['model_calls']} |")
    lines += ['', '## Etapas instrumentadas', '',
              'Los tiempos inclusivos pueden solaparse o ejecutarse en paralelo; no deben sumarse como latencia total.', '',
              '| Etapa | Turnos | Total | Media por turno |', '|---|---:|---:|---:|']
    for stage, total in overall['stage_totals_ms'].items():
        turns = overall['stage_turns'].get(stage, 0)
        mean = total / turns if turns else None
        lines.append(f"| {stage} | {turns} | {total} ms | {_round(mean)} ms |")
    if overall['model_stage_totals_ms']:
        lines += ['', '## Etapas del modelo', '',
                  '| Etapa | Llamadas registradas | Total |', '|---|---:|---:|']
        for stage, total in overall['model_stage_totals_ms'].items():
            lines.append(f"| {stage} | {overall['model_stage_calls'].get(stage, 0)} | {total} ms |")
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--markdown', type=Path)
    args = parser.parse_args(argv)
    report = json.loads(args.input.read_text(encoding='utf-8-sig'))
    rows = [row for row in report.get('turns', []) if isinstance(row, dict)]
    categories = defaultdict(list)
    routes = defaultdict(list)
    for row in rows:
        categories[str(row.get('category', 'unspecified'))].append(row)
        diagnostics = row.get('diagnostics')
        route = diagnostics.get('provider', 'unknown') if isinstance(diagnostics, dict) else 'unknown'
        routes[str(route)].append(row)
    summary = {
        'source': str(args.input),
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'factual_review': 'not_independently_certified',
        'global': summarize(rows),
        'categories': {category: summarize(items)
                       for category, items in sorted(categories.items())},
        'routes': {route: summarize(items) for route, items in sorted(routes.items())},
    }
    markdown = _markdown(summary)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown, encoding='utf-8')
    print(markdown)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
