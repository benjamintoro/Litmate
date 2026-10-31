"""Descarga oficial reanudable; no importa datos ni modifica configuraciones."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time


def verify_file(path, size, sha1):
    if path.stat().st_size != size:
        raise ValueError('download_size_mismatch')
    first, second = hashlib.sha1(), hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            first.update(block)
            second.update(block)
    if first.hexdigest() != sha1:
        raise ValueError('download_checksum_mismatch')
    return second.hexdigest()


def download(item, destination, *, seconds=1800):
    name = item['name']
    match = re.fullmatch(r'ol_dump_(works|authors)_(\d{4}-\d{2}-\d{2})\.txt\.gz', name)
    if not match or not re.fullmatch('[a-f0-9]{40}', item['sha1']):
        raise ValueError('invalid_official_file')
    size = int(item['size'])
    if not 1 <= size <= 10*1024**3:
        raise ValueError('invalid_download_size')
    destination.mkdir(parents=True, exist_ok=True)
    final = destination/name
    partial = destination/(name+'.part')
    url = 'https://archive.org/download/ol_dump_'+match[2]+'/'+name
    if shutil.disk_usage(destination).free < size+10*1024**3:
        raise ValueError('insufficient_disk_margin')
    start = time.monotonic()
    if not final.exists():
        # curl valida TLS y Range. Si no hay soporte de Range, falla sin
        # anexar una respuesta completa al parcial. No se fuerzan reintentos.
        command = ['curl.exe','--fail','--location','--max-redirs','4',
                   '--proto','=https','--proto-redir','=https','--continue-at','-',
                   '--limit-rate','8M','--connect-timeout','20','--max-time',str(seconds),
                   '--retry','2','--retry-delay','10','--silent','--show-error',
                   '--user-agent','LitMate/Local-1.0 (https://github.com/benjamintoro/Litmate)',
                   '--output',str(partial),url]
        if not partial.exists() or partial.stat().st_size < size:
            result = subprocess.run(command, check=False)
            if result.returncode:
                return {'status':'partial','name':name,'bytes':partial.stat().st_size if partial.exists() else 0,
                        'curl_exit':result.returncode,'seconds':round(time.monotonic()-start,3)}
        sha256 = verify_file(partial,size,item['sha1'])
        if final.exists():
            raise ValueError('destination_already_exists')
        partial.rename(final)
    else:
        sha256 = verify_file(final,size,item['sha1'])
    report = {'status':'verified','name':name,'path':str(final),'bytes':size,
              'source_url':url,'sha1':item['sha1'],'sha256':sha256,
              'seconds':round(time.monotonic()-start,3)}
    receipt = destination/(name+'.verified.json')
    if not receipt.exists():
        receipt.write_text(json.dumps(report,indent=2),encoding='utf8')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--destination',type=Path,default=Path('data/adquisicion/openlibrary'))
    parser.add_argument('--kind',choices=['authors','works'],action='append',required=True)
    parser.add_argument('--seconds',type=int,default=1800)
    args=parser.parse_args()
    if not 30 <= args.seconds <= 3600:
        parser.error('Usa entre 30 y 3600 segundos por archivo.')
    files=json.loads(args.manifest.read_text(encoding='utf8'))
    for kind in args.kind:
        selected=[item for item in files if item['name'].startswith('ol_dump_'+kind+'_')]
        if len(selected)!=1:
            raise ValueError('ambiguous_manifest')
        print(json.dumps(download(selected[0],args.destination,seconds=args.seconds)),flush=True)


if __name__=='__main__':
    main()
