#!/usr/bin/env python
"""
Script de prueba para validar el chatbot sin servidor web
"""
import os
import django
import sys

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'litmate_project.settings')
sys.path.insert(0, 'd:\\DESCARGAS\\litmate_projecto\\litmate_project')
django.setup()

from core.chatbot_data import BOOK_QUERY_PATTERNS, SOCIAL_PATTERNS, detect_genre
import re

def test_book_info():
    """Test que la información de libros se obtiene dinámicamente"""
    print("=== TEST 1: API GOOGLE BOOKS ===")
    print("Los libros ahora se obtienen dinámicamente de Google Books API")
    print("No hay información local precargada")
    print()

def test_patterns():
    """Test que los patrones de link existen"""
    print("=== TEST 2: PATTERNS ===")
    if 'link' in BOOK_QUERY_PATTERNS:
        print("✓ Patrón 'link' encontrado")
        print(f"  Pattern: {BOOK_QUERY_PATTERNS['link']['pattern']}")
        print(f"  Template: {BOOK_QUERY_PATTERNS['link']['response_template']}")
        
        # Test si detecta "link"
        test_msgs = ["link", "Link", "donde leerlo", "dónde leerlo", "enlace"]
        for msg in test_msgs:
            if re.search(BOOK_QUERY_PATTERNS['link']['pattern'], msg, re.I):
                print(f"  ✓ Detecta: '{msg}'")
            else:
                print(f"  ✗ NO detecta: '{msg}'")
    else:
        print("✗ Patrón 'link' NO encontrado")
    print()

def test_filtering():
    """Test que palabras cortas se ignoran"""
    print("=== TEST 3: FILTRADO ===")
    
    palabras_solo_ignorar = ['si', 'no', 'ok', 'link', 'hola', 'eres', 'soy']
    palabras_cortas_ignorar = ['si', 'no', 'ok', 'link', 'hola', 'eres', 'soy', 'es', 'donde', 'dónde', 'enlace']
    
    test_cases = [
        ("1984", False),  # Debería buscarse
        ("link", True),   # Debería ignorarse como palabra única
        ("Dime sobre 1984", False),  # Debería buscarse
        ("La trama de 1984", False),  # Debería buscarse
        ("19884", False),  # Typo, debería buscarse (pero mal)
    ]
    
    for msg, should_ignore in test_cases:
        msg_lower = msg.lower().strip()
        es_palabra_corta = msg_lower in palabras_solo_ignorar or (len(msg.split()) == 1 and any(w in msg_lower for w in palabras_cortas_ignorar))
        
        resultado = "IGNORADO" if es_palabra_corta else "BUSCADO"
        esperado = "IGNORADO" if should_ignore else "BUSCADO"
        check = "✓" if resultado == esperado else "✗"
        
        print(f"{check} '{msg}' → {resultado} (esperado: {esperado})")
    print()

if __name__ == "__main__":
    test_book_info()
    test_patterns()
    test_filtering()
    print("=== TESTS COMPLETADOS ===")
