"""Reutiliza CDP existente para comprobar una tarjeta real en el ensayo8007."""
import getpass
import json
from pathlib import Path
import subprocess


def main():
    source = Path('scripts/demo/capturar_demo.mjs').read_text(encoding='utf8')
    start = 'const questions = config.navigation ? ['
    end = '  ];\n  for (const question of questions)'
    marker = '  clearInterval(timer);\n  await sleep(500);'
    assert start in source and end in source and marker in source
    source = source.replace(start, 'const questions = config.questions || (config.navigation ? [')
    source = source.replace(end, '  ]);\n  for (const question of questions)')
    source = source.replace('let scrollAudit = [];', 'let scrollAudit = [];\nlet imageChecks = [];')
    inspect = ('  imageChecks = await evaluate("Array.from(document.querySelectorAll(\'.lm-chat-book-cover img\'))'
               '.map(i=>({url:i.src,loaded:i.naturalWidth>0,complete:i.complete}))");\n')
    source = source.replace(marker, inspect + marker)
    source = source.replace('frames, conversation, navigation, mobileChecks, scrollAudit,',
                            'frames, conversation, navigation, mobileChecks, scrollAudit, imageChecks,')
    script = Path('.testtmp/recall-final-http-20261031/browser-validation.mjs')
    script.write_text(source, encoding='utf8')
    secret = getpass.getpass('Clave del ensayo8007 para navegador (oculta): ')
    config = {'folder': str(Path('reports/recuerdos_opencode_20261031/navegador_final').resolve()),
              'password':secret, 'port':8007,
              'questions':['Una sociedad donde se prohíben los libros y los queman']}
    return subprocess.run(['node', str(script.resolve())], input=json.dumps(config), encoding='utf8').returncode


if __name__ == '__main__':
    raise SystemExit(main())
