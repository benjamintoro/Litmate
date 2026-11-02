"""Aggregate measured campaign outputs; answered is never a factual verdict."""
import argparse
import json
import math
from pathlib import Path
import statistics


def latency(rows):
    values=sorted(row['turns'][0]['seconds'] for row in rows)
    return {'cases':len(rows),'answered_status':sum(row['turns'][0]['status']=='answered' for row in rows),
        'mean_seconds':round(statistics.mean(values),4) if values else None,
        'p50_seconds':statistics.median(values) if values else None,
        'p95_nearest_rank_seconds':values[math.ceil(.95*len(values))-1] if values else None,
        **{f'under_{limit}_seconds':sum(value<limit for value in values) for limit in (5,10,30)},
        'factual_precision':None,'answered_does_not_mean_correct':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        parser.error('Conserva el resumen anterior; elige una salida nueva.')
    pairs=[(p,json.loads(p.read_text(encoding='utf-8'))) for p in sorted(args.folder.glob('case_*.json'))]
    workers=[json.loads(p.read_text(encoding='utf-8')) for p in args.folder.rglob('enrichment_[0-9]*.json')]
    baseline=[r for p,r in pairs if p.name.endswith('_online_1.json')]
    after=[r for p,r in pairs if r.get('research_profile')=='cold_after']
    offline=[r for p,r in pairs if r.get('offline_guard_version')==2]
    google=[r for p,r in pairs if r.get('research_profile')=='free_google']
    report={'initial_cold':latency(baseline),'after_cold_same_initial_memory':latency(after),
        'strict_offline_new_answer_cache':latency(offline),'google_confirmed_no_billing_profile':latency(google),
        'workers':{'unique_works_examined':len({r['work']['work_id'] for r in workers}),
            'work_checkpoints':len(workers),'works_with_coverage_change':sum(r['coverage_changed'] for r in workers),
            'jobs_claimed':sum(r['batch'].get('batch',{}).get('claimed',0) for r in workers),
            'jobs_completed':sum(r['batch'].get('batch',{}).get('completed',0) for r in workers),
            'sources_admitted_or_reverified':sum(r['batch'].get('batch',{}).get('stored',0) for r in workers),
            'measured_worker_seconds':round(sum(r['batch'].get('seconds',0) for r in workers),3),
            'measured_worker_cpu_seconds':round(sum(r['batch'].get('cpu_seconds',0) for r in workers),3),
            'peak_worker_rss_mb':max((r['batch'].get('process',{}).get('peak_rss_mb',0) for r in workers),default=0),
            'llm_calls':sum(r['batch'].get('llm_calls',0) for r in workers)},
        'per_case_runs':[{'file':str(p),'case':r['case']['case'],'offline':r['offline'],
            'guard_version':r.get('offline_guard_version'),'profile':r.get('research_profile','research'),
            'seconds':r['turns'][0]['seconds'],'status':r['turns'][0]['status'],
            'model_calls':r['turns'][0].get('diagnostics',{}).get('progress_metrics',{}).get('model_calls_started'),
            'http_timing':r['turns'][0].get('http_timing')} for p,r in pairs],
        'limits':['Small benchmark, not a production SLA or a measured 99% accuracy.',
                  'Live providers and model generations vary between runs.',
                  'Worker times exclude full-backup verification and campaign inventory overhead.',
                  'Nonfiction follow-up batch and explicit public ingestion are separate reports.']}
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(report,stream,ensure_ascii=True,indent=2)
    print(json.dumps({k:v for k,v in report.items() if k!='per_case_runs'},ensure_ascii=True))


if __name__=='__main__':
    main()
