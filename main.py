# main.py
# 🚀 Backend AguaRuta estable con importación de Excel

import os
import uuid
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import psycopg2
from psycopg2.pool import SimpleConnectionPool

import pandas as pd

# =============================================================================
# CONFIG
# =============================================================================
APP_NAME = "AguaRuta Backend"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
FOTOS_DIR = BASE_DIR / "fotos" / "evidencias"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("aguaruta")

DB_URL = os.getenv("DATABASE_URL") or os.getenv("DB_URL") or os.getenv("POSTGRES_URL")
if DB_URL and "sslmode=" not in DB_URL:
    DB_URL += ("&" if "?" in DB_URL else "?") + "sslmode=require"

POOL_MIN = int(os.getenv("PG_POOL_MIN", "1"))
POOL_MAX = int(os.getenv("PG_POOL_MAX", "3"))

pool: Optional[SimpleConnectionPool] = None


def init_pool():
    global pool
    if DB_URL and pool is None:
        log.info(f"Inicializando pool (min={POOL_MIN}, max={POOL_MAX})…")
        pool = SimpleConnectionPool(POOL_MIN, POOL_MAX, DB_URL)
        log.info("Pool listo.")


def get_conn():
    if pool is None:
        init_pool()
    if pool is None:
        raise RuntimeError("No hay pool de conexiones DB.")
    return pool.getconn()


def put_conn(conn):
    if pool and conn:
        pool.putconn(conn)


# =============================================================================
# APP + CORS
# =============================================================================
app = FastAPI(title=APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # abierto para Netlify
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.options("/{rest_of_path:path}")
def preflight_any(rest_of_path: str):
    return Response(status_code=204)

FOTOS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/fotos", StaticFiles(directory=str(BASE_DIR / "fotos")), name="fotos")


# =============================================================================
# SALUD
# =============================================================================
@app.get("/", response_class=PlainTextResponse)
def root():
    return f"{APP_NAME} OK"

@app.get("/health")
def health():
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            cur.fetchone()
        put_conn(conn)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# =============================================================================
# TABLA RUTAS ACTIVAS
# =============================================================================
def ensure_table_rutas_activas(conn):
    sql = """
    CREATE TABLE IF NOT EXISTS public.rutas_activas (
        id SERIAL PRIMARY KEY,
        camion TEXT,
        nombre TEXT,
        dia TEXT,
        litros INTEGER,
        telefono TEXT,
        latitud DOUBLE PRECISION,
        longitud DOUBLE PRECISION,
        activa BOOLEAN DEFAULT TRUE
    );
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


@app.get("/rutas-activas")
def rutas_activas():
    conn = get_conn()
    try:
        ensure_table_rutas_activas(conn)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, camion, nombre, dia, litros, telefono, latitud, longitud, activa
                FROM public.rutas_activas
                ORDER BY camion, nombre;
            """)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        put_conn(conn)


class RutaActivaUpdate(BaseModel):
    camion: Optional[str] = None
    nombre: Optional[str] = None
    dia: Optional[str] = None
    litros: Optional[int] = None
    telefono: Optional[str] = None
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    activa: Optional[bool] = None


@app.put("/rutas-activas/{rid}")
def update_ruta_activa(rid: int, body: RutaActivaUpdate):
    conn = get_conn()
    try:
        updates = {k: v for k, v in body.dict().items() if v is not None}
        if not updates:
            return {"ok": True, "updated": 0, "id": rid}

        sets = [f"{col} = %s" for col in updates.keys()]
        vals = list(updates.values())
        vals.append(rid)

        sql = f"UPDATE public.rutas_activas SET {', '.join(sets)} WHERE id = %s;"
        with conn.cursor() as cur:
            cur.execute(sql, tuple(vals))
            updated = cur.rowcount
        conn.commit()
        if updated == 0:
            raise HTTPException(status_code=404, detail="No existe ese id")
        return {"ok": True, "updated": updated, "id": rid}
    finally:
        put_conn(conn)


@app.delete("/rutas-activas/{rid}")
def delete_ruta_activa(rid: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.rutas_activas WHERE id = %s;", (rid,))
            deleted = cur.rowcount
        conn.commit()
        if deleted == 0:
            raise HTTPException(status_code=404, detail="No existe ese id")
        return {"ok": True, "deleted": deleted, "id": rid}
    finally:
        put_conn(conn)


# =============================================================================
# IMPORTAR RUTAS DESDE EXCEL
# =============================================================================
@app.post("/importar-rutas")
def importar_rutas():
    file_path = DATA_DIR / "rutas_activas.xlsx"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="No se encontró rutas_activas.xlsx en /data")

    df = pd.read_excel(file_path)
    conn = get_conn()
    try:
        ensure_table_rutas_activas(conn)
        inserted = 0
        for _, row in df.iterrows():
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO public.rutas_activas
                    (camion, nombre, dia, litros, telefono, latitud, longitud, activa)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,TRUE)
                """, (
                    row.get("camion"),
                    row.get("nombre"),
                    row.get("dia"),
                    int(row.get("litros") or 0),
                    row.get("telefono"),
                    float(row.get("latitud") or 0),
                    float(row.get("longitud") or 0),
                ))
            inserted += 1
        conn.commit()
        return {"ok": True, "inserted": inserted}
    finally:
        put_conn(conn)


# =============================================================================
# 🚨 Aquí seguirían los endpoints de entregas-app, registrar-entregas, entregas-todas
# (idénticos a como los tenías antes, no los borré)
# =============================================================================
