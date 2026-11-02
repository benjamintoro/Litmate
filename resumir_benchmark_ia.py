"""Entrada compatible; implementacion en scripts.analysis.resumir_benchmark_ia."""
import sys
from scripts.analysis import resumir_benchmark_ia as _implementation


if __name__ == '__main__':
    raise SystemExit(_implementation.main())
else:
    # One module object preserves legacy imports, patches and shared state.
    sys.modules[__name__] = _implementation
