import pandas as pd
import psycopg2

DB_URL = "postgresql://aguaruta_db_user:u1JUg0dcbEYzzzoF8N4lsbdZ6c2ZXyPb@dpg-d25b5mripnbc73dpod0g-a.oregon-postgres.render.com/aguaruta_db"
csv_file = "base_datos_todos_con_coordenadas.csv"

# Columnas que tu base espera (ajusta si cambian)
expected_columns = ["camion", "nombre", "latitud", "longitud", "litros", "dia", "telefono"]

# Cargar CSV
df = pd.read_csv(csv_file)

# Normalizar nombres de columnas para evitar errores por espacios
df.columns = [col.strip().lower().replace(" ", "_").replace("(jefe_de_hogar)", "nombre") for col in df.columns]

# Renombrar columnas del CSV para que coincidan con las de la base de datos
rename_map = {
    "id_camión": "camion",
    "conductor": "nombre",  # O ajusta según tu estructura
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

# Solo columnas relevantes
df = df[[col for col in expected_columns if col in df.columns]]

# Conexión a la base
conn = psycopg2.connect(DB_URL)
cur = conn.cursor()

for idx, row in df.iterrows():
    # Si toda la fila está vacía, ignorar
    if row.isnull().all():
        continue

    # Insertar, permitiendo valores nulos
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
print("¡Importación completada!")
