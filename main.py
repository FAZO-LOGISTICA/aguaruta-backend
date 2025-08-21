from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from typing import Dict
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import execute_values
from contextlib import contextmanager
import pandas as pd
import io
import os
from datetime import datetime
from typing import List, Dict, Optional
from fastapi import Body
from pathlib import Path
import json
import unicodedata

# === Routers ===
# Asegúrate de tener un __init__.py vacío dentro de backend/routers/
from routers import redistribucion_legacy      # -> expone /redistribucion (para el front actual)
from routers import redistribucion as nueva_redistribucion  # -> tus endpoints /nueva-distribucion/...

# -----------------------------------------------------------------------------
# Configuración inicial
# -----------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL no está configurada en variables de entorno")

# Render requiere SSL
pool = SimpleConnectionPool(
    1, 20, dsn=DATABASE_URL, sslmode="require"
)

app = FastAPI(title="AguaRuta API", version="2.0")

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

# === Montar routers ===
app.include_router(redistribucion_legacy.router)       # /redistribucion (+ /redistribucion/health)
app.include_router(nueva_redistribucion.router)        # /nueva-distribucion/*

# -----------------------------------------------------------------------------
# Helpers
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
# Salud
# -----------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

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
    """
    try:
        content = archivo.file.read()
        nombre = archivo.filename.lower()

        if nombre.endswith(".xlsx"):
            df = pd.read_excel(io.BytesIO(content), dtype=str)
        elif nombre.endswith(".csv"):
            try:
                df = pd.read_csv(io.BytesIO(content), dtype=str, encoding="utf-8")
            except Exception:
                df = pd.read_csv(io.BytesIO(content), dtype=str, encoding="latin-1")
        else:
            raise HTTPException(status_code=400, detail="Formato no soportado. Sube .csv o .xlsx")

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
