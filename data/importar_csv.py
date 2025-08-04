import pandas as pd
import psycopg2

# Configuración de la base de datos (pon tu usuario, clave y host aquí)
DB_URL = "postgresql://aguaruta_db_user:u1JUg0dcbEYzzzoF8N4lsbdZ6c2ZXyPb@dpg-d25b5mripnbc73dpod0g-a.oregon-postgres.render.com/aguaruta_db"

# Lee el archivo CSV
csv_file = "base_datos_todos_con_coordenadas.csv"  # Cambia si tu archivo se llama distinto
df = pd.read_csv(csv_file)

conn = psycopg2.connect(DB_URL)
cur = conn.cursor()

for _, row in df.iterrows():
    # Si la columna no existe, pon None. Si el dato está vacío, pon None.
    camion = str(row['id camión']) if 'id camión' in row and pd.notnull(row['id camión']) else None
    nombre = str(row['nombre (jefe de hogar)']) if 'nombre (jefe de hogar)' in row and pd.notnull(row['nombre (jefe de hogar)']) else None
    dia = str(row['dia']) if 'dia' in row and pd.notnull(row['dia']) else None
    litros = int(row['litros de entrega']) if 'litros de entrega' in row and pd.notnull(row['litros de entrega']) else None
    telefono = str(row['telefono']) if 'telefono' in row and pd.notnull(row['telefono']) else None
    latitud = float(row['latitud']) if 'latitud' in row and pd.notnull(row['latitud']) else None
    longitud = float(row['longitud']) if 'longitud' in row and pd.notnull(row['longitud']) else None

    cur.execute("""
        INSERT INTO ruta_activa (camion, nombre, dia, litros, telefono, latitud, longitud)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (camion, nombre, dia, litros, telefono, latitud, longitud))

conn.commit()
cur.close()
conn.close()

print("Importación completada.")
