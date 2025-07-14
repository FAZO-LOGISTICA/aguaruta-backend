import sqlite3
import pandas as pd

# Cargar los teléfonos desde el archivo Excel
df = pd.read_excel("NUMEROS DE TELEFONOS RECUERRENTES.xlsx")
df.columns = [col.strip().lower() for col in df.columns]
telefonos_dict = {
    str(fila["jefe de hogar"]).strip().upper(): str(fila["número de telefonos"]).strip()
    for _, fila in df.iterrows()
}

# Conectar a la base de datos
conn = sqlite3.connect("entregas.db")
cursor = conn.cursor()

# Buscar los nombres únicos en la base
cursor.execute("SELECT DISTINCT jefe_hogar FROM entregas")
nombres_bd = [fila[0].strip().upper() for fila in cursor.fetchall()]

# Verificar cuáles nombres no tienen teléfono
print("\nNombres sin teléfono:")
for nombre in nombres_bd:
    if nombre not in telefonos_dict:
        print("-", nombre)

conn.close()
