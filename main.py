from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
from typing import Optional
import os

app = FastAPI()

# CORS para conexión desde app móvil o frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Puedes restringir en producción
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ruta correcta al archivo oficial de AguaRuta
DATA_FILE = os.path.join("data", "base_datos_todos_con_coordenadas.xlsx")

@app.get("/")
def root():
    return {"message": "API AguaRuta funcionando correctamente"}

# ✅ Rutas filtradas por conductor y día (ajustado a columnas reales)
@app.get("/ruta-asignada")
def get_ruta_asignada(conductor: str = Query(...), dia: str = Query(...)):
    try:
        df = pd.read_excel(DATA_FILE)

        # Normaliza nombres de columnas a minúsculas sin espacios
        df.columns = df.columns.str.strip().str.lower()

        df['conductor'] = df['conductor'].astype(str).str.strip().str.lower()
        df['dia_asignado'] = df['dia_asignado'].astype(str).str.strip().str.lower()

        rutas = df[
            (df['conductor'] == conductor.strip().lower()) &
            (df['dia_asignado'] == dia.strip().lower())
        ]

        return rutas.to_dict(orient="records")
    except Exception as e:
        return {"error": str(e)}

# ✅ Todas las rutas (sin filtro, útil para mostrar por camión, mapa, etc.)
@app.get("/rutas-por-camion")
def get_rutas_por_camion():
    try:
        df = pd.read_excel(DATA_FILE)
        df.columns = df.columns.str.strip().str.lower()
        return df.to_dict(orient="records")
    except Exception as e:
        return {"error": str(e)}
