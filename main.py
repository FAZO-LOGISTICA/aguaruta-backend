# 🚀 Forzar redeploy Render (CORS abierto)
# main.py
# Backend FastAPI – AguaRuta (contrato estable)
import os
import uuid
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import psycopg2
from psycopg2.pool import SimpleConnectionPool

# =============================================================================
# CONFIG
# =============================================================================
APP_NAME = "AguaRuta Backend"
BASE_DIR = Path(__file__).resolve().parent
FOTOS_DIR = BASE_DIR / "fotos" / "evidencias"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("aguaruta")

# ---- DB URL + Pool con SSL ---------------------------------------------------
DB_URL = os.getenv("DATABASE_URL") or os.getenv("DB_URL") or os.getenv("POSTGRES_URL")
if not DB_URL:
    log.warning("⚠️ Falta DATABASE_URL/DB_URL/POSTGRES_URL en variables de entorno.")
else:
    if "sslmode=" not in DB_URL:
        DB_URL += ("&" if "?" in DB_URL else "?") + "sslmode=require"

POOL_MIN = int(os.getenv("PG_POOL_MIN", "1"))
POOL_MAX = int(os.getenv("PG_POOL_MAX", "3"))

pool: Optional[SimpleConnectionPool] = None

def init_pool() -> None:
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

def put_conn(conn) -> None:
    if pool and conn:
        pool.putconn(conn)

# =============================================================================
# APP + CORS
# =============================================================================
app = FastAPI(title=APP_NAME)

# 🚨 FIX: CORS abierto para pruebas (incluye Netlify)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # 🔥 abre todo (frontend Netlify incluido)
    allow_credentials=True,
    allow_methods=["*"],       # GET, POST, PUT, DELETE, OPTIONS
    allow_headers=["*"],       # acepta todos los headers
)

# Preflight global
@app.options("/{rest_of_path:path}")
def preflight_any(rest_of_path: str):
    return Response(status_code=204)

# Estáticos para evidencias
FOTOS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/fotos", StaticFiles(directory=str(BASE_DIR / "fotos")), name="fotos")

# =============================================================================
# SALUD
# =============================================================================
@app.get("/", response_class=PlainTextResponse)
def root():
    return f"{APP_NAME} OK"

@app.head("/", include_in_schema=False)
def head_root():
    return PlainTextResponse("")

@app.get("/health")
def health():
    try:
        if DB_URL:
            conn = get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                    cur.fetchone()
            finally:
                put_conn(conn)
        return {"ok": True}
    except Exception as e:
        log.exception("Health check failed")
        return {"ok": False, "error": str(e)}

# =============================================================================
# /url.txt  (descubrimiento para app móvil)
# =============================================================================
@app.get("/url.txt", response_class=PlainTextResponse)
def url_txt():
    fp = BASE_DIR / "url.txt"
    if not fp.exists():
        raise HTTPException(status_code=404, detail="url.txt no existe")
    return fp.read_text(encoding="utf-8").strip()

# =============================================================================
# ENDPOINTS NEGOCIO – RUTAS ACTIVAS
# =============================================================================
@app.get("/rutas-activas")
def rutas_activas():
    """Lee DIRECTO from public.ruta_activa."""
    if pool is None:
        raise HTTPException(status_code=503, detail="DB no configurada")
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    id,
                    camion,
                    nombre,
                    dia,
                    litros,
                    telefono,
                    latitud,
                    longitud
                FROM public.ruta_activa
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

@app.put("/rutas-activas/{rid}")
def update_ruta_activa(rid: int, body: RutaActivaUpdate):
    if pool is None:
        raise HTTPException(status_code=503, detail="DB no configurada")

    updates: Dict[str, Any] = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        return {"ok": True, "updated": 0, "id": rid}

    conn = get_conn()
    try:
        sets = []
        vals = []
        for col, val in updates.items():
            sets.append(f"{col} = %s")
            vals.append(val)
        vals.append(rid)
        sql = f"UPDATE public.ruta_activa SET {', '.join(sets)} WHERE id = %s;"
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
    if pool is None:
        raise HTTPException(status_code=503, detail="DB no configurada")
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.ruta_activa WHERE id = %s;", (rid,))
            deleted = cur.rowcount
        conn.commit()
        if deleted == 0:
            raise HTTPException(status_code=404, detail="No existe ese id")
        return {"ok": True, "deleted": deleted, "id": rid}
    finally:
        put_conn(conn)

# =============================================================================
# ENTREGAS APP (fotos de respaldo/no entrega, desde móviles)
# =============================================================================
def ensure_table_entregas_app(conn) -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS public.entregas_app (
        id UUID PRIMARY KEY,
        nombre TEXT,
        camion TEXT,
        litros INTEGER,
        estado INTEGER,
        fecha TIMESTAMP,
        lat DOUBLE PRECISION,
        lon DOUBLE PRECISION,
        foto_ruta TEXT
    );
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()

@app.post("/entregas-app")
async def entregas_app(
    nombre: str = Form(...),
    camion: str = Form(...),
    litros: str = Form(...),
    estado: int = Form(...),
    fecha: str = Form(...),
    lat: Optional[float] = Form(None),
    lon: Optional[float] = Form(None),
    foto: Optional[UploadFile] = File(None),
):
    if pool is None:
        raise HTTPException(status_code=503, detail="DB no configurada")

    try:
        litros_int = int(float(litros))
    except Exception:
        litros_int = None

    try:
        if len(fecha) <= 10:
            dt = datetime.strptime(fecha, "%Y-%m-%d")
        else:
            dt = datetime.fromisoformat(fecha.replace("Z", "+00:00"))
    except Exception:
        dt = datetime.utcnow()

    foto_rel = None
    if foto is not None:
        if not str(foto.content_type).lower().startswith("image/"):
            raise HTTPException(status_code=400, detail="Archivo de foto inválido")
        y = dt.year
        m = f"{dt.month:02d}"
        destino = FOTOS_DIR / str(y) / m
        destino.mkdir(parents=True, exist_ok=True)
        fname = f"evidencia_{uuid.uuid4().hex}.jpg"
        fpath = destino / fname
        with open(fpath, "wb") as out:
            shutil.copyfileobj(foto.file, out)
        foto_rel = f"/fotos/evidencias/{y}/{m}/{fname}"

    conn = get_conn()
    try:
        ensure_table_entregas_app(conn)
        with conn.cursor() as cur:
            rec_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO public.entregas_app
                (id, nombre, camion, litros, estado, fecha, lat, lon, foto_ruta)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (rec_id, nombre, camion, litros_int, estado, dt, lat, lon, foto_rel),
            )
        conn.commit()
        return {"ok": True, "id": rec_id, "foto_url": foto_rel}
    finally:
        put_conn(conn)

# =============================================================================
# REGISTRAR ENTREGAS MANUAL (desde frontend web)
# =============================================================================
def ensure_table_registrar_entregas(conn) -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS public.entregas_manual (
        id UUID PRIMARY KEY,
        nombre TEXT NOT NULL,
        camion TEXT NOT NULL,
        litros INTEGER NOT NULL,
        fecha TIMESTAMP NOT NULL,
        lat DOUBLE PRECISION,
        lon DOUBLE PRECISION,
        created_at TIMESTAMP DEFAULT NOW()
    );
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()

@app.post("/registrar-entregas")
async def registrar_entregas(
    nombre: str = Form(...),
    camion: str = Form(...),
    litros: str = Form(...),
    fecha: str = Form(...),
    lat: Optional[float] = Form(None),
    lon: Optional[float] = Form(None),
):
    if pool is None:
        raise HTTPException(status_code=503, detail="DB no configurada")

    try:
        litros_int = int(float(litros))
    except Exception:
        raise HTTPException(status_code=400, detail="Litros inválidos")

    try:
        if len(fecha) <= 10:
            dt = datetime.strptime(fecha, "%Y-%m-%d")
        else:
            dt = datetime.fromisoformat(fecha.replace("Z", "+00:00"))
    except Exception:
        dt = datetime.utcnow()

    conn = get_conn()
    try:
        ensure_table_registrar_entregas(conn)
        with conn.cursor() as cur:
            rec_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO public.entregas_manual
                (id, nombre, camion, litros, fecha, lat, lon)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                """,
                (rec_id, nombre, camion, litros_int, dt, lat, lon),
            )
        conn.commit()
        return {"ok": True, "id": rec_id}
    finally:
        put_conn(conn)

# =============================================================================
# CATÁLOGOS / NUEVOS PUNTOS (para RegistrarNuevoPunto.js)
# =============================================================================
@app.get("/camiones")
def listar_camiones(only_active: bool = True):
    items = ["A1", "A2", "A3", "A4", "A5", "M1", "M2", "M3"]
    return {"ok": True, "items": items}

class PuntoNuevo(BaseModel):
    nombre: str
    litros: int
    telefono: Optional[str] = None
    latitud: float
    longitud: float
    dia: Optional[str] = None
    camion_override: Optional[str] = None
