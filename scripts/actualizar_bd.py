import sqlite3

conn = sqlite3.connect("entregas.db")
cursor = conn.cursor()

# Intentar agregar la columna telefono solo si no existe
try:
    cursor.execute("ALTER TABLE entregas ADD COLUMN telefono TEXT;")
    print("Columna 'telefono' agregada con éxito.")
except Exception as e:
    print("Error (probablemente la columna ya existe):", e)

conn.commit()
conn.close()
