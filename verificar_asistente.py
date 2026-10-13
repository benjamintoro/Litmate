"""Verifica el asistente offline sin migrar ni tocar la base del proyecto."""
from verificar_proyecto import main

if __name__ == "__main__":
    raise SystemExit(1 if main(["core"]) else 0)
