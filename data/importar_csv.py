import pandas as pd
import psycopg2

# Configura tu URL de base de datos
DB_URL = "postgresql://aguaruta_db_user:u1JUg0dcbEYzzzoF8N4lsbdZ6c2ZXyPb@dpg-d25b5mripnbc73dpod0g-a.oregon-postgres.render.com/aguaruta_db"

df = pd.read_csv("base_datos_todos_con_coordenadas.csv")
conn = psycopg2.connect(DB_URL)
cur = conn.cursor()

for idx, row in df.iterrows():
    try:
        cur.execute("""
            INSERT INTO ruta_activa (camion, nombre, dia, litros, telefono, latitud, longitud)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING;
        """, (
            str(row.get('id camión', '')),
            str(row.get('nombre (jefe de hogar)', '')),
            str(row.get('dia', '')),
            int(row.get('litros de entrega', 0) if not pd.isnull(row.get('litros de entrega', 0)) else 0),
            str(row.get('telefono', '')) if not pd.isnull(row.get('telefono', '')) else '',
            float(row.get('latitud', 0)) if not pd.isnull(row.get('latitud', 0)) else None,
            float(row.get('longitud', 0)) if not pd.isnull(row.get('longitud', 0)) else None,
        ))
    except Exception as e:
        print(f"Error en fila {idx}: {e}")

conn.commit()
cur.close()
conn.close()
print("¡Listo! Datos subidos.")
