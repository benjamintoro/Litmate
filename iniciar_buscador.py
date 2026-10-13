"""Inicia SearXNG local. Genera un secreto interno: no es una clave de API."""
import os
import secrets
import subprocess
from pathlib import Path

if __name__ == '__main__':
    environment = os.environ.copy()
    environment['LITMATE_SEARCH_SECRET'] = secrets.token_hex(32)
    try:
        subprocess.run(['docker', 'compose', '-f', 'docker-compose.ia.yml', 'up', '-d'],
                       cwd=Path(__file__).resolve().parent, env=environment, check=True)
        print('Buscador local: http://127.0.0.1:8080')
    except FileNotFoundError:
        raise SystemExit('Instala Docker Desktop y ábrelo antes de ejecutar este comando.')
    except subprocess.CalledProcessError:
        raise SystemExit('Docker no pudo iniciar SearXNG. Revisa que esté abierto y el puerto 8080 libre.')
