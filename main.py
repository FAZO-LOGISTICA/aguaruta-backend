# principal.py
# Backend FastAPI – AguaRuta (versión consolidada)
# - Pool PostgreSQL con SSL
# - CORS para web/app
# - /url.txt servido desde archivo local
# - Evidencias en /fotos/evidencias/YYYY/MM
# - Rutas mínimas de respaldo si no existen routers externos

import os
import io
import sys
import json
import uuid
import math
import time
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import psycopg2
from psycopg2.pool import SimpleConnectionPool

# =============================================================================
# CONFIGURACIÓN GENERAL
# =============================================================================

APP_NAME = "AguaRuta Backend"
BASE_DIR = Path(__file__).resolve().parent
FOTOS_DIR = BASE_DIR / "fotos" / "evidencias"

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("aguaruta")

# -----------------------------------------------------------------------------
# DB: URL + Pool con SSL
# -----------------------------------------------------------------------------
DB_URL = (
    os.getenv("DATABASE_URL")
    or os.getenv("DB_URL")
    or os.getenv("POSTGRES_URL")
)

if not DB_URL:
    log.warning("⚠️ Falta DATABASE_URL/DB_URL en variables de entorno. "
                "Se cargarán rutas de respaldo si aplican.")
else:
    # Forzar sslmode=require si no está presente (evita errores en Render/Neon)
    if "sslmode=" not in DB_URL:
        sep = "&" if ("?" in DB_URL) else "?"
        DB_URL = f"{DB_URL}{sep}sslmode=require"

pool: Optional[SimpleConnectionPool] = None

def init_pool():
    global pool
    if DB_URL and (pool is None):
        log.info("Inicializando pool de conexiones…")
        pool = SimpleConnectionPool(
            minconn=1,
            maxconn=int(os.getenv("DB_MAX_CONN", "8")),
            dsn=DB_URL
        )
        log.info("Pool de conexiones listo.")

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
# FASTAPI APP
# =============================================================================

app = FastAPI(title=APP_NAME)

# CORS (Netlify, Expo y genérico)
allow_origins = [
    os.getenv("FRONTEND_ORIGIN", "https://aguaruta.netlify.app"),
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:5173",
    # Expo Go / Metro typical origins (no siempre aplican a CORS, pero no estorban)
    "exp://localhost",
    "http://192.168.0.0/16",
    "*",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Estáticos para evidencias
FOTOS_DIR.mkdir(parents=True, exist_ok=True)
if not any(m.path == "/fotos" for m in app.router.routes if hasattr(m, "path")):
    app.mount("/fotos", StaticFiles(directory=str(BASE_DIR / "fotos")), name="fotos")

# =============================================================================
# SALUD
# =============================================================================

@app.get("/", response_class=PlainTextResponse)
def root():
    return f"{APP_NAME} OK"

# =============================================================================
# /url.txt  (descubrimiento de URL del backend para la app móvil)
# =============================================================================

@app.get("/url.txt", response_class=PlainTextResponse)
def url_txt():
    """
    Devuelve el contenido del archivo url.txt (una sola línea con la URL pública actual).
    """
    fp = BASE_DIR / "url.txt"
    if not fp.exists():
        raise HTTPException(status_code=404, detail="url.txt no existe")
    return fp.read_text(encoding="utf-8").strip()

# =============================================================================
# Carga opcional de routers externos si existen
# =============================================================================

def try_include_router(mod_path: str, attr: str = "router", prefix: str = ""):
    try:
        module = __import__(mod_path, fromlist=[attr])
        router = getattr(module, attr)
        app.include_router(router, prefix=prefix)
        log.info(f"Router '{mod_path}' cargado")
        return True
    except Exception as e:
        log.warning(f"No se pudo cargar router {mod_path}: {e}")
        return False

loaded_rutas = try_include_router("enrutadores.rutas_activas")  # expone /rutas-activas
loaded_entregas = try_include_router("enrutadores.entregas")    # expone /entregas-app
_ = try_include_router("enrutadores.redistribucion")            # opcional

# =============================================================================
# FALLBACKS (si no existen routers)
# =============================================================================

def ensure_table_entregas_app(conn):
    sql = """
    CREATE TABLE IF NOT EXISTS entregas_app (
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

if not loaded_rutas:
    @app.get("/rutas-activas")
    def rutas_activas():
        """
        Respaldo mínimo de /rutas-activas si no hay router:
        SELECT camion, nombre, latitud, longitud, litros, dia_asignado AS dia, telefono FROM ruta_activa
        """
        if pool is None:
            raise HTTPException(status_code=503, detail="DB no configurada")
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        camion,
                        nombre,
                        latitud,
                        longitud,
                        litros,
                        COALESCE(dia_asignado, dia) AS dia,
                        telefono
                    FROM ruta_activa
                """)
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
            data = [dict(zip(cols, r)) for r in rows]
            return data
        finally:
            put_conn(conn)

if not loaded_entregas:
    @app.post("/entregas-app")
    async def entregas_app(
        nombre: str = Form(...),
        camion: str = Form(...),
        litros: str = Form(...),
        estado: int = Form(...),        # 1=entregada(sin foto), 0/2=con foto, 3=sin foto
        fecha: str = Form(...),         # "YYYY-MM-DD" o ISO
        lat: Optional[float] = Form(None),
        lon: Optional[float] = Form(None),
        foto: Optional[UploadFile] = File(None),
    ):
        """
        Guarda entrega + evidencia (si corresponde) y registra en Postgres.
        Devuelve {ok, id, foto_url?}
        """
        if pool is None:
            raise HTTPException(status_code=503, detail="DB no configurada")

        # Normaliza litros/fecha
        try:
            litros_int = int(float(litros))
        except Exception:
            litros_int = None

        try:
            # Acepta fecha "YYYY-MM-DD" o ISO
            if len(fecha) <= 10:
                dt = datetime.strptime(fecha, "%Y-%m-%d")
            else:
                dt = datetime.fromisoformat(fecha.replace("Z", "+00:00"))
        except Exception:
            dt = datetime.utcnow()

        # Guardar foto si viene adjunta
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

            # Save to disk
            with open(fpath, "wb") as out:
                shutil.copyfileobj(foto.file, out)

            # URL pública (servimos /fotos/…)
            foto_rel = f"/fotos/evidencias/{y}/{m}/{fname}"

        # Insert en DB
        conn = get_conn()
        try:
            ensure_table_entregas_app(conn)
            with conn.cursor() as cur:
                rec_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO entregas_app
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
# STARTUP / SHUTDOWN
# =============================================================================

@app.on_event("startup")
def on_startup():
    try:
        init_pool()
    except Exception as e:
        log.warning(f"No se pudo inicializar pool DB al inicio: {e}")
    log.info("Aplicación iniciada.")

@app.on_event("shutdown")
def on_shutdown():
    global pool
    try:
        if pool:
            pool.closeall()
            log.info("Pool DB cerrado.")
    except Exception:
        pass

# =============================================================================
# UTIL: Export CSV/Excel (opcional) – placeholder si lo necesitas luego
# =============================================================================
# Aquí podrías mantener tus endpoints de exportación, limpieza, etc.
