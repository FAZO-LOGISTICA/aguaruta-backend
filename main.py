# backend/main.py
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from typing import Dict, List, Optional
from contextlib import contextmanager
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import execute_values
import psycopg2
import pandas as pd
from pathlib import Path
import unicodedata
import io
import os
import json
from datetime import datetime

# -----------------------------------------------------------------------------
# Configuración inicial
# -----------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL no está configurada en variables de entorno")

# Render requiere SSL
pool = SimpleConnectionPool(1, 20, dsn=DATABASE_URL, sslmode="require")

app = FastAPI(title="AguaRuta API", version="2.1")

# CORS (Netlify + local dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://aguaruta.netlify.app",
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Helpers DB
# -----------------------------------------------------------------------------
@contextmanager
def get_conn_cursor():
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        yield conn, cur
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        pool.putconn(conn)

def _rows_to_dicts(cur, rows):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]

# -----------------------------------------------------------------------------
# Helpers de normalización / redistribución (solo lectura para vistas)
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_FILE_REDIS = DATA_DIR / "RutasMapaFinal_con_telefono.json"
CAMIONES_VALIDOS = {"A1", "A2", "A3", "A4", "A5", "M1", "M2"}  # M3 se preserva, no se reasigna

def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn")

def _norm_key(k: str) -> str:
    return _strip_accents(k).lower().replace(" ", "_")

def _norm_dict(d: dict) -> dict:
    return {_norm_key(k): v for k, v in d.items()}

def _pick(dn: dict, *candidatos, default=None):
    for k in candidatos:
        if k in dn and dn[k] not in (None, "", "nan"):
            return dn[k]
    return default

def _parse_float(x):
    if x is None:
        return None
    try:
        s = str(x).strip().replace(",", ".")
        return float(s)
    except Exception:
        return None

def _parse_int_pos(x):
    try:
        f = _parse_float(x)
        return int(f) if f is not None and f > 0 else None
    except Exception:
        return None

_DIAS = {
    "LUN": "LUNES", "LUNES": "LUNES",
    "MAR": "MARTES", "MARTES": "MARTES",
    "MIE": "MIERCOLES", "MIERCOLES": "MIERCOLES", "MIÉRCOLES": "MIERCOLES",
    "JUE": "JUEVES", "JUEVES": "JUEVES",
    "VIE": "VIERNES", "VIERNES": "VIERNES"
}

def _norm_dia(d) -> Optional[str]:
    if not d:
        return None
    t = _strip_accents(str(d)).strip().upper()
    if t in _DIAS:
        return _DIAS[t]
    pref = t[:3]
    return _DIAS.get(pref, None)

def _valid_lat_lon(lat, lon) -> bool:
    if lat is None or lon is None:
        return True  # opcional
    try:
        return (-90.0 <= float(lat) <= 90.0) and (-180.0 <= float(lon) <= 180.0)
    except Exception:
        return False

# -----------------------------------------------------------------------------
# Salud
# -----------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

# -----------------------------------------------------------------------------
# Compatibilidad: /redistribucion (para front de mapas) -> lee JSON en backend/data
# Si no existe el archivo, devuelve [] (no 404) para no ensuciar el front.
# -----------------------------------------------------------------------------
def _norm_row_json(r: dict) -> dict:
    return {
        "camion": r.get("camion") or r.get("CAMION") or r.get("id_camion"),
        "nombre": r.get("nombre") or r.get("NOMBRE"),
        "latitud": r.get("latitud") or r.get("LATITUD"),
        "longitud": r.get("longitud") or r.get("LONGITUD"),
        "litros": r.get("litros") or r.get("LITROS_DE_ENTREGA") or r.get("litros_entrega"),
        "dia": r.get("dia") or r.get("DIA") or r.get("dia_asignado"),
        "telefono": r.get("telefono") or r.get("TELEFONO") or r.get("fono"),
    }

@app.get("/redistribucion")
def redistribucion_compat(camion: Optional[str] = None, dia: Optional[str] = None):
    if not DATA_FILE_REDIS.exists():
        return []
    try:
        raw = json.loads(DATA_FILE_REDIS.read_text(encoding="utf-8")) or []
    except Exception:
        return []
    rows = [_norm_row_json(x) for x in raw if isinstance(x, dict)]
    if camion:
        rows = [r for r in rows if (r.get("camion") or "").upper() == camion.upper()]
    if dia:
        rows = [r for r in rows if (r.get("dia") or "").upper() == dia.upper()]
    return rows

@app.get("/redistribucion/health")
def redistribucion_health():
    return {"ok": True}

# -----------------------------------------------------------------------------
# RUTA ACTIVA — listar / editar
# -----------------------------------------------------------------------------
@app.get("/rutas-activas")
def obtener_rutas_activas():
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                SELECT id, camion, nombre, dia, litros, telefono, latitud, longitud
                FROM ruta_activa
                ORDER BY camion, dia, nombre
            """)
            filas = cur.fetchall()
            return _rows_to_dicts(cur, filas)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/rutas-activas/{id}")
def editar_ruta_activa(id: int, data: Dict):
    """
    Body JSON con las claves a actualizar. Ej:
    { "camion":"A5", "dia":"Martes", "latitud":-33.1, "longitud":-71.5 }
    """
    try:
        if not data:
            raise HTTPException(status_code=400, detail="Body vacío")
        with get_conn_cursor() as (_, cur):
            sets = ", ".join([f"{k} = %s" for k in data.keys()])
            values = list(data.values()) + [id]
            cur.execute(f"UPDATE ruta_activa SET {sets} WHERE id = %s", values)
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Registro no encontrado")
        return {"mensaje": "✅ Registro actualizado correctamente", "id": id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# COMPAT — el front viejo llama PUT /editar-ruta (sin {id})
# -----------------------------------------------------------------------------
@app.put("/editar-ruta")
def editar_ruta_legacy(payload: Dict):
    try:
        rid = payload.get("id") or payload.get("ID") or payload.get("Id")
        if not rid:
            raise HTTPException(status_code=400, detail="Falta 'id' en el payload")

        allowed = {"camion","nombre","dia","litros","telefono","latitud","longitud"}
        data = {k.lower(): v for k, v in payload.items() if k.lower() in allowed}

        def fixnum(x, kind="float"):
            if x is None:
                return None
            s = str(x).strip().replace(",", ".")
            try:
                return int(float(s)) if kind == "int" else float(s)
            except Exception:
                return None

        if "litros"   in data: data["litros"]   = fixnum(data["litros"], "int")
        if "latitud"  in data: data["latitud"]  = fixnum(data["latitud"], "float")
        if "longitud" in data: data["longitud"] = fixnum(data["longitud"], "float")

        if not data:
            raise HTTPException(status_code=400, detail="Sin campos para actualizar")

        with get_conn_cursor() as (_, cur):
            sets = ", ".join([f"{k} = %s" for k in data.keys()])
            values = list(data.values()) + [rid]
            cur.execute(f"UPDATE ruta_activa SET {sets} WHERE id = %s", values)
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Registro no encontrado")

        return {"ok": True, "id": rid, "mensaje": "✅ Registro actualizado"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/editar-ruta/{id}")
def editar_ruta_legacy_with_id(id: int, payload: Dict):
    payload = dict(payload or {})
    payload["id"] = id
    return editar_ruta_legacy(payload)

# -----------------------------------------------------------------------------
# IMPORTAR **RUTA ACTIVA** desde CSV/XLSX (reemplaza todo)
# -----------------------------------------------------------------------------
@app.post("/admin/importar-ruta-activa-file")
def importar_ruta_activa_file(
    archivo: UploadFile = File(...),
    truncate: bool = Form(True),
):
    """
    Sube un CSV/XLSX y carga DIRECTO en ruta_activa.
    Columnas aceptadas (en cualquier orden y con alias):
      camion | nombre | litros | latitud | longitud | dia (o dia_asignado) | telefono
    - Reemplaza comas decimales por punto.
    - Ignora vacíos (no rompe).
    - Si truncate=True (default), limpia ruta_activa antes de insertar.
    """
    try:
        content = archivo.file.read()
        nombre = archivo.filename.lower()

        # Leer archivo a DataFrame
        if nombre.endswith(".xlsx"):
            df = pd.read_excel(io.BytesIO(content), dtype=str)
        elif nombre.endswith(".csv"):
            try:
                df = pd.read_csv(io.BytesIO(content), dtype=str, encoding="utf-8")
            except Exception:
                df = pd.read_csv(io.BytesIO(content), dtype=str, encoding="latin-1")
        else:
            raise HTTPException(status_code=400, detail="Formato no soportado. Sube .csv o .xlsx")

        # Normalizar nombres de columnas
        df.columns = [c.strip().lower() for c in df.columns]

        def pick(df, col, *alts):
            for c in (col, *alts):
                if c in df.columns:
                    return df[c]
            return None

        out = pd.DataFrame({
            "camion":   pick(df, "camion"),
            "nombre":   pick(df, "nombre", "jefe_hogar"),
            "dia":      pick(df, "dia", "dia_asignado"),
            "litros":   pick(df, "litros", "litros_de_entrega"),
            "telefono": pick(df, "telefono", "phone"),
            "latitud":  pick(df, "latitud", "lat", "latitude"),
            "longitud": pick(df, "longitud", "lon", "lng", "longitude"),
        })

        # Limpiar/tipar
        for c in ["latitud", "longitud", "litros"]:
            out[c] = pd.to_numeric(out[c].astype(str).str.replace(",", ".", regex=False), errors="coerce")
        for c in ["camion", "nombre", "dia", "telefono"]:
            out[c] = out[c].astype(str).str.strip().replace({"nan": None, "None": None, "": None})
        out = out.where(pd.notnull(out), None)

        rows = list(out.itertuples(index=False, name=None))
        if not rows:
            raise HTTPException(status_code=400, detail="Archivo sin filas útiles")

        with get_conn_cursor() as (_, cur):
            if truncate:
                cur.execute("TRUNCATE TABLE ruta_activa;")
            execute_values(cur, """
                INSERT INTO ruta_activa (camion, nombre, dia, litros, telefono, latitud, longitud)
                VALUES %s
            """, rows)

        return {"ok": True, "insertados": len(rows)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# EXPORTAR RUTA ACTIVA a Excel
# -----------------------------------------------------------------------------
@app.get("/exportar-excel")
def exportar_excel():
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                SELECT camion, nombre, dia, litros, telefono, latitud, longitud
                FROM ruta_activa
                ORDER BY camion, dia, nombre
            """)
            filas = cur.fetchall()
            cols = [d[0] for d in cur.description]

        df = pd.DataFrame(filas, columns=cols)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Rutas Activas")
        output.seek(0)

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=rutas_activas.xlsx"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# REGISTRAR NUEVO PUNTO (Ruta Activa) — JSON body
# -----------------------------------------------------------------------------
@app.post("/registrar-nuevo-punto")
def registrar_nuevo_punto(data: Dict):
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                INSERT INTO ruta_activa (camion, nombre, dia, litros, telefono, latitud, longitud)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                data.get("camion"), data.get("nombre"), data.get("dia"),
                data.get("litros"), data.get("telefono"),
                data.get("latitud"), data.get("longitud")
            ))
            new_id = cur.fetchone()[0]
        return {"mensaje": "✅ Nuevo punto registrado en ruta activa", "id": new_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# ENTREGAS APP (historial y registro)
# -----------------------------------------------------------------------------
@app.get("/entregas-app")
def obtener_entregas_app():
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                SELECT nombre, camion, litros, estado, fecha, latitud, longitud, foto
                FROM entregas_app
                ORDER BY fecha DESC
            """)
            filas = cur.fetchall()
            return _rows_to_dicts(cur, filas)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/entregas-app")
def registrar_entrega_app(data: Dict):
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                INSERT INTO entregas_app (nombre, camion, litros, estado, fecha, latitud, longitud, foto)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                data.get("nombre"), data.get("camion"), data.get("litros"),
                data.get("estado"), data.get("fecha"),
                data.get("latitud"), data.get("longitud"), data.get("foto")
            ))
        return {"mensaje": "✅ Entrega registrada correctamente"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# NUEVA DISTRIBUCIÓN: DESHABILITADA
# -----------------------------------------------------------------------------
@app.post("/nueva-distribucion/aplicar")
def aplicar_nueva_redistribucion_deprecated(
    items: Optional[List[Dict]] = Body(default=None),
    preservar_m3: bool = True,
    truncate: bool = True,
    truncate_only_if_valid: bool = True,
    source: str = "file",
):
    # 410 Gone: funcionalidad retirada
    raise HTTPException(
        status_code=410,
        detail="Endpoint deshabilitado: 'Nueva Distribución' fue retirada del sistema."
    )

# -----------------------------------------------------------------------------
# Limpieza
# -----------------------------------------------------------------------------
@app.post("/limpiar-tablas")
def limpiar_tablas():
    """Limpia SOLO ruta_activa (ya no usamos redistribucion)."""
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("TRUNCATE TABLE ruta_activa;")
        return {"mensaje": "✅ Tabla ruta_activa limpiada"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/drop-redistribucion")
def drop_redistribucion():
    """Opcional: elimina la tabla redistribucion si existe (para simplificar el sistema)."""
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("DROP TABLE IF EXISTS redistribucion;")
        return {"mensaje": "✅ Tabla redistribucion eliminada (si existía)"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
