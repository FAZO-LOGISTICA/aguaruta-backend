import pandas as pd
import psycopg2

DB_URL = "postgresql://aguaruta_db_user:u1JUg0dcbEYzzzoF8N4lsbdZ6c2ZXyPb@dpg-d25b5mripnbc73dpod0g-a.oregon-postgres.render.com/aguaruta_db"
csv_file = "base_datos_todos_con_coordenadas.csv"

# Cargar CSV
df = pd.read_csv(csv_file)

# Normalizar nombres de columnas y limpiar espacios
df.columns = [col.strip().lower().replace(" ", "_").replace("(jefe_de_hogar)", "nombre") for col in df.columns]

# Renombrar columnas del CSV para que coincidan con la base de datos
rename_map = {
    "id_camión": "camion",
    "conductor": "nombre",  # Solo si tienes una columna así
    "nombre_(jefe_de_hogar)": "nombre",
    "nombre": "nombre",
    "dia": "dia",
    "telefono": "telefono",
    "latitud": "latitud",
    "longitud": "longitud",
    "litros_de_entrega": "litros",
    "litros": "litros"
}
df = df.rename(columns=rename_map)

# Solo columnas relevantes (ajusta si tu base tiene otras)
expected_columns = ["camion", "nombre", "latitud", "longitud", "litros", "dia", "telefono"]
df = df[[col for col in expected_columns if col in df.columns]]

# ELIMINA FILAS TOTALMENTE VACÍAS
df = df.dropna(how='all')

# OPCIONAL: SOLO SI "camion" y "nombre" están vacíos, también omite (así nunca subes basura)
df = df.dropna(subset=["camion", "nombre"], how='any')

# Conexión a la base
conn = psycopg2.connect(DB_URL)
cur = conn.cursor()

# Limpia la tabla antes de importar (opcional, borra todo)
cur.execute("TRUNCATE TABLE ruta_activa RESTART IDENTITY;")

for idx, row in df.iterrows():
    cur.execute("""
        INSERT INTO ruta_activa (camion, nombre, latitud, longitud, litros, dia, telefono)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (
        row.get("camion"),
        row.get("nombre"),
        row.get("latitud"),
        row.get("longitud"),
        row.get("litros"),
        row.get("dia"),
        row.get("telefono")
    ))

conn.commit()
cur.close()
conn.close()
print("¡Importación completada con solo registros válidos!")
