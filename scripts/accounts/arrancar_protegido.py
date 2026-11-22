"""Arranque de la instancia existente con secretos DPAPI del usuario de Windows."""
import getpass
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def saved_basic(prompt):
    if not prompt.startswith('Contraseña Basic transitoria'):
        raise ValueError('El lanzador solicitó una credencial inesperada.')
    from reader_accounts.signing_key import _dpapi
    return _dpapi((ROOT/'data/production/basic.dpapi').read_bytes(), decrypt=True).decode('utf-8')


if __name__ == '__main__':
    from reader_accounts.mysql_config import activate
    activate(ROOT)
    os.environ.update(LITMATE_WEBPAY_INTEGRATION_ENABLED='1', LITMATE_COMMUNITY_ENABLED='1', LITMATE_SIMULATED_CHECKOUT_ENABLED='1',
                      LITMATE_CHECKOUT_TEST_SCENARIOS='0')
    sys.argv = ['iniciar_produccion.py', '--origin', os.environ.get('LITMATE_PUBLIC_ORIGIN', 'https://xato.taila70665.ts.net'),
        '--proxy', 'loopback-tls', '--port', '8003', '--accounts-db', 'data/accounts/users.sqlite3',
        '--runtime', 'data/production/runtime', '--mysql-secret-file', 'data/production/mysql.dpapi',
        '--basic', '--google-books-sin-facturacion']
    getpass.getpass = saved_basic
    from iniciar_produccion import main
    raise SystemExit(main())
