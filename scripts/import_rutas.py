# scripts/import_rutas.py
import os
import psycopg2
import pandas as pd

DB_URL = os.getenv("DATABASE_URL") or os.getenv("DB_URL")

def importar_rutas():
    # Ruta del CSV dentro del proyecto
    csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "rutas_activas.csv")
    df = pd.read_csv(csv_path)

    conn = psycopg2.connect(dsn=DB_URL)
    cur = conn.cursor()

    # Vacía la tabla antes de cargar (evita duplicados)
    cur.execute("TRUNCATE TABLE rutas_activas RESTART IDENTITY;")

    for _, row in df.iterrows():
        cur.execute("""
            INSERT INTO rutas_activas (camion, nombre, dia, litros, telefono, latitud, longitud)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            row['camion'],
            row['nombre'],
            row['dia'],
            int(row['litros']) if not pd.isna(row['litros']) else None,
            row['telefono'],
            float(row['latitud']) if not pd.isna(row['latitud']) else None,
            float(row['longitud']) if not pd.isna(row['longitud']) else None,
        ))

    conn.commit()
    cur.close()
    conn.close()
    print("✅ Rutas activas cargadas con éxito.")

if __name__ == "__main__":
    importar_rutas()
