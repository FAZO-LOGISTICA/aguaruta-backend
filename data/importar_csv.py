import pandas as pd
import psycopg2

# Conexión a tu base de datos
DB_URL = "postgresql://aguaruta_db_user:u1JUg0dcbEYzzzoF8N4lsbdZ6c2ZXyPb@dpg-d25b5mripnbc73dpod0g-a.oregon-postgres.render.com/aguaruta_db"

# Carga del CSV
csv_file = "base_datos_todos_con_coordenadas.csv"
df = pd.read_csv(csv_file)

# Limpieza de nombres de columnas (quitar espacios al inicio/fin)
df.columns = [col.strip().replace('\n', ' ').replace('\r', '') for col in df.columns]

# Mapear nombres de columnas del CSV a la tabla ruta_activa
col_map = {
    'id camión': 'camion',
    'conductor': 'nombre',
    'dia': 'dia',
    'telefono': 'telefono',
    'latitud': 'latitud',
    'longitud': 'longitud',
    'litros de entrega': 'litros'
    # Puedes agregar aquí más mapeos si lo deseas
}

# Solo usar las columnas que existen en el CSV y en la base de datos
cols_db = ['camion', 'nombre', 'dia', 'telefono', 'latitud', 'longitud', 'litros']

# Prepara los datos para insertar
rows_to_insert = []
for _, row in df.iterrows():
    values = []
    for col in cols_db:
        # Obtiene el valor del CSV usando el mapeo, si no está deja None
        csv_col = [k for k, v in col_map.items() if v == col]
        val = row[csv_col[0]] if csv_col and csv_col[0] in row else None
        values.append(val)
    # Inserta aunque haya columnas vacías
    rows_to_insert.append(tuple(values))

# Inserción en la base de datos
conn = psycopg2.connect(DB_URL)
cur = conn.cursor()

# OPCIONAL: Borra la tabla antes de cargar nuevos datos
# cur.execute("TRUNCATE TABLE ruta_activa RESTART IDENTITY;")
# conn.commit()

for row in rows_to_insert:
    cur.execute("""
        INSERT INTO ruta_activa (camion, nombre, dia, telefono, latitud, longitud, litros)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, row)

conn.commit()
cur.close()
conn.close()
print("¡Importación completada!")
