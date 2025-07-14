import sqlite3
import pandas as pd

# Carga el CSV extraído desde el archivo KMZ
df = pd.read_csv("puntos_extraidos.csv")

# Conexión a la base de datos
conn = sqlite3.connect("entregas.db")
cursor = conn.cursor()

# Verificamos si las columnas existen
cursor.execute("PRAGMA table_info(entregas)")
columnas = [col[1] for col in cursor.fetchall()]
if "latitud" not in columnas:
    cursor.execute("ALTER TABLE entregas ADD COLUMN latitud REAL")
if "longitud" not in columnas:
    cursor.execute("ALTER TABLE entregas ADD COLUMN longitud REAL")

# Recorremos los puntos y actualizamos
for _, fila in df.iterrows():
    nombre = fila["nombre"].strip().upper()
    lat = fila["latitud"]
    lon = fila["longitud"]

    cursor.execute("""
        UPDATE entregas
        SET latitud = ?, longitud = ?
        WHERE UPPER(jefe_hogar) = ?
    """, (lat, lon, nombre))

conn.commit()
conn.close()
print("Coordenadas actualizadas correctamente.")
