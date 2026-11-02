"""Desactiva Ollama Cloud conservando las otras opciones del usuario."""
import json
from pathlib import Path

if __name__ == '__main__':
    path = Path.home() / '.ollama' / 'server.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        configuration = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if not isinstance(configuration, dict):
            raise ValueError('La configuración debe ser un objeto JSON')
    except (ValueError, OSError) as exc:
        raise SystemExit('No se modificó server.json. Revisa su formato: ' + str(exc))
    configuration['disable_ollama_cloud'] = True
    path.write_text(json.dumps(configuration, indent=2) + '\n', encoding='utf-8')
    print('Ollama Cloud desactivado en la configuración. Cierra Ollama completamente y vuelve a abrirlo.')
