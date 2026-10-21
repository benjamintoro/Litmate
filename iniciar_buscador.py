"""Inicia SearXNG local. Genera un secreto interno: no es una clave de API."""
import os
import secrets
import subprocess
import time
import json
from urllib.request import build_opener, ProxyHandler
from pathlib import Path

if __name__ == '__main__':
    environment = os.environ.copy()
    environment['LITMATE_SEARCH_SECRET'] = secrets.token_hex(32)
    try:
        subprocess.run(['docker', 'compose', '--env-file', 'searxng/compose.env',
                        '-f', 'docker-compose.ia.yml', 'up', '-d'],
                       cwd=Path(__file__).resolve().parent, env=environment, check=True)
        opener = build_opener(ProxyHandler({}))
        for attempt in range(20):
            try:
                with opener.open('http://127.0.0.1:8080/healthz', timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(1)
        else:
            raise SystemExit('El contenedor se inició, pero no responde. Revisa docker compose -f docker-compose.ia.yml logs --tail 30.')
        with opener.open('http://127.0.0.1:8080/search?q=libros&format=json&engines=wikipedia', timeout=10) as response:
            result = json.load(response)
        if not isinstance(result.get('results'), list):
            raise SystemExit('SearXNG responde, pero la API JSON no tiene el formato esperado.')
        print('SearXNG local y API JSON disponibles: http://127.0.0.1:8080')
        if result.get('unresponsive_engines'):
            print('Hay motores temporalmente no disponibles; el asistente conserva las otras fuentes gratuitas.')
    except FileNotFoundError:
        raise SystemExit('Instala Docker Desktop y ábrelo antes de ejecutar este comando.')
    except subprocess.CalledProcessError:
        raise SystemExit('Docker no pudo iniciar SearXNG. Revisa que esté abierto y el puerto 8080 libre.')
    except (OSError, ValueError):
        raise SystemExit('No se pudo comprobar JSON. Revisa los motores y docker compose -f docker-compose.ia.yml logs --tail 30.')
