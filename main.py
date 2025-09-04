# main.py
# Backend FastAPI – AguaRuta (contrato estable)
# - Pool PostgreSQL con SSL (Render/Neon)
# - CORS (Netlify/localhost)
# - CRUD básico sobre public.ruta_activa
# - Registrar nuevo punto con auto-asignación por vecino más cercano
# - Evidencias /entregas-app
# - (Opcional) catálogo /camiones para verificación/creación de códigos

import os
import uuid
import math
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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

# -----------------------------------------------------------------------------#
# DB URL + Pool con SSL
# -----------------------------------------------------------------------------#
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
# SALUD / URL
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

@app.get("/url.txt", response_class=PlainTextResponse)
def url_txt():
    fp = BASE_DIR / "url.txt"
    if not fp.exists():
        raise HTTPException(status_code=404, detail="url.txt no existe")
    return fp.read_text(encoding="utf-8").strip()

# =============================================================================
# UTILS
# =============================================================================

def to_float(v) -> Optional[float]:
    if v is None: return None
    try:
        return float(str(v).replace(",", ".").strip())
    except Exception:
        return None

def to_int(v) -> Optional[int]:
    f = to_float(v)
    return int(round(f)) if f is not None else None

def dictfetchall(cur) -> List[Dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

def ensure_table_camiones(conn) -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS public.camiones (
        codigo TEXT PRIMARY KEY,
        nombre TEXT,
        capacidad_litros INTEGER,
        activo BOOLEAN DEFAULT TRUE
    );
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()

def haversine_km(lat1, lon1, lat2, lon2) -> float:
    # distancia aproximada en km
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb/2)**2
    return 2 * R * math.asin(math.sqrt(a))

# =============================================================================
# MODELOS
# =============================================================================

class RutaUpdate(BaseModel):
    camion: Optional[str] = None
    nombre: Optional[str] = None
    dia: Optional[str] = None
    litros: Optional[int] = Field(default=None)
    telefono: Optional[str] = None
    latitud: Optional[float] = Field(default=None)
    longitud: Optional[float] = Field(default=None)

class NuevoPunto(BaseModel):
    nombre: str
    litros: int
    telefono: Optional[str] = None
    latitud: float
    longitud: float
    dia: Optional[str] = None
    camion_override: Optional[str] = None

# =============================================================================
# RUTAS ACTIVAS – CRUD
# =============================================================================

@app.get("/rutas-activas")
def rutas_activas():
    """
    Devuelve rutas activas leyendo DIRECTO de public.ruta_activa.
    Contrato: [{id, camion, nombre, dia, litros, telefono, latitud, longitud}]
    """
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
            return dictfetchall(cur)
    finally:
        put_conn(conn)

@app.put("/rutas-activas/{id}")
def rutas_activas_update(id: int, payload: RutaUpdate = Body(...)):
    """
    Actualiza parcialmente un registro de ruta_activa.
    """
    if pool is None:
        raise HTTPException(status_code=503, detail="DB no configurada")

    # construir SET dinámico
    campos = []
    valores = []

    if payload.camion is not None:
        campos.append("camion = %s"); valores.append(payload.camion.strip() or None)
    if payload.nombre is not None:
        campos.append("nombre = %s"); valores.append(payload.nombre.strip() or None)
    if payload.dia is not None:
        campos.append("dia = %s"); valores.append(payload.dia.strip() or None)
    if payload.litros is not None:
        campos.append("litros = %s"); valores.append(int(payload.litros))
    if payload.telefono is not None:
        campos.append("telefono = %s"); valores.append(payload.telefono.strip() or None)
    if payload.latitud is not None:
        lf = to_float(payload.latitud)
        campos.append("latitud = %s"); valores.append(lf)
    if payload.longitud is not None:
        ln = to_float(payload.longitud)
        campos.append("longitud = %s"); valores.append(ln)

    if not campos:
        return {"ok": True, "updated": 0}

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            sql = f"UPDATE public.ruta_activa SET {', '.join(campos)} WHERE id = %s"
            valores.append(id)
            cur.execute(sql, valores)
        conn.commit()
        return {"ok": True, "updated": 1}
    finally:
        put_conn(conn)

@app.delete("/rutas-activas/{id}")
def rutas_activas_delete(id: int):
    """
    Elimina un registro de ruta_activa por ID.
    """
    if pool is None:
        raise HTTPException(status_code=503, detail="DB no configurada")
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.ruta_activa WHERE id = %s", (id,))
            deleted = cur.rowcount
        conn.commit()
        if deleted == 0:
            raise HTTPException(status_code=404, detail="Registro no encontrado")
        return {"ok": True, "deleted": deleted}
    finally:
        put_conn(conn)

# =============================================================================
# Registrar nuevo punto con auto-asignación por vecino más cercano
# =============================================================================

@app.post("/registrar-nuevo-punto-auto")
def registrar_nuevo_punto_auto(data: NuevoPunto):
    """
    Inserta un registro en ruta_activa.
    - Si 'camion_override' viene, se usa ese camión.
    - Si no, se copia camión/día del vecino más cercano (si existe).
    - Si no hay vecinos, se usa camion='A1' y dia=(data.dia o NULL).
    Devuelve {ok, id, asignacion:{camion, dia}, vecino_id?}
    """
    if pool is None:
        raise HTTPException(status_code=503, detail="DB no configurada")

    nombre = data.nombre.strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="Nombre obligatorio")

    litros = int(data.litros)
    lat = float(data.latitud)
    lon = float(data.longitud)
    telefono = (data.telefono or "").strip() or None

    # Determinar camión/día
    asign_camion = (data.camion_override or "").strip().upper() or None
    asign_dia = (data.dia or "").strip().upper() or None
    vecino_id = None

    conn = get_conn()
    try:
        # Si no forzó camión, buscar vecino más cercano
        if not asign_camion:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, camion, dia, latitud, longitud
                    FROM public.ruta_activa
                    WHERE latitud IS NOT NULL AND longitud IS NOT NULL
                """)
                vecinos = dictfetchall(cur)

            best = None
            best_dist = 1e12
            for v in vecinos:
                try:
                    d = haversine_km(lat, lon, float(v["latitud"]), float(v["longitud"]))
                    if d < best_dist:
                        best = v; best_dist = d
                except Exception:
                    continue

            if best:
                vecino_id = best["id"]
                asign_camion = (best.get("camion") or "").strip() or "A1"
                asign_dia = asign_dia or (best.get("dia") or None)

        # defaults si seguimos sin camión
        if not asign_camion:
            asign_camion = "A1"

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.ruta_activa
                (camion, nombre, dia, litros, telefono, latitud, longitud)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (asign_camion, nombre, asign_dia, litros, telefono, lat, lon),
            )
            new_id = cur.fetchone()[0]
        conn.commit()

        return {
            "ok": True,
            "id": new_id,
            "asignacion": {"camion": asign_camion, "dia": asign_dia},
            "vecino_id": vecino_id,
        }
    finally:
        put_conn(conn)

# =============================================================================
# CAMIONES (opcional para verificación/creación desde el picker)
# =============================================================================

@app.get("/camiones")
def camiones_list(only_active: bool = True):
    """
    Devuelve catálogo de camiones (si existe tabla public.camiones).
    Si no existe, intenta crearla vacía.
    """
    if pool is None:
        raise HTTPException(status_code=503, detail="DB no configurada")
    conn = get_conn()
    try:
        ensure_table_camiones(conn)
        with conn.cursor() as cur:
            if only_active:
                cur.execute("SELECT codigo, nombre, capacidad_litros, activo FROM public.camiones WHERE activo = true")
            else:
                cur.execute("SELECT codigo, nombre, capacidad_litros, activo FROM public.camiones")
            return dictfetchall(cur)
    finally:
        put_conn(conn)

class CamionUpsert(BaseModel):
    codigo: str
    nombre: Optional[str] = None
    capacidad_litros: Optional[int] = None
    activo: Optional[bool] = True

@app.post("/camiones")
def camiones_upsert(payload: CamionUpsert):
    """
    Crea/actualiza un camión en public.camiones para que el picker pueda verificar/crear códigos.
    """
    if pool is None:
        raise HTTPException(status_code=503, detail="DB no configurada")
    codigo = (payload.codigo or "").strip().upper()
    if not codigo:
        raise HTTPException(status_code=400, detail="Código inválido")

    conn = get_conn()
    try:
        ensure_table_camiones(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.camiones (codigo, nombre, capacidad_litros, activo)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (codigo)
                DO UPDATE SET nombre=EXCLUDED.nombre, capacidad_litros=EXCLUDED.capacidad_litros, activo=EXCLUDED.activo
                """,
                (codigo, payload.nombre, payload.capacidad_litros, payload.activo),
            )
        conn.commit()
        return {"ok": True, "codigo": codigo}
    finally:
        put_conn(conn)

# =============================================================================
# ENTREGAS APP (con evidencia)
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
