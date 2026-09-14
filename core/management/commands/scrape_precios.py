import time
from django.core.management.base import BaseCommand
from core.models import Libro
from core.scraper import obtener_datos_comparador_libro


class Command(BaseCommand):
    help = 'Ejecuta web scraping de precios y enlaces directos para los libros del catálogo LitMate'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=15, help='Límite de libros a procesar')
        parser.add_argument('--force', action='store_true', help='Forzar actualización ignorando caché')

    def handle(self, *args, **options):
        limit = options['limit']
        force = options['force']
        
        libros = Libro.objects.select_related('autor').all()[:limit]
        total = len(libros)
        self.stdout.write(self.style.SUCCESS(f"Iniciando scraping de precios para {total} libros..."))

        exitosos = 0
        for idx, libro in enumerate(libros, 1):
            titulo = libro.titulo
            autor = libro.autor.nombre if libro.autor else ""
            isbn = libro.isbn_13 or libro.isbn_10 or ""
            
            self.stdout.write(f"[{idx}/{total}] Scraping '{titulo}' ({autor})...")
            try:
                datos = obtener_datos_comparador_libro(
                    libro_id=libro.id,
                    titulo=titulo,
                    autor=autor,
                    isbn=isbn,
                    force_refresh=force
                )
                tienda_top = datos['tiendas'][0] if datos.get('tiendas') else None
                if tienda_top:
                    self.stdout.write(self.style.SUCCESS(
                        f"  -> OK: {tienda_top['tienda']} | {tienda_top.get('precio_formateado')} | {tienda_top.get('enlace_directo')[:60]}..."
                    ))
                    exitosos += 1
                time.sleep(1)  # Pausa de cortesía para no saturar
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  -> Error: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Finalizado. {exitosos}/{total} libros actualizados correctamente."))
