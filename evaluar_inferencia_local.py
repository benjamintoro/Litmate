"""Comparación controlada de inferencia local; no mide el chatbot completo.

Las mismas fichas de prueba se entregan a cada configuración. No escribe en
conocimiento ni usa respuestas cacheadas. No descarga ni cambia modelos.
"""
import argparse
import json
from pathlib import Path
import time
from core.ai_http import read_json_url

CASES = [
    {'id': 'autoria', 'question': '¿Quién escribió Orgullo y prejuicio?',
     'evidence': 'Orgullo y prejuicio es una novela de Jane Austen.', 'required': ['Jane Austen']},
    {'id': 'contexto', 'question': 'Estamos hablando de Papelucho y el marciano. ¿Y qué sucede con Det?',
     'evidence': 'En Papelucho y el marciano, de Marcela Paz, Det es el amigo marciano de Papelucho y vive dentro de él.',
     'required': ['Det', 'Papelucho']},
    {'id': 'incertidumbre', 'question': '¿En qué página aparece esa escena?',
     'evidence': 'No se dispone de una edición ni del texto de la escena.', 'required': [], 'uncertain': True},
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Usa una ruta nueva.')
    report = {'scope': 'real_local_controlled_extraction_not_end_to_end_quality', 'results': []}
    schema = {'type': 'object', 'properties': {'answer': {'type': 'string'}, 'uncertain': {'type': 'boolean'}},
              'required': ['answer', 'uncertain'], 'additionalProperties': False}
    for model, context in [('qwen3.5:9b-q4_K_M', 16384), ('qwen3.5:9b-q4_K_M', 8192), ('qwen3.5:4b', 8192)]:
        for case in CASES:
            started = time.monotonic()
            row = {'model': model, 'context': context, 'case': case['id']}
            try:
                result = read_json_url('http://127.0.0.1:11434/api/generate', local=True, timeout=40,
                    payload={'model': model, 'stream': False, 'think': False, 'format': schema,
                        'keep_alive': '10m', 'options': {'num_ctx': context, 'num_predict': 160, 'temperature': 0},
                        'system': 'Responde en español usando únicamente la evidencia recibida. Si falta evidencia, uncertain=true y solicita lo necesario. Devuelve JSON answer/uncertain.',
                        'prompt': json.dumps({k: case[k] for k in ('question', 'evidence')}, ensure_ascii=False)})
                answer = json.loads(result.get('response', ''))
                row.update(answer=answer, done_reason=result.get('done_reason'),
                    load_seconds=result.get('load_duration', 0) / 1e9,
                    prompt_seconds=result.get('prompt_eval_duration', 0) / 1e9,
                    generate_seconds=result.get('eval_duration', 0) / 1e9,
                    tokens=result.get('eval_count'),
                    passed_control=all(token.casefold() in answer.get('answer', '').casefold()
                        for token in case['required']) and answer.get('uncertain') is bool(case.get('uncertain')))
            except Exception as error:
                row.update(error=type(error).__name__, passed_control=False)
            row['seconds'] = round(time.monotonic() - started, 3)
            report['results'].append(row)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(row, ensure_ascii=True), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
