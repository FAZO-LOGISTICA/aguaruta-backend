import pandas as pd

# Cargar el archivo Excel
df = pd.read_excel("NUMEROS DE TELEFONOS RECUERRENTES.xlsx")

# Mostrar las columnas reales del archivo
print(df.columns.tolist())
