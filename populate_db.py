import os
import django
import requests
from sentence_transformers import SentenceTransformer
from pinecone import Pinecone, ServerlessSpec
from tqdm import tqdm # Para ver una barra de progreso

# Configurar el entorno de Django para poder usar los settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'litmate_project.settings')
django.setup()

from django.conf import settings

def populate_vector_db():
    print("Inicializando componentes...")
    # --- 1. Inicializar Modelo de Embeddings y Pinecone (CON REGIÓN CORREGIDA) ---
    try:
        pc = Pinecone(api_key=settings.PINECONE_API_KEY)
        INDEX_NAME = 'litmate-book-index'
        
        # Revisa si el índice existe
        if INDEX_NAME not in pc.list_indexes().names():
            print(f"El índice '{INDEX_NAME}' no existe. Creándolo...")
            pc.create_index(
                name=INDEX_NAME,
                dimension=384, # all-MiniLM-L6-v2 tiene 384 dimensiones
                metric='cosine',
                spec=ServerlessSpec(
                    cloud='aws',
                    region='us-east-1' # <-- ¡CAMBIO REALIZADO AQUÍ!
                )
            )
            print(f"Índice '{INDEX_NAME}' creado en Pinecone.")
        
        pinecone_index = pc.Index(INDEX_NAME)
        embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        print("Componentes inicializados correctamente.")
    except Exception as e:
        print(f"Error fatal al inicializar: {e}")
        return

    # --- 2. Obtener libros de la API de Google Books ---
    print("Obteniendo libros de Google Books...")
    temas = ["aventura", "ciencia ficción", "misterio", "historia", "biografía", "tecnología", "fantasía"]
    libros = []
    
    for tema in temas:
        try:
            url = f"https://www.googleapis.com/books/v1/volumes?q=subject:{tema}&maxResults=40&lang=es"
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            
            if 'items' in data:
                for item in data['items']:
                    info = item.get('volumeInfo', {})
                    if info.get('description') and info.get('title'):
                        libros.append({
                            'id': item['id'],
                            'title': info['title'],
                            'text': info['description'],
                            'categories': info.get('categories', [])
                        })
        except requests.exceptions.RequestException as e:
            print(f"Error obteniendo libros del tema '{tema}': {e}")
    
    print(f"Se encontraron {len(libros)} libros para procesar.")
    if not libros:
        return
        
    # --- 3. Crear embeddings y subirlos a Pinecone ---
    print("Creando embeddings y subiendo a Pinecone...")
    batch_size = 32
    for i in tqdm(range(0, len(libros), batch_size)):
        batch = libros[i:i+batch_size]
        
        ids = [libro['id'] for libro in batch]
        texts = [libro['text'] for libro in batch]
        metadata = [{'title': libro['title'], 'text': libro['text'], 'categories': libro.get('categories', [])} for libro in batch]
        
        # Crear embeddings
        embeddings = embedding_model.encode(texts).tolist()
        
        # Subir a Pinecone
        pinecone_index.upsert(vectors=zip(ids, embeddings, metadata))
        
    print("\n¡Proceso completado! La base de datos vectorial ha sido poblada.")

if __name__ == "__main__":
    populate_vector_db()