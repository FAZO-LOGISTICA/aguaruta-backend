from fastapi import APIRouter, HTTPException, Query
from pathlib import Path
import json

router = APIRouter(prefix="", tags=["redistribucion-legacy"])

def data_path(relative: str) -> Path:
    backend_dir = Path(__file__).resolve().parents[1]  # .../backend
    return (backend_dir / relative).resolve()

DATA_FILE = data_path("data/RutasMapaFinal_con_telefono.json")

def _normalize_row(r: dict) -> dict:
    return {
        "camion": r.get("camion") or r.get("CAMION") or r.get("id_camion"),
        "nombre": r.get("nombre") or r.get("NOMBRE"),
        "latitud": r.get("latitud") or r.get("LATITUD"),
        "longitud": r.get("longitud") or r.get("LONGITUD"),
        "litros": r.get("litros") or r.get("LITROS_DE_ENTREGA") or r.get("litros_entrega"),
        "dia": r.get("dia") or r.get("DIA") or r.get("dia_asignado"),
        "telefono": r.get("telefono") or r.get("TELEFONO") or r.get("fono"),
    }

@router.get("/redistribucion")
def get_redistribucion(camion: str | None = Query(default=None),
                       dia: str | None = Query(default=None)):
    if not DATA_FILE.exists():
        raise HTTPException(status_code=404, detail=f"Archivo no encontrado: {DATA_FILE.name}")

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    rows = [_normalize_row(x) for x in raw if isinstance(x, dict)]

    if camion:
        rows = [r for r in rows if (r.get("camion") or "").upper() == camion.upper()]
    if dia:
        rows = [r for r in rows if (r.get("dia") or "").upper() == dia.upper()]

    return rows

@router.get("/redistribucion/health")
def health():
    return {"ok": True}
