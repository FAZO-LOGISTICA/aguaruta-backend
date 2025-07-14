import pandas as pd
import requests
import json

# 1. Cargar archivo Excel
try:
    df = pd.read_excel("bbdd.xlsx", sheet_name="BBDD ENTREGAS")
except FileNotFoundError:
    print("⚠️ El archivo 'bbdd.xlsx' no se encuentra en esta carpeta.")
    exit()

# 2. Limpiar datos: quitar filas sin datos clave
df = df.dropna(subset=["ID CAMIÓN", "NOMBRE", "LITROS DE ENTREGA"])

# 3. Renombrar columnas al formato del backend
df = df.rename(columns={
    "ID CAMIÓN": "camion_id",
    "PATENTE": "patente",
    "CONDUCTOR": "conductor",
    "DIA": "dia",
    "NOMBRE": "jefe_hogar",
    "SECTOR": "sector",
    "LITROS DE ENTREGA": "litros"
})

# 4. Convertir litros a float válido y eliminar inválidos
df["litros"] = pd.to_numeric(df["litros"], errors="coerce")
df = df.dropna(subset=["litros"])

# 5. Reemplazar NaN restantes por string vacío
df = df.fillna("")

# 6. Convertir a JSON
entregas = df[["camion_id", "patente", "conductor", "dia", "jefe_hogar", "sector", "litros"]].to_dict(orient="records")

# 7. Enviar al backend
url = "http://localhost:8000/api/entregas/lote/"
