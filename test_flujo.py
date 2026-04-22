#!/usr/bin/env python
"""
Test de flujo completo del chatbot con Google Books
"""
import sys
sys.path.insert(0, 'd:\\DESCARGAS\\litmate_projecto\\litmate_project')

import requests

def test_search(query, max_results=1):
    """Simula la búsqueda de libros"""
    try:
        query_escaped = requests.utils.quote(query)
        url = f"https://www.googleapis.com/books/v1/volumes?q={query_escaped}&maxResults={max_results * 2}&langRestrict=es&orderBy=relevance"
        response = requests.get(url, timeout=5)
        data = response.json()
        
        results = []
        if 'items' in data:
            for item in data['items']:
                info = item.get('volumeInfo', {})
                titulo = info.get('title', '')
                description = info.get('description', '')
                
                if not titulo or len(titulo) < 2:
                    continue
                if not description or len(description) < 50:
                    continue
                
                book_id = item.get('id', '')
                link = f"https://books.google.com/books?id={book_id}" if book_id else ""
                
                results.append({
                    'titulo': titulo,
                    'autores': info.get('authors', ['Desconocido']),
                    'descripcion': description[:150],
                    'link': link
                })
                
                if len(results) >= max_results:
                    break
        
        return results
    except Exception as e:
        print(f"Error: {e}")
        return []

print("=" * 70)
print("TEST: Flujo de búsqueda de libros")
print("=" * 70)

test_cases = [
    ("Narnia", "Búsqueda simple: Narnia"),
    ("Cronicas de narnia", "Búsqueda simple: Cronicas de narnia"),
    ("El señor de los anillos", "Búsqueda simple: El señor de los anillos"),
    ("Quién es el autor de 1984", "Patrón + extracción: 1984"),
]

for query, description in test_cases:
    print(f"\n{description}")
    print(f"Query: '{query}'")
    results = test_search(query)
    
    if results:
        book = results[0]
        print(f"  ✓ Encontrado: {book['titulo']}")
        print(f"    Autor: {', '.join(book['autores'])}")
        print(f"    Descripción: {book['descripcion'][:80]}...")
        print(f"    Link: {book['link'][:50]}...")
    else:
        print(f"  ✗ NO encontrado")

print("\n" + "=" * 70)
print("Tests completados")
print("=" * 70)
