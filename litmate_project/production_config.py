"""Origen, transporte y almacenamiento explícitos, sin contraseñas."""
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
import os
import re


@dataclass(frozen=True)
class ProductionConfig:
    root: Path
    origin: str
    host: str
    accounts: Path
    runtime: Path
    testing: bool
    gate: str
    port: int

    @classmethod
    def from_environment(cls, root, environment=None):
        env = os.environ if environment is None else environment
        root = Path(root).resolve()
        parsed = urlsplit(env.get('LITMATE_PUBLIC_ORIGIN', '').strip())
        try:
            port = parsed.port
        except ValueError as error:
            raise ValueError('El origen público tiene un puerto inválido.') from error
        host = (parsed.hostname or '').lower()
        if (parsed.scheme != 'https' or not host or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in ('', '/')
                or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}',host)
                or len(host)>253):
            raise ValueError('Indica un origen HTTPS con dominio explícito, sin rutas, comodines ni credenciales.')
        if env.get('LITMATE_PROXY_MODE') != 'loopback-tls':
            raise ValueError('Configura explícitamente el proxy loopback-tls.')
        testing = env.get('LITMATE_PRODUCTION_TESTING') == '1'
        account_raw, runtime_raw = env.get('LITMATE_ACCOUNTS_DB', ''), env.get('LITMATE_PRODUCTION_RUNTIME', '')
        if not account_raw or not runtime_raw or not Path(account_raw).is_absolute() or not Path(runtime_raw).is_absolute():
            raise ValueError('Las cuentas y el runtime requieren rutas absolutas distintas.')
        account, runtime = Path(account_raw).resolve(), Path(runtime_raw).resolve()
        if testing:
            allowed = root/'.testtmp'
            if not account.is_relative_to(allowed) or not runtime.is_relative_to(allowed):
                raise ValueError('El ensayo sólo admite almacenamiento propio dentro de .testtmp.')
        elif not account.is_relative_to(root/'data/accounts') or not runtime.is_relative_to(root/'data/production'):
            raise ValueError('Producción requiere cuentas y runtime en sus directorios privados.')
        if account.is_relative_to(runtime) or runtime.is_relative_to(account.parent):
            raise ValueError('Runtime y cuentas deben tener ubicaciones independientes.')
        gate = env.get('LITMATE_ACCESS_GATE', 'open')
        if gate not in ('open','basic'):
            raise ValueError('El modo de acceso sólo puede ser open o basic.')
        listen_port = int(env.get('LITMATE_PRODUCTION_PORT', '8010'))
        if not 1024<=listen_port<=65535:
            raise ValueError('Puerto local inválido.')
        if testing and listen_port==8003:
            raise ValueError('El ensayo no puede utilizar el puerto de la publicación.')
        origin = 'https://' + host + ((':'+str(port)) if port and port!=443 else '')
        return cls(root, origin, host, account, runtime, testing, gate, listen_port)
