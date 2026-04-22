#!/usr/bin/env python
"""
Test simple para validar la extracción dinámica de libros desde Google Books
"""
import os
import django
import sys
import json

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'litmate_project.settings')
sys.path.insert(0, 'd:\\DESCARGAS\\litmate_projecto\\litmate_project')
django.setup()

from core.views import buscar_detalles_libro_google, search_google_books
import re

print("=" * 60)
print("TEST: Búsqueda dinámica de libros en Google Books")
print("=" * 60)

# Test 1: Buscar libro directo
print("\n[TEST 1] Búsqueda directa de 1984:")
resultado = search_google_books("1984", max_results=1)
if resultado:
    libro = resultado[0]
    print(f"  Título: {libro['titulo']}")
    print(f"  Autores: {', '.join(libro['autores'])}")
    print(f"  Link: {libro['google_books_link']}")
    print("  ✓ OK")
else:
    print("  ✗ NO encontrado")

# Test 2: Buscar detalles de un libro
print("\n[TEST 2] Búsqueda de detalles de 1984:")
detalles, link = buscar_detalles_libro_google("1984", "author")
if detalles:
    print(f"  Título: {detalles['titulo']}")
    print(f"  Autor: {detalles['author']}")
    print(f"  Trama: {detalles['trama'][:100]}...")
    print(f"  Link: {link}")
    print("  ✓ OK")
else:
    print("  ✗ NO encontrado")

# Test 3: Extracción de nombre de libro
print("\n[TEST 3] Extracción de nombres de libros:")
test_cases = [
    ("Quién es el autor de 1984", "1984"),
    ("Dime la trama de Harry Potter", "harry potter"),
    ("¿Cuál es la serie de El Señor de los Anillos?", "señor anillos"),
]

for msg, esperado_parcial in test_cases:
    # Simular la lógica de extracción
    msg_limpio = re.sub(r'[?¿!¡]', '', msg).lower()
    palabras_ignorar = {
        'quién', 'quien', 'qué', 'que', 'dime', 'cuéntame',
        'es', 'fue', 'son', 'están', 'está', 'el', 'la', 'los', 'las',
        'de', 'del', 'y', 'o', 'u', 'en', 'a', 'por', 'para', 'con',
        'sobre', 'escribió', 'escribio', 'autor', 'escritor',
        'trama', 'argumento', 'historia', 'sinopsis', 'personajes',
        'serie', 'saga', 'link', 'enlace', 'donde', 'dónde', 'leerlo',
        'cuéntame', 'necesito', 'quiero', 'me', 'gustaría', 'dí', 'cuál'
    }
    palabras = [p for p in msg_limpio.split() if p and p not in palabras_ignorar and len(p) > 1]
    resultado = ' '.join(palabras) if palabras else None
    
    check = "✓" if resultado and esperado_parcial in resultado else "✗"
    print(f"  {check} '{msg}'")
    print(f"     → '{resultado}'")

print("\n" + "=" * 60)
print("Tests completados")
print("=" * 60)
