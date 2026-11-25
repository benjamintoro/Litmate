"""Carga la configuración privada de cuentas sin editar archivos .env."""
import json
import os
from pathlib import Path
import re

from .signing_key import _dpapi


def activate(root):
    root = Path(root).resolve()
    config = root / 'data/production/accounts-mysql.json'
    if not config.is_file():
        return False
    values = json.loads(config.read_text(encoding='utf8'))
    if (set(values) != {'schema', 'user'} or not re.fullmatch(r'litmate_accounts_[a-z0-9_]{1,45}', values['schema'])
            or not re.fullmatch(r'litmate_[a-z0-9_]{1,20}', values['user'])):
        raise ValueError('Configuración privada de cuentas inválida.')
    password = _dpapi((config.parent / 'accounts-mysql.dpapi').read_bytes(), decrypt=True).decode('utf8')
    os.environ.update(LITMATE_ACCOUNTS_BACKEND='mysql', LITMATE_ACCOUNTS_MYSQL_NAME=values['schema'],
                      LITMATE_ACCOUNTS_MYSQL_USER=values['user'], LITMATE_ACCOUNTS_MYSQL_PASSWORD=password)
    return True
