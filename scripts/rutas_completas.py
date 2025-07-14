from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List

router = APIRouter()

class PuntoRuta(BaseModel):
    id: int
    nombre: str
    litros: int
    camion: str
    dia: str
    lat: float
    lon: float

@router.get("/rutas_completas", response_model=List[PuntoRuta])
def obtener_rutas():
    try:
        rutas = [
            {
                "id": 1,
                "nombre": "Juan Pérez",
                "litros": 500,
                "camion": "A1",
                "dia": "Lunes",
                "lat": -33.045,
                "lon": -71.619
            },
            {
                "id": 2,
                "nombre": "Ana Rojas",
                "litros": 750,
                "camion": "A2",
                "dia": "Martes",
                "lat": -33.048,
                "lon": -71.615
            }
        ]
        return rutas
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
