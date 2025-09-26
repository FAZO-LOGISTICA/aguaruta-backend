# 🚀 Backend FastAPI – AguaRuta (completo y estable)
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

DB_URL = os.getenv("DATABASE_URL") or os.getenv("DB_URL") or os.getenv("POSTGRES_URL")
if DB_URL and "sslmode=" not in DB_URL:
    DB_URL += ("&" if "?" in DB_URL else "?") + "sslmode=require"

POOL_MIN = int(os.getenv("PG_POOL_MIN", "1"))
POOL_MAX = int(os.getenv("PG_POOL_MAX", "3"))
pool: Optional[SimpleConnectionPool] = None

def init_pool() -> None:
    global pool
    if DB_URL and pool is None:
        pool = SimpleConnectionPool(POOL_MIN, POOL_MAX, DB_URL)
        log.info("✅ Pool DB inicializado")

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 🔥 abierto (incluye Netlify y app móvil)
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
        put_conn(conn)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# =============================================================================
# FIX: asegurar tabla/columnas en rutas_activas
# =============================================================================
def ensure_table_rutas_activas(conn):
    sql = """
    CREATE TABLE IF NOT EXISTS public.rutas_activas (
        id SERIAL PRIMARY KEY,
        camion TEXT,
        nombre TEXT,
        dia TEXT,
        litros INTEGER
    );
    ALTER TABLE public.rutas_activas
        ADD COLUMN IF NOT EXISTS telefono TEXT,
        ADD COLUMN IF NOT EXISTS latitud DOUBLE PRECISION,
        ADD COLUMN IF NOT EXISTS longitud DOUBLE PRECISION,
        ADD COLUMN IF NOT EXISTS activa BOOLEAN DEFAULT TRUE;
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()

# =============================================================================
# RUTAS ACTIVAS
# =============================================================================
@app.get("/rutas-activas")
def rutas_activas():
    conn = get_conn()
    try:
        ensure_table_rutas_activas(conn)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, camion, nombre, dia, litros,
                       telefono, latitud, longitud, activa
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
        ensure_table_rutas_activas(conn)
        updates: Dict[str, Any] = {k: v for k, v in body.dict().items() if v is not None}
        if not updates:
            return {"ok": True, "updated": 0}
        sets = [f"{col}=%s" for col in updates]
        vals = list(updates.values()) + [rid]
        sql = f"UPDATE public.rutas_activas SET {', '.join(sets)} WHERE id=%s;"
        with conn.cursor() as cur:
            cur.execute(sql, vals)
            updated = cur.rowcount
        conn.commit()
        return {"ok": True, "updated": updated}
    finally:
        put_conn(conn)

@app.delete("/rutas-activas/{rid}")
def delete_ruta_activa(rid: int):
    conn = get_conn()
    try:
        ensure_table_rutas_activas(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.rutas_activas WHERE id=%s;", (rid,))
            deleted = cur.rowcount
        conn.commit()
        return {"ok": True, "deleted": deleted}
    finally:
        put_conn(conn)

# =============================================================================
# ENTREGAS APP (choferes)
# =============================================================================
def ensure_table_entregas_app(conn):
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
        foto_ruta TEXT,
        fuente TEXT DEFAULT 'app'
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
    conn = get_conn()
    try:
        ensure_table_entregas_app(conn)
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
            y, m = dt.year, f"{dt.month:02d}"
            destino = FOTOS_DIR / str(y) / m
            destino.mkdir(parents=True, exist_ok=True)
            fname = f"evidencia_{uuid.uuid4().hex}.jpg"
            fpath = destino / fname
            with open(fpath, "wb") as out:
                shutil.copyfileobj(foto.file, out)
            foto_rel = f"/fotos/evidencias/{y}/{m}/{fname}"

        with conn.cursor() as cur:
            rec_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO public.entregas_app
                (id, nombre, camion, litros, estado, fecha, lat, lon, foto_ruta, fuente)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'app')
                """,
                (rec_id, nombre, camion, litros_int, estado, dt, lat, lon, foto_rel),
            )
        conn.commit()
        return {"ok": True, "id": rec_id, "foto_url": foto_rel}
    finally:
        put_conn(conn)

# =============================================================================
# ENTREGAS MANUALES (RegistrarEntrega.js)
# =============================================================================
def ensure_table_entregas(conn):
    sql = """
    CREATE TABLE IF NOT EXISTS public.entregas (
        id UUID PRIMARY KEY,
        nombre TEXT,
        camion TEXT,
        litros INTEGER,
        estado INTEGER,
        fecha TIMESTAMP,
        latitud DOUBLE PRECISION,
        longitud DOUBLE PRECISION,
        fuente TEXT DEFAULT 'manual'
    );
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()

@app.post("/registrar-entregas")
def registrar_entregas(body: Dict[str, Any] = Body(...)):
    conn = get_conn()
    try:
        ensure_table_entregas(conn)
        rec_id = str(uuid.uuid4())
        try:
            litros_int = int(body.get("litros", 0))
        except Exception:
            litros_int = None
        try:
            fecha_str = body.get("fecha")
            if fecha_str and len(fecha_str) <= 10:
                dt = datetime.strptime(fecha_str, "%Y-%m-%d")
            elif fecha_str:
                dt = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
            else:
                dt = datetime.utcnow()
        except Exception:
            dt = datetime.utcnow()

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.entregas
                (id, nombre, camion, litros, estado, fecha, latitud, longitud, fuente)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'manual')
                """,
                (
                    rec_id,
                    body.get("nombre"),
                    body.get("camion"),
                    litros_int,
                    body.get("estado", 1),
                    dt,
                    body.get("latitud"),
                    body.get("longitud"),
                ),
            )
        conn.commit()
        return {"ok": True, "id": rec_id}
    finally:
        put_conn(conn)

# =============================================================================
# ENTREGAS – UNIFICADAS
# =============================================================================
@app.get("/entregas-todas")
def entregas_todas():
    conn = get_conn()
    try:
        ensure_table_entregas_app(conn)
        ensure_table_entregas(conn)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, nombre, camion, litros, estado, fecha,
                       lat AS latitud, lon AS longitud, fuente
                FROM public.entregas_app
                UNION ALL
                SELECT id, nombre, camion, litros, estado, fecha,
                       latitud, longitud, fuente
                FROM public.entregas
                ORDER BY fecha DESC;
            """)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        put_conn(conn)

# =============================================================================
# START/STOP
# =============================================================================
@app.on_event("startup")
def on_startup():
    try:
        init_pool()
    except Exception as e:
        log.warning(f"No se pudo inicializar pool DB: {e}")
    log.info("🚀 Aplicación iniciada")

@app.on_event("shutdown")
def on_shutdown():
    global pool
    try:
        if pool:
            pool.closeall()
            log.info("Pool DB cerrado.")
    except Exception:
        pass
