"""Lotes de vectores reanudables para originales autorizados de la biblioteca.

No contiene texto, respuestas ni datos de conversaciones. No se activa para
colecciones personales ni sustituye al índice final publicado atómicamente.
"""
from contextlib import closing
import hashlib
import math
from pathlib import Path
import re
import sqlite3
import struct


VERSION = 'library-vector-cache-v1'


def validate_library_metadata(files, metadata):
    for path in files:
        item = metadata.get(path.name, {})
        rights = item.get('rights', {}) if isinstance(item, dict) else {}
        if (not isinstance(item, dict) or not isinstance(rights, dict)
                or item.get('indexing_authorized') is not True or item.get('kind') != 'excerpt'
                or not re.fullmatch(r'[a-f0-9]{32}', str(item.get('library_document_id', '')))
                or not re.fullmatch(r'[a-f0-9]{64}', str(item.get('original_sha256', '')))
                or not item.get('license') or rights.get('jurisdiction') != 'CL'
                or rights.get('edition_covered') is not True
                or rights.get('status') not in {'public_domain', 'open_license', 'explicit_permission'}):
            raise ValueError('La caché incremental sólo admite originales de biblioteca autorizados')


def _blob_valid(size, blob, digest):
    if (not isinstance(size, int) or not 1 <= size <= 2048
            or not isinstance(blob, bytes) or len(blob) != 4 * size
            or hashlib.sha256(blob).hexdigest() != digest):
        return False
    values = struct.unpack('<' + 'f' * size, blob)
    return all(math.isfinite(value) for value in values) and any(value != 0 for value in values)


class LibraryVectorCache:
    def __init__(self, path, folder, index, identity, *, maximum=256_000_000):
        self.path = Path(path).resolve()
        self.folder, self.index = str(Path(folder).resolve()), str(Path(index).resolve())
        self.maximum = max(65536, min(int(maximum), 1_000_000_000))
        self.model, self.digest = identity
        self.full = False
        if (not isinstance(self.model, str) or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,100}', self.model)
                or not isinstance(self.digest, str) or not re.fullmatch(r'[a-f0-9]{64}', self.digest)
                or 'cloud' in self.model.lower() or '..' in self.model):
            raise ValueError('Identidad de modelo local inválida para la caché')
        if self.path == Path(index).resolve():
            raise ValueError('La caché no puede reemplazar el índice final')
        from django.conf import settings
        if settings.configured:
            protected = [Path(value['NAME']).resolve() for value in settings.DATABASES.values()
                         if value.get('NAME') and value['NAME'] != ':memory:']
            for name in dir(settings):
                if name.startswith('LITMATE_') and name.endswith('_DB'):
                    value = getattr(settings, name, None)
                    if value:
                        protected.append(Path(value).resolve())
            if self.path in protected:
                raise ValueError('La caché necesita una base auxiliar exclusiva')
        if self.path.is_file():
            with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)) as previous:
                try:
                    owner = previous.execute('SELECT version,folder,destination FROM vector_cache_owner WHERE id=1').fetchone()
                except sqlite3.Error:
                    owner = None
            if owner != (VERSION, self.folder, self.index):
                raise ValueError('El archivo no es una caché propia de esta biblioteca e índice')
            if self.path.stat().st_size > self.maximum:
                raise ValueError('La caché existente supera el límite de almacenamiento')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=3)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS vector_cache_owner (
                id INTEGER PRIMARY KEY,version TEXT,folder TEXT,destination TEXT);
            CREATE TABLE IF NOT EXISTS vectors (
                model TEXT,digest TEXT,chunk_id TEXT,dimension INTEGER,vector BLOB,
                vector_sha256 TEXT,PRIMARY KEY(model,digest,chunk_id));
            CREATE TABLE IF NOT EXISTS model_dimensions (
                model TEXT,digest TEXT,dimension INTEGER,PRIMARY KEY(model,digest));
        ''')
        self.db.execute('INSERT OR IGNORE INTO vector_cache_owner VALUES(1,?,?,?)',
                        (VERSION, self.folder, self.index))
        self.db.commit()

    def get(self, chunk_id):
        row = self.db.execute('SELECT dimension,vector,vector_sha256 FROM vectors '
            'WHERE model=? AND digest=? AND chunk_id=?', (self.model, self.digest, chunk_id)).fetchone()
        expected = self.db.execute('SELECT dimension FROM model_dimensions WHERE model=? AND digest=?',
                                   (self.model, self.digest)).fetchone()
        return row[:2] if row and expected == (row[0],) and _blob_valid(*row) else None

    def put_batch(self, rows):
        """Confirma un lote completo antes de seguir con el siguiente lote."""
        if self.full or not rows:
            return
        dimension = None
        for chunk_id, size, blob in rows:
            if not re.fullmatch(r'[a-f0-9]{32}', chunk_id):
                raise ValueError('Identificador de fragmento inválido')
            if not _blob_valid(size, blob, hashlib.sha256(blob).hexdigest()):
                raise ValueError('Vector inválido para la caché persistente')
            if dimension is not None and size != dimension:
                raise ValueError('Dimensiones inconsistentes en el lote')
            dimension = size
        previous = self.db.execute('SELECT dimension FROM model_dimensions WHERE model=? AND digest=?',
                                   (self.model, self.digest)).fetchone()
        if previous and previous != (dimension,):
            raise ValueError('El mismo modelo cambió su dimensión de embeddings')
        current_bytes = self.db.execute('PRAGMA page_count').fetchone()[0] * self.db.execute('PRAGMA page_size').fetchone()[0]
        if current_bytes + sum(len(row[2]) + 1024 for row in rows) > self.maximum:
            self.full = True
            return
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO model_dimensions VALUES(?,?,?)',
                             (self.model, self.digest, dimension))
            self.db.executemany('INSERT OR REPLACE INTO vectors VALUES(?,?,?,?,?,?)',
                ((self.model, self.digest, chunk_id, size, blob, hashlib.sha256(blob).hexdigest())
                 for chunk_id, size, blob in rows))

    def close(self):
        self.db.close()
