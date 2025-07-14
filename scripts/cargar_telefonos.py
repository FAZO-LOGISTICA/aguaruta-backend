import pandas as pd
import sqlite3

# Leer el Excel
df = pd.read_excel("NUMEROS DE TELEFONOS RECUERRENTES.xlsx")

# Conectar a la base de datos
conn = sqlite3.connect("entregas.db")
cursor = conn.cursor()

# Añadir columna "telefono" si no existe
cursor.execute("PRAGMA table_info(entregas)")
columnas = [col[1] for col in cursor.fetchall()]
if "telefono" not in columnas:
    cursor.execute("ALTER TABLE entregas ADD COLUMN telefono TEXT")

# Insertar o actualizar los números
for _, fila in df.iterrows():
    nombre = fila["jefe de hogar"].strip().upper()
    telefono = str(fila["número de telefonos"]).strip()
    cursor.execute("""
        UPDATE entregas SET telefono = ?
        WHERE UPPER(jefe_hogar) = ?
    """, (telefono, nombre))

conn.commit()
conn.close()

print("Teléfonos actualizados correctamente.")
