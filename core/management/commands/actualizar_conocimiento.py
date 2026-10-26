"""Trabajador opcional y reiniciable para la memoria literaria auxiliar."""
import json
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.literary_learning import (DEFAULT_PROVIDERS, PROVIDERS, REQUIREMENTS, lower_worker_priority,
    provider_order, run_refresh_batch, schedule_known_works)


class Command(BaseCommand):
    help = ('Actualiza identidades bibliográficas ya conocidas en una cola SQLite independiente. '
            'Sin LLM, novelas completas, datos de usuario ni APIs de pago.')

    def add_arguments(self, parser):
        parser.add_argument('--database', type=Path, help='SQLite auxiliar; nunca es la base de Django.')
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument('--once', action='store_true', help='Procesa un lote y sale (por defecto).')
        mode.add_argument('--watch', action='store_true', help='Repite lotes hasta Ctrl+C, conservando la cola.')
        parser.add_argument('--max-jobs', type=int, default=2)
        parser.add_argument('--max-seconds', type=float, default=30)
        parser.add_argument('--job-seconds', type=float, default=8)
        parser.add_argument('--interval', type=float, default=60)
        parser.add_argument('--pause', type=float, default=1)
        parser.add_argument('--enqueue-known', action='store_true',
                            help='Encola identidades existentes con evidencia vencida; no rastrea sitios.')
        parser.add_argument('--provider', choices=('auto', *PROVIDERS), default='auto',
            help='Wikipedia es opt-in y sólo consulta introducciones oficiales, sin leer páginas completas.')
        parser.add_argument('--requirement', choices=sorted(REQUIREMENTS), default='metadata')
        parser.add_argument('--stats', action='store_true', help='Lee señales agregadas sin realizar red.')
        parser.add_argument('--delete-usage', action='store_true',
                            help='Elimina sólo señales agregadas; conserva libros, fuentes y trabajos.')

    def handle(self, *args, **options):
        from core.literary_memory import default_path, initialize_store, usage_stats, delete_usage
        database = options.get('database') or default_path()
        try:
            if options.get('delete_usage'):
                deleted = delete_usage(database=database)
                self.stdout.write(json.dumps({'deleted_usage_rows': deleted, 'network': False}))
                return
            if options.get('stats'):
                stats = usage_stats(database=database)
                self.stdout.write(json.dumps({'usage': stats,
                    'eligible_provider_order': provider_order(stats, requirement=options['requirement']),
                    'network': False}, ensure_ascii=False))
                return
            if not 1 <= options['max_jobs'] <= 20 or not 1 <= options['max_seconds'] <= 120:
                raise ValueError('Usa --max-jobs entre 1 y 20 y --max-seconds entre 1 y 120.')
            if not 1 <= options['job_seconds'] <= 12 or not 1 <= options['pause'] <= 30:
                raise ValueError('Usa --job-seconds entre 1 y 12 y --pause entre 1 y 30.')
            if not 5 <= options['interval'] <= 86400:
                raise ValueError('Usa --interval entre 5 y 86400 segundos.')
            initialize_store(database=database)
            lower_worker_priority()
            while True:
                if options.get('enqueue_known'):
                    provider = options['provider']
                    if provider == 'auto':
                        eligible = (('wikidata',) if options['requirement'] in {
                            'characters', 'character_detail', 'relationships'} else DEFAULT_PROVIDERS)
                        provider = provider_order(usage_stats(database=database),
                            requirement=options['requirement'], eligible=eligible)[0]
                    queued = schedule_known_works(database=database, maximum=options['max_jobs'],
                        requirement=options['requirement'], provider=provider)
                    self.stdout.write(json.dumps({'scheduled': len(queued)}))
                report = run_refresh_batch(database=database, max_jobs=options['max_jobs'],
                    max_seconds=options['max_seconds'], job_seconds=options['job_seconds'],
                    pause_seconds=options['pause'])
                self.stdout.write(json.dumps(report, ensure_ascii=False))
                if not options.get('watch'):
                    break
                # Se divide la pausa para facilitar Ctrl+C y no bloquear la
                # consola durante un intervalo largo. No hay hilo residente en Django.
                remaining = options['interval']
                while remaining > 0:
                    duration = min(remaining, 1)
                    time.sleep(duration)
                    remaining -= duration
        except KeyboardInterrupt:
            self.stdout.write('Trabajador detenido; la cola y los checkpoints se conservan.')
        except (OSError, TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from None
