"""Respaldo programable de una sola ejecución; retención informativa, sin borrados."""
import argparse
import datetime
import json
from pathlib import Path
import secrets
import tempfile
from reader_accounts.production_runtime import FileLease
from scripts.accounts.backup_store import create, restore_new, digest

ROOT=Path(__file__).resolve().parents[2]


def run_backup(database, destination, *, keep=14, interval_hours=20):
    database,destination=Path(database).resolve(),Path(destination).resolve()
    if not 2<=keep<=365 or not 0<=interval_hours<=168:raise ValueError('Política de respaldo inválida.')
    if not (destination.is_relative_to(ROOT/'backups') or destination.is_relative_to(ROOT/'.testtmp')):
        raise ValueError('Utiliza almacenamiento privado de respaldos.')
    marker=destination/'backup-job-owner.json'
    if destination.exists() and not marker.is_file():raise ValueError('La carpeta existente no pertenece al trabajo automático.')
    destination.mkdir(parents=True,exist_ok=True)
    if not marker.exists():marker.write_text('{"owner":"litmate-backup-v1"}',encoding='utf8')
    if json.loads(marker.read_text(encoding='utf8'))!={'owner':'litmate-backup-v1'}:raise ValueError('Marcador de respaldo inválido.')
    (ROOT/'.testtmp').mkdir(exist_ok=True)
    with FileLease(destination/'job.lock'):
        if (destination/'pause.request').exists():return {'status':'paused','deleted':0}
        latest=destination/'latest.json'
        if latest.is_file():
            previous=json.loads(latest.read_text(encoding='utf8'))
            previous_path=destination/previous['backup']
            if previous_path.resolve().parent!=destination:raise ValueError('Referencia de respaldo inválida.')
            manifest=json.loads((previous_path/'manifest.json').read_text(encoding='utf8'))
            if digest(previous_path/'accounts.sqlite3')!=manifest['database_sha256']:raise ValueError('El respaldo anterior se alteró; requiere revisión.')
            # Verifica también clave, avatares, filas y relaciones; no basta
            # con que siga intacto el SQLite del último respaldo.
            with tempfile.TemporaryDirectory(prefix='backup-recheck-',dir=ROOT/'.testtmp') as temporary:
                restore_new(previous_path,Path(temporary)/'accounts.sqlite3')
            age=datetime.datetime.now(datetime.timezone.utc).timestamp()-previous['timestamp']
            if age<interval_hours*3600:return {'status':'recent_backup_valid','deleted':0}
        now=datetime.datetime.now(datetime.timezone.utc)
        name='backup-'+now.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3)
        folder=destination/name
        try:
            manifest=create(database,folder)
            with tempfile.TemporaryDirectory(prefix='backup-restore-',dir=ROOT/'.testtmp') as temporary:
                restore_new(folder,Path(temporary)/'accounts.sqlite3')
        except Exception as error:
            (destination/'failure.json').write_text(json.dumps({'status':'failed','at':now.isoformat(),
                'error_class':type(error).__name__}),encoding='utf8')
            raise
        backups=sorted(p.name for p in destination.glob('backup-*') if p.is_dir() and (p/'manifest.json').is_file())
        result={'status':'verified','backup':name,'timestamp':now.timestamp(),'at':now.isoformat(),
                'tables':len(manifest['tables']),'restore_verified':True,'deleted':0,
                'retention_candidates':backups[:-keep] if len(backups)>keep else []}
        latest.write_text(json.dumps(result,indent=2),encoding='utf8')
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--folder',type=Path,required=True)
    parser.add_argument('--keep',type=int,default=14)
    parser.add_argument('--interval-hours',type=int,default=20)
    args=parser.parse_args()
    print(json.dumps(run_backup(args.database,args.folder,keep=args.keep,interval_hours=args.interval_hours)))


if __name__=='__main__':
    try:main()
    except Exception as error:
        print(json.dumps({'status':'failed','error_class':type(error).__name__,'deleted':0}))
        raise SystemExit(1)
