import pandas as pd
import psycopg2

# Configuración de la base de datos
DB_URL = "postgresql://aguaruta_db_user:u1JUg0dcbEYzzzoF8N4lsbdZ6c2ZXyPb@dpg-d25b5mripnbc73dpod0g-a.oregon-postgres.render.com/aguaruta_db"

# Leer CSV
df = pd.read_csv("base_datos_todos_con_coordenadas.csv")

# Columnas esperadas en la base de datos
columnas_db = {
    'camion': ['camion', 'id camión', 'camión', 'patente'],
    'nombre': ['nombre', 'nombre (jefe de hogar)', 'conductor'],
    'dia': ['dia', 'día'],
    'litros': ['litros', 'litros de entrega'],
    'telefono': ['telefono', 'teléfono'],
    'latitud': ['latitud'],
    'longitud': ['longitud']
}

# Buscar la mejor coincidencia para cada columna esperada
def get_value(row, posibles):
    for p in posibles:
        if p in row:
            return row[p]
    return None

# Abrir conexión
conn = psycopg2.connect(DB_URL)
cur = conn.cursor()

for _, row in df.iterrows():
    # Armar el diccionario de inserción
    data = {}
    for col, variantes in columnas_db.items():
        data[col] = get_value(row, variantes)

    # Insertar ignorando errores si faltan columnas
    cur.execute("""
        INSERT INTO ruta_activa (camion, nombre, dia, litros, telefono, latitud, longitud)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (
        data.get('camion'),
        data.get('nombre'),
        data.get('dia'),
        data.get('litros'),
        data.get('telefono'),
        data.get('latitud'),
        data.get('longitud')
    ))

conn.commit()
cur.close()
conn.close()
print("¡Importación completada!")

