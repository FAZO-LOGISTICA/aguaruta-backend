# principal.py
# Backend FastAPI – AguaRuta (versión consolidada y robusta)
# - Pool PostgreSQL con SSL (Render/Neon)
# - CORS para Netlify/localhost
# - /url.txt servido desde archivo local
# - Evidencias en /fotos/evidencias/YYYY/MM
# - Fallbacks si no existen routers externos
# - /rutas-activas tolerante a nombres de columnas/tabla

import os
import uuid
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

import psycopg2
from psycopg2.pool import SimpleConnectionPool

# =============================================================================
# CONFIG
# =============================================================================

APP_NAME = "AguaRuta Backend"
BASE_DIR = Path(__file__).resolve().parent
FOTOS_DIR = BASE_DIR / "fotos" / "evidencias"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("aguaruta")

# -----------------------------------------------------------------------------
# DB URL + Pool con SSL
# -----------------------------------------------------------------------------
DB_URL = (
    os.getenv("DATABASE_URL")
    or os.getenv("DB_URL")
    or os.getenv("POSTGRES_URL")
)

if not DB_URL:
    log.warning("⚠️ Falta DATABASE_URL/DB_URL/POSTGRES_URL en variables de entorno.")
else:
    if "sslmode=" not in DB_URL:
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
# APP
# =============================================================================

app = FastAPI(title=APP_NAME)

# CORS
allow_origins = [
    os.getenv("FRONTEND_ORIGIN", "https://aguaruta.netlify.app"),
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:5173",
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
# Carga opcional de routers externos
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

loaded_rutas = try_include_router("enrutadores.rutas_activas")   # /rutas-activas
loaded_entregas = try_include_router("enrutadores.entregas")     # /entregas-app
_ = try_include_router("enrutadores.redistribucion")             # opcional

# =============================================================================
# Utilidades SQL para fallback
# =============================================================================

def table_exists(cur, name: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema='public' AND table_name=%s
        """,
        (name,),
    )
    return cur.fetchone() is not None

def existing_columns(cur, table: str) -> set:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s
        """,
        (table,),
    )
    return {r[0] for r in cur.fetchall()}

def pick_col(cols: set, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in cols:
            return c
    return None

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
        Respaldo /rutas-activas tolerante a nombres de columnas y tabla:
        - Tabla: busca primero 'rutas_activas' y si no, 'ruta_activa'.
        - Columnas: usa la primera que exista entre varios candidatos.
        """
        if pool is None:
            raise HTTPException(status_code=503, detail="DB no configurada")
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                # 1) Detecta tabla
                table = None
                for t in ("rutas_activas", "ruta_activa"):
                    if table_exists(cur, t):
                        table = t
                        break
                if not table:
                    raise HTTPException(status_code=500, detail="No existe tabla rutas_activas/ruta_activa")

                # 2) Detecta columnas disponibles
                cols = existing_columns(cur, table)

                camion_col   = pick_col(cols, ["camion", "id_camion"])
                nombre_col   = pick_col(cols, ["nombre", "jefe_hogar", "vecino"])
                dia_col      = pick_col(cols, ["dia_asignado", "dia"])
                litros_col   = pick_col(cols, ["litros_entrega", "litros"])
                telefono_col = pick_col(cols, ["telefono", "tel"])
                lat_col      = pick_col(cols, ["latitud", "lat"])
                lon_col      = pick_col(cols, ["longitud", "lon", "lng"])

                if not camion_col or not nombre_col or not dia_col or not litros_col or not lat_col or not lon_col:
                    raise HTTPException(status_code=500, detail=f"Faltan columnas mínimas en {table}")

                # 3) Construye SELECT seguro
                select_parts = [
                    f"{camion_col}   AS camion",
                    f"{nombre_col}   AS nombre",
                    f"{dia_col}      AS dia",
                    f"{litros_col}   AS litros",
                    (f"{telefono_col} AS telefono" if telefono_col else "NULL::text AS telefono"),
                    f"{lat_col}      AS latitud",
                    f"{lon_col}      AS longitud",
                ]
                q = f"SELECT {', '.join(select_parts)} FROM {table} ORDER BY {camion_col}, {nombre_col};"

                cur.execute(q)
                rows = cur.fetchall()
                hdrs = [d[0] for d in cur.description]
                return [dict(zip(hdrs, r)) for r in rows]
        finally:
            put_conn(conn)

if not loaded_entregas:
    @app.post("/entregas-app")
    async def entregas_app(
        nombre: str = Form(...),
        camion: str = Form(...),
        litros: str = Form(...),
        estado: int = Form(...),        # 1=entregada; 0/2=con foto; 3=sin foto por no ubicar
        fecha: str = Form(...),         # "YYYY-MM-DD" o ISO
        lat: Optional[float] = Form(None),
        lon: Optional[float] = Form(None),
        foto: Optional[UploadFile] = File(None),
    ):
        if pool is None:
            raise HTTPException(status_code=503, detail="DB no configurada")

        # Normaliza litros
        try:
            litros_int = int(float(litros))
        except Exception:
            litros_int = None

        # Normaliza fecha
        try:
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
            with open(fpath, "wb") as out:
                shutil.copyfileobj(foto.file, out)
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
