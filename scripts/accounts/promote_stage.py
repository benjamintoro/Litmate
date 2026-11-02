"""Prepara una copia persistente NUEVA sólo tras la autorización de despliegue.

No inicia/reinicia servicios, no importa hacia MySQL y no sobrescribe destinos.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3


def inventory(path):
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('La copia no pasó integridad.')
        result={}
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            quoted='"'+table.replace('"','""')+'"'
            rows=db.execute('SELECT * FROM '+quoted+' ORDER BY rowid').fetchall()
            digest=hashlib.sha256(json.dumps(rows,ensure_ascii=True,default=str).encode()).hexdigest()
            result[table]={'rows':len(rows),'sha256':digest}
        return result


def main():
    root=Path(__file__).resolve().parents[2]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    parser.add_argument('--destination',type=Path,default=root/'data/accounts/users.sqlite3')
    parser.add_argument('--deployment-authorized',action='store_true')
    args=parser.parse_args()
    source,destination=args.source.resolve(),args.destination.resolve()
    if not args.deployment_authorized:
        parser.error('Este paso sólo se ejecuta después de autorizar el despliegue.')
    if not source.is_relative_to(root/'.testtmp') or not destination.is_relative_to(root/'data/accounts') or destination.suffix!='.sqlite3':
        parser.error('Origen de ensayo o destino privado inválido.')
    target_key=destination.with_name(destination.name+'.signing.dpapi')
    if destination.exists() or target_key.exists():
        parser.error('El destino ya existe; no se sobrescribirá.')
    receipt=json.loads(args.receipt.read_text(encoding='utf-8'))
    if not receipt.get('source_read_only') or receipt.get('foreign_key_issues') or receipt.get('quick_check')!='ok':
        parser.error('Se requiere una copia de cuentas verificada.')
    expected=receipt.get('destination_file_sha256')
    if not expected or hashlib.sha256(source.read_bytes()).hexdigest()!=expected:
        parser.error('La copia cambió desde su verificación. No se promoverá.')
    before=inventory(source)
    if before['reader_accounts_usagebucket']['rows'] or before['reader_accounts_queryoperation']['rows'] or before['django_session']['rows']:
        parser.error('La copia contiene sesiones o consumo de ensayo; usa una copia nueva sin actividad.')
    from reader_accounts.signing_key import load_key
    load_key(source)  # Verifica DPAPI con el usuario actual; no imprime la clave.
    from scripts.knowledge.knowledge_campaign import sqlite_snapshot
    destination.parent.mkdir(parents=True,exist_ok=True)
    sqlite_snapshot(source,destination)
    source_key=source.with_name(source.name+'.signing.dpapi')
    with target_key.open('xb') as stream:
        stream.write(source_key.read_bytes())
    if inventory(destination)!=before:
        raise ValueError('No coincide el contenido persistente. Conservar ambas copias e investigar.')
    print(json.dumps({'persistent_copy_verified':True,'users':before['auth_user']['rows'],
                      'source_preserved':True,'services_started':False,'mysql_modified':False}))


if __name__=='__main__':
    main()
