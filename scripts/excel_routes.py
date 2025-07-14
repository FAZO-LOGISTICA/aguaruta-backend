from fastapi import APIRouter
import pandas as pd

router = APIRouter()

@router.get("/rutas-activas")
def obtener_rutas_activas():
    try:
        df = pd.read_excel("base de datos.xlsx")  # Asegúrate de que esté en la raíz del backend
        return df.to_dict(orient="records")
    except Exception as e:
        return {"error": str(e)}
