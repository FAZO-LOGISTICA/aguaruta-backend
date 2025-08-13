# backend/rutas_activas.py
from fastapi import APIRouter, HTTPException
from pathlib import Path
import pandas as pd
import unicodedata

# Evita colisión con /rutas-activas (DB) del main.py
router = APIRouter(prefix="/rutas-activas-excel", tags=["rutas-activas-excel"])

def data_path(relative: str) -> Path:
    backend_dir = Path(__file__).resolve().parent  # .../backend
    return (backend_dir / relative).resolve()

RUTA_BASE = data_path("data/base_datos_todos_con_coordenadas.xlsx")
CAMIONES_VALIDOS = ['A1', 'A2', 'A3', 'A4', 'A5', 'M1', 'M2']

def norm(s: str) -> str:
    s = s.lower().strip().replace(" ", "_")
    s = "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")
    return s

def find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cand_norm = [norm(c) for c in candidates]
    mapping = {norm(c): c for c in df.columns}
    for c in cand_norm:
        if c in mapping:
            return mapping[c]
    return None

@router.get("")
def obtener_rutas_activas_excel():
    try:
        if not RUTA_BASE.exists():
            raise HTTPException(status_code=404, detail=f"No existe archivo: {RUTA_BASE}")
        df = pd.read_excel(RUTA_BASE)
        df = df.fillna("")
        return df.to_dict(orient="records")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/puntos")
def obtener_puntos_excel():
    try:
        if not RUTA_BASE.exists():
            raise HTTPException(status_code=404, detail=f"No existe archivo: {RUTA_BASE}")
        df = pd.read_excel(RUTA_BASE)

        nombre_col = find_col(df, ["nombre", "nombre_(jefe_de_hogar)", "nombre_jefe_de_hogar"])
        litros_col = find_col(df, ["litros_de_entrega", "litros"])
        lat_col    = find_col(df, ["latitud"])
        lon_col    = find_col(df, ["longitud", "long"])

        if not all([lat_col, lon_col, nombre_col, litros_col]):
            raise HTTPException(status_code=400, detail="Faltan columnas necesarias (latitud/longitud/nombre/litros)")

        sub = df[[lat_col, lon_col, nombre_col, litros_col]].rename(columns={
            nombre_col: "nombre",
            litros_col: "litros",
            lat_col:    "latitud",
            lon_col:    "longitud",
        })
        sub = sub.dropna(subset=["latitud", "longitud", "nombre", "litros"])
        return sub.to_dict(orient="records")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/registrar-nuevo-punto")
def registrar_nuevo_punto(punto: dict):
    try:
        if not RUTA_BASE.exists():
            raise HTTPException(status_code=404, detail=f"No existe archivo: {RUTA_BASE}")

        df = pd.read_excel(RUTA_BASE)
        df = df.fillna("")

        id_camion_col = find_col(df, ["id_camión", "id_camion", "id camion"])
        litros_col    = find_col(df, ["litros_de_entrega", "litros"])
        nombre_col    = find_col(df, ["nombre_(jefe_de_hogar)", "nombre"])
        dia_col       = find_col(df, ["dia", "día"])
        tel_col       = find_col(df, ["telefono", "teléfono", "fono"])
        lat_col       = find_col(df, ["latitud"])
        lon_col       = find_col(df, ["longitud"])
        sector_col    = find_col(df, ["sector"])

        # crea columnas si faltan
        created_cols = []
        if id_camion_col is None:
            id_camion_col = "id_camion"
            df[id_camion_col] = ""
            created_cols.append(id_camion_col)
        if litros_col is None:
            litros_col = "litros"
            df[litros_col] = 0
            created_cols.append(litros_col)

        # resumen por camión (si hay datos previos)
        resumen = df.groupby(id_camion_col)[litros_col].sum(min_count=1).to_dict() if litros_col in df.columns else {}
        asignar_a = min(CAMIONES_VALIDOS, key=lambda c: resumen.get(c, 0) if resumen else 0)

        # día tentativo (puedes mejorar la lógica luego)
        dia_val = "LUNES"

        nuevo = {
            id_camion_col: asignar_a,
            "patente": "",
            "conductor": "",
            (dia_col or "dia"): dia_val,
            (nombre_col or "nombre"): punto["nombre"],
            (tel_col or "telefono"): punto.get("telefono", ""),
            (sector_col or "sector"): punto.get("sector", ""),
            (litros_col or "litros"): punto["litros"],
            (lat_col or "latitud"): punto["latitud"],
            (lon_col or "longitud"): punto["longitud"],
        }

        df_nuevo = pd.concat([df, pd.DataFrame([nuevo])], ignore_index=True)
        df_nuevo.to_excel(RUTA_BASE, index=False)

        msg_extra = f" (creadas columnas: {', '.join(created_cols)})" if created_cols else ""
        return {"mensaje": f"✅ Punto registrado{msg_extra}", "camion_asignado": asignar_a}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
