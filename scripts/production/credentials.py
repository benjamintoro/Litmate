"""Preparación manual opcional de credencial MySQL DPAPI; nunca la imprime."""
import argparse
import getpass
from pathlib import Path
from reader_accounts.signing_key import _dpapi

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file',type=Path,required=True)
    args=parser.parse_args();target=args.file.resolve()
    if not target.is_relative_to(ROOT/'data/production') or target.exists():
        parser.error('Usa un archivo NUEVO dentro de data/production; no se sobrescriben secretos.')
    password=getpass.getpass('Contraseña MySQL local (oculta): ')
    confirmation=getpass.getpass('Repite la contraseña (oculta): ')
    if not password or password!=confirmation:parser.error('La confirmación no coincide.')
    protected=_dpapi(password.encode('utf8'));password=confirmation=None
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb') as stream:stream.write(protected)
    print('Credencial cifrada para este usuario de Windows. No se ha iniciado ningún servicio.')


if __name__=='__main__':main()
