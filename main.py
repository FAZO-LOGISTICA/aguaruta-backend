# main.py
# Backend FastAPI – AguaRuta (contrato estable + altas y camiones)
# - Pool PostgreSQL con SSL (Render/Neon)
# - CORS para Netlify/localhost
# - /rutas-activas LEE DIRECTO de public.ruta_activa
# - /registrar-nuevo-punto-auto inserta en ruta_activa (auto-asignación o override)
# - /camiones (GET/POST upsert)
# - /entregas-app guarda evidencia en /fotos/evidencias/YYYY/MM

import os
import uuid
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Body
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
# APP
# =============================================================================

app = FastAPI(title=APP_NAME)

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
# HELPERS / SCHEMA SAFE
# =============================================================================

def normalize_camion(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    s = str(code).strip().upper()
    # admite "A 1", "A-1", "M 2", "M2", etc.
    import re
    m = re.match(r"^\s*([AM])\s*-?\s*(\d{1,2})\s*$", s)
    if m:
        return f"{m.group(1)}{int(m.group(2))}"
    if (s.startswith("A") or s.startswith("M")) and len(s) <= 3:
        return s
    return None

def to_int(v):
    if v is None or v == "":
        return None
    try:
        return int(round(float(str(v).replace(",", "."))))
    except Exception:
        return None

def to_float(v):
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return None

def ensure_indexes(conn):
    with conn.cursor() as cur:
        # ÍNDICES para búsqueda rápida por proximidad/camión (no falla si no existen)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ruta_activa_camion ON public.ruta_activa (camion);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ruta_activa_lonlat ON public.ruta_activa (longitud, latitud);")
    conn.commit()

def ensure_table_camiones(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.camiones (
              codigo TEXT PRIMARY KEY,
              nombre TEXT,
              capacidad_litros INTEGER,
              activo BOOLEAN DEFAULT TRUE
            );
        """)
    conn.commit()

def ruta_activa_tiene_id(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='ruta_activa' AND column_name='id'
            LIMIT 1;
        """)
        return cur.fetchone() is not None

# =============================================================================
# ENDPOINTS DE NEGOCIO
# =============================================================================

@app.get("/rutas-activas")
def rutas_activas():
    """
    Devuelve rutas activas leyendo DIRECTO de public.ruta_activa.
    Contrato: [{camion, nombre, dia, litros, telefono, latitud, longitud}]
    """
    if pool is None:
        raise HTTPException(status_code=503, detail="DB no configurada")
    conn = get_conn()
    try:
        ensure_indexes(conn)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT camion, nombre, dia, litros, telefono, latitud, longitud
                FROM public.ruta_activa
                ORDER BY camion, nombre;
            """)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        put_conn(conn)

@app.post("/registrar-nuevo-punto-auto")
def registrar_nuevo_punto_auto(body: Dict[str, Any] = Body(...)):
    """
    JSON:
    {
      nombre, litros, telefono?, latitud, longitud, dia?,
      camion_override? ('M6','A7', etc.)
    }
    Inserta en public.ruta_activa con auto-asignación por vecino más cercano,
    a menos que se envíe camion_override.
    """
    nombre = (body.get("nombre") or "").strip()
    litros = to_int(body.get("litros"))
    telefono = (body.get("telefono") or "").strip() or None
    lat = to_float(body.get("latitud"))
    lon = to_float(body.get("longitud"))
    dia_in = (body.get("dia") or "").strip() or None
    camion_override = normalize_camion(body.get("camion_override"))

    if not nombre:
        raise HTTPException(status_code=400, detail="Falta nombre.")
    if not litros or litros <= 0:
        raise HTTPException(status_code=400, detail="Litros inválidos.")
    if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise HTTPException(status_code=400, detail="Coordenadas inválidas.")

    if pool is None:
        raise HTTPException(status_code=503, detail="DB no configurada")

    conn = get_conn()
    try:
        ensure_indexes(conn)

        vecino_camion = None
        vecino_dia = None
        # Busca vecino más cercano (si existe)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT camion, dia
                FROM public.ruta_activa
                ORDER BY ((latitud - %s)^2 + (longitud - %s)^2) ASC
                LIMIT 1;
            """, (lat, lon))
            r = cur.fetchone()
            if r:
                vecino_camion, vecino_dia = r[0], (r[1] or None)

        asign_camion = camion_override or vecino_camion or "A1"
        asign_dia = dia_in or vecino_dia or None

        new_id = None
        with conn.cursor() as cur:
            # si existe columna id, devolvemos id
            if ruta_activa_tiene_id(conn):
                cur.execute("""
                    INSERT INTO public.ruta_activa (camion, nombre, dia, litros, telefono, latitud, longitud)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id;
                """, (asign_camion, nombre, asign_dia, litros, telefono, lat, lon))
                new_id = cur.fetchone()[0]
            else:
                cur.execute("""
                    INSERT INTO public.ruta_activa (camion, nombre, dia, litros, telefono, latitud, longitud)
                    VALUES (%s,%s,%s,%s,%s,%s,%s);
                """, (asign_camion, nombre, asign_dia, litros, telefono, lat, lon))
        conn.commit()

        return {"ok": True, "id": new_id, "asignacion": {"camion": asign_camion, "dia": asign_dia}}
    finally:
        put_conn(conn)

# ----------------------- CAMIONES API -----------------------

@app.get("/camiones")
def listar_camiones(only_active: bool = False):
    if pool is None:
        raise HTTPException(status_code=503, detail="DB no configurada")
    conn = get_conn()
    try:
        ensure_table_camiones(conn)
        with conn.cursor() as cur:
            if only_active:
                cur.execute("""
                    SELECT codigo, nombre, capacidad_litros, activo
                    FROM public.camiones
                    WHERE activo IS TRUE
                    ORDER BY codigo;
                """)
            else:
                cur.execute("""
                    SELECT codigo, nombre, capacidad_litros, activo
                    FROM public.camiones
                    ORDER BY codigo;
                """)
            rows = cur.fetchall()
        return [{"codigo": r[0], "nombre": r[1], "capacidad_litros": r[2], "activo": r[3]} for r in rows]
    finally:
        put_conn(conn)

@app.post("/camiones")
def upsert_camion(body: Dict[str, Any] = Body(...)):
    """
    { codigo: 'M6', nombre?: str, capacidad_litros?: int, activo?: bool }
    """
    if pool is None:
        raise HTTPException(status_code=503, detail="DB no configurada")

    codigo = normalize_camion(body.get("codigo"))
    if not codigo:
        raise HTTPException(status_code=400, detail="Código de camión inválido.")
    nombre = (body.get("nombre") or None)
    cap = to_int(body.get("capacidad_litros"))
    activo = body.get("activo")
    if activo is None:
        activo = True

    conn = get_conn()
    try:
        ensure_table_camiones(conn)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO public.camiones (codigo, nombre, capacidad_litros, activo)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (codigo) DO UPDATE
                SET nombre = EXCLUDED.nombre,
                    capacidad_litros = EXCLUDED.capacidad_litros,
                    activo = EXCLUDED.activo;
            """, (codigo, nombre, cap, bool(activo)))
        conn.commit()
        return {"ok": True, "codigo": codigo}
    finally:
        put_conn(conn)

# ----------------------- ENTREGAS APP -----------------------

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
    estado: int = Form(...),        # 1=entregada; 0/2=con foto; 3=sin foto por no ubicar
    fecha: str = Form(...),         # "YYYY-MM-DD" o ISO
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
# STARTUP / SHUTDOWN
# =============================================================================

@app.on_event("startup")
def on_startup():
    try:
        init_pool()
        if pool:
            conn = get_conn()
            try:
                ensure_indexes(conn)
                ensure_table_camiones(conn)
            finally:
                put_conn(conn)
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
