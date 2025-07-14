from fastapi import APIRouter
from pathlib import Path
import pandas as pd
import random

router = APIRouter()

@router.get("/puntos-nuevos")
def get_nuevos_puntos():
    filepath = Path("backend/data/Puntos_Nuevos_Consolidados.xlsx")

    if not filepath.exists():
        return {"error": "Archivo no encontrado."}

    try:
        df = pd.read_excel(filepath)
        df.columns = [col.strip().lower().replace(" ", "_") for col in df.columns]

        columnas_necesarias = ["nombre", "telefono", "litros", "latitud", "longitud"]
        df = df[[col for col in columnas_necesarias if col in df.columns]]

        return df.to_dict(orient="records")

    except Exception as e:
        return {"error": str(e)}

@router.post("/redistribuir")
def redistribuir_puntos():
    filepath = Path("backend/data/Puntos_Nuevos_Consolidados.xlsx")

    if not filepath.exists():
        return {"error": "Archivo no encontrado."}

    try:
        df = pd.read_excel(filepath)
        df.columns = [col.strip().lower().replace(" ", "_") for col in df.columns]

        camiones_disponibles = ["A1", "A2", "A3", "A4", "A5", "M1", "M2"]
        asignaciones = []

        for _, row in df.iterrows():
            asignado = random.choice(camiones_disponibles)
            nuevo = row.to_dict()
            nuevo["camion_asignado"] = asignado
            asignaciones.append(nuevo)

        return asignaciones

    except Exception as e:
        return {"error": str(e)}
