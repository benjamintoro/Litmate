"""Compatibilidad de instalación: la configuración vive en ai_settings.py.

No pegues otro bloque de variables sobre settings.py. Importa este módulo
únicamente después de definir BASE_DIR, o utiliza el settings.py del proyecto.
"""
from pathlib import Path
from litmate_project.ai_settings import apply_ai_settings

apply_ai_settings(globals(), globals().get('BASE_DIR', Path(__file__).resolve().parent))
