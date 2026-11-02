"""Graba únicamente el navegador aislado de la demo local, sin credenciales en disco."""
import argparse
import getpass
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--carpeta', type=Path, required=True)
    parser.add_argument('--puerto', type=int, default=8002)
    parser.add_argument('--navegacion', action='store_true', help='Recorre el frontend y prueba dos turnos con navegación intermedia.')
    parser.add_argument('--movil-cuentas', action='store_true', help='Matriz móvil del perfil de cuentas aislado, con datos sintéticos.')
    args = parser.parse_args()
    if not 1024 <= args.puerto <= 65535:
        parser.error('Puerto local inválido.')
    folder = args.carpeta.resolve()
    if not folder.is_relative_to(ROOT / 'reports') or folder.exists():
        parser.error('Usa una carpeta nueva dentro de reports.')
    password = getpass.getpass('Contraseña de acceso demo local (oculta): ')
    result = subprocess.run(['node', str(Path(__file__).with_suffix('.mjs'))],
        input=json.dumps({'folder': str(folder), 'password': password, 'port': args.puerto,
                          'navigation': args.navegacion, 'readerMobile': args.movil_cuentas}), text=True,
        encoding='utf-8', cwd=ROOT, check=False)
    password = None
    if result.returncode:
        return result.returncode
    capture = json.loads((folder / 'captura.json').read_text(encoding='utf-8'))
    if args.movil_cuentas and (not capture.get('mobileChecks') or capture.get('errors') or
                              not all(check.get('passed') for check in capture['mobileChecks'])):
        print('La verificación móvil detectó fallos; conserva captura.json para revisarlos.')
        return 1
    from PIL import Image
    frames = capture['frames']
    images = []
    for frame in frames:
        with Image.open(folder / frame['file']) as image:
            images.append(image.convert('RGB').resize((1024, 640)))
    if images:
        durations = [max(100, round((frames[i + 1]['seconds'] - frame['seconds']) * 1000))
                     if i + 1 < len(frames) else 3000 for i, frame in enumerate(frames)]
        images[0].save(folder / 'funcionamiento_real.webp', save_all=True,
            append_images=images[1:], duration=durations, loop=0, quality=76)
    print('Capturas y grabación WebP guardadas en ' + str(folder))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
