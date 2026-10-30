"""Bounded local SearXNG audit on a fixed public literary corpus."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlencode
from urllib.request import build_opener, ProxyHandler

QUERIES = ('Frankenstein Mary Shelley personajes', 'Odisea Homero argumento',
           'Naruto Masashi Kishimoto personajes', 'Jane Eyre Charlotte Bronte argumento')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--identity-only', action='store_true',
                        help='Compare exact title lookup against full narrative queries.')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Usa un informe nuevo.')
    client = build_opener(ProxyHandler({}))
    rows = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for engine in ('openlibrary','wikipedia','mwmbl'):
        queries = ('Frankenstein','Odisea','Naruto','Jane Eyre') if args.identity_only else QUERIES
        for query in queries:
            start = time.monotonic()
            row = {'engine':engine,'query':query,'results':[]}
            url = 'http://127.0.0.1:8080/search?'+urlencode({'q':query,'format':'json','engines':engine,'language':'es'})
            try:
                with client.open(url, timeout=8) as response:
                    data = json.loads(response.read(2_000_000))
                row['unresponsive_engines'] = data.get('unresponsive_engines',[])
                for result in data.get('results',[])[:5]:
                    row['results'].append({key: str(result.get(key,''))[:800] for key in ('title','url','content','engine')})
                row['status'] = 'ok' if row['results'] else 'empty'
            except Exception as error:
                row['status'] = type(error).__name__
            row['seconds'] = round(time.monotonic()-start,3)
            row['with_description'] = sum(len(item['content']) >= 80 for item in row['results'])
            row['narrative_candidates'] = sum(bool(re.search(r'\b(?:historia|trama|narra|novela|personaje|story|character|novel)\b',
                item['content'],re.I)) for item in row['results'])
            row['quality_note'] = 'Candidate counts are not identity, factual accuracy, or sufficient evidence.'
            rows.append(row)
            args.output.write_text(json.dumps(rows,ensure_ascii=True,indent=2),encoding='utf8')
            print(json.dumps({k:v for k,v in row.items() if k not in ('results','quality_note')},ensure_ascii=True),flush=True)
            time.sleep(1)
    # Only aggregate error signatures, never persist arbitrary request logs.
    proc = subprocess.run(['docker','logs','--since','30m','--tail','300','litmate-searxng-1'],
                          capture_output=True,text=True,encoding='utf8',errors='replace',timeout=10)
    log = proc.stdout+proc.stderr
    summary = {label:len(re.findall(pattern,log,re.I)) for label,pattern in {
        'timeout':'timeout|timed out','openlibrary':'openlibrary','late_result':'result.*clos|closed.*result',
        'autocomplete':'autocomplete','forwarded_header':'X-Forwarded-For|X-Real-IP'}.items()}
    args.output.with_suffix('.logs.json').write_text(json.dumps({'window':'last_30_minutes_max_300_lines',
        'signature_counts':summary,'raw_logs_not_saved':True},indent=2),encoding='utf8')


if __name__ == '__main__':
    main()
