"""Clave de firma persistente protegida por DPAPI del usuario Windows actual."""
import ctypes
from contextlib import closing
from ctypes import wintypes
import os
from pathlib import Path
import secrets
import sqlite3


def _dpapi(value, *, decrypt=False):
    if os.name != 'nt':
        raise ValueError('Este lanzador protege la clave mediante DPAPI de Windows.')

    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError('No fue posible abrir la clave protegida para este usuario de Windows.')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def load_key(database):
    database = Path(database).resolve()
    path = database.with_name(database.name + '.signing.dpapi')
    if path.exists():
        return _dpapi(path.read_bytes(), decrypt=True).decode('ascii')
    if not database.is_file():
        raise ValueError('Prepara primero la base privada; el arranque nunca ejecuta migraciones.')
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('La base privada no pasó quick_check.')
        required = {'auth_user', 'django_session', 'reader_accounts_usagebucket', 'reader_accounts_queryoperation'}
        present = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required <= present:
            raise ValueError('Falta el esquema privado; no se aplicarán migraciones automáticamente.')
        if db.execute('SELECT COUNT(*) FROM django_session').fetchone()[0] or db.execute(
                'SELECT COUNT(*) FROM reader_accounts_usagebucket').fetchone()[0]:
            raise ValueError('Falta la clave de una base ya utilizada. Restaura su respaldo; no se regenerará.')
    value = secrets.token_urlsafe(64)
    with path.open('xb') as stream:
        stream.write(_dpapi(value.encode('ascii')))
    return value
