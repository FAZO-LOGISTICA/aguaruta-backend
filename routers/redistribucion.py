# routers/redistribucion.py
from fastapi import APIRouter
from pathlib import Path
import pandas as pd
import random

# Este prefix evita colisiones con /redistribucion (DB) del main.py
router = APIRouter(prefix="/nueva-distribucion", tags=["nueva-distribucion"])

def data_path(relative: str) -> Path:
    """
    Resuelve rutas en local y en Render.
    Asumiendo estructura:
      backend/
        data/Puntos_Nuevos_Consolidados.xlsx
        routers/redistribucion.py (este archivo)
    """
    backend_dir = Path(__file__).resolve().parents[1]  # .../backend
    return (backend_dir / relative).resolve()

@router.get("/puntos-nuevos")
def get_nuevos_puntos():
    filepath = data_path("data/Puntos_Nuevos_Consolidados.xlsx")
    if not filepath.exists():
        return {"error": f"Archivo no encontrado: {filepath}"}

    try:
        df = pd.read_excel(filepath)
        # normaliza cabeceras
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

        # columnas mínimas
        columnas_necesarias = ["nombre", "telefono", "litros", "latitud", "longitud"]
        cols_presentes = [c for c in columnas_necesarias if c in df.columns]
        if not cols_presentes:
            return {"error": f"No se encontraron columnas necesarias en {filepath.name}"}

        return df[cols_presentes].to_dict(orient="records")
    except Exception as e:
        return {"error": str(e)}

@router.post("/redistribuir")
def redistribuir_puntos():
    filepath = data_path("data/Puntos_Nuevos_Consolidados.xlsx")
    if not filepath.exists():
        return {"error": f"Archivo no encontrado: {filepath}"}

    try:
        df = pd.read_excel(filepath)
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

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
