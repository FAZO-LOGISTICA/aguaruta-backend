# rutas_json.py

from fastapi import APIRouter, HTTPException
import json
import os

router = APIRouter()

RUTA_ARCHIVO = "rutas_activas.json"  # asegúrate que esté en la raíz del backend

@router.get("/rutas-desde-excel")
def obtener_rutas_desde_excel():
    if not os.path.exists(RUTA_ARCHIVO):
        raise HTTPException(status_code=404, detail="Archivo de rutas no encontrado")
    
    with open(RUTA_ARCHIVO, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data
