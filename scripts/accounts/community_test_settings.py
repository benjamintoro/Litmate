"""Perfil reutilizable por pruebas sintéticas y demostración aislada."""
import os
from pathlib import Path
import secrets


def configure(folder, *, settings_module='litmate_project.reader_settings'):
    folder = Path(folder).resolve()
    root = Path(__file__).resolve().parents[2]
    if not folder.is_relative_to(root / '.testtmp'):
        raise ValueError('Utiliza una carpeta sintética bajo .testtmp.')
    folder.mkdir(parents=True, exist_ok=True)
    os.environ.update(
        DJANGO_SETTINGS_MODULE=settings_module,
        DB_ENGINE='sqlite',
        DB_SQLITE_PATH=str(folder / 'catalogue.sqlite3'),
        LITMATE_ACCOUNTS_DB=str(folder / 'accounts' / 'users.sqlite3'),
        LITMATE_DEMO_MODE='local',
        LITMATE_DEMO_WORKSPACE=str(folder),
        LITMATE_COMMUNITY_ENABLED='1',
        PYTHON_DOTENV_DISABLED='1',
        SECRET_KEY=secrets.token_urlsafe(64),
    )
    (folder / 'accounts').mkdir(exist_ok=True)
