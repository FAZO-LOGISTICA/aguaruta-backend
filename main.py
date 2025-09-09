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

# CORS robusto. Si FRONTEND_ORIGIN está vacío, se usa Netlify por defecto.
FE = os.getenv("FRONTEND_ORIGIN") or "https://aguaruta.netlify.app"
allow_origins = [FE, "http://localhost", "http://localhost:3000", "http://localhost:5173"]
log.info(f"CORS allow_origins: {allow_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],      # incluye DELETE/PUT/OPTIONS
    allow_headers=["*"],
)

# Preflight global (por si alguna ruta/exception se interpone)
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
# ENTREGAS APP (fotos de respaldo/no entrega)
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

    # litros
    try:
        litros_int = int(float(litros))
    except Exception:
        litros_int = None

    # fecha
    try:
        if len(fecha) <= 10:
            dt = datetime.strptime(fecha, "%Y-%m-%d")
        else:
            dt = datetime.fromisoformat(fecha.replace("Z", "+00:00"))
    except Exception:
        dt = datetime.utcnow()

    # foto
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

    # insert
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
# CATÁLOGOS / NUEVOS PUNTOS (para RegistrarNuevoPunto.js)
# =============================================================================
@app.get("/camiones")
def listar_camiones(only_active: bool = True):
    """
    Devuelve el listado de camiones disponibles.
    Si deseas, reemplaza por SELECT DISTINCT camion FROM public.ruta_activa ...
    """
    items = ["A1", "A2", "A3", "A4", "A5", "M1", "M2", "M3"]
    return {"ok": True, "items": items}

class PuntoNuevo(BaseModel):
    nombre: str
    litros: int
    telefono: Optional[str] = None
    latitud: float
    longitud: float
    dia: Optional[str] = None                # opcional; si no viene, copia del vecino
    camion_override: Optional[str] = None    # opcional; fuerza camión

def ensure_table_nuevos_puntos(conn) -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS public.nuevos_puntos (
        id UUID PRIMARY KEY,
        nombre TEXT NOT NULL,
        telefono TEXT,
        litros INTEGER NOT NULL,
        latitud DOUBLE PRECISION NOT NULL,
        longitud DOUBLE PRECISION NOT NULL,
        camion TEXT,
        dia TEXT,
        fuente TEXT DEFAULT 'manual',
        created_at TIMESTAMP DEFAULT NOW()
    );
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()

def ensure_table_ruta_activa(conn) -> None:
    """Crea ruta_activa si no existe (seguro). Ajusta tipos si ya existe."""
    sql = """
    CREATE TABLE IF NOT EXISTS public.ruta_activa (
        id SERIAL PRIMARY KEY,
        camion TEXT,
        nombre TEXT,
        dia TEXT,
        litros INTEGER,
        telefono TEXT,
        latitud DOUBLE PRECISION,
        longitud DOUBLE PRECISION
    );
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()

def normalize_camion(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    t = str(code).upper().replace("-", "").replace(" ", "")
    return t  # Validación simple; endurecer si quieres

def nearest_assignment(conn, lat: float, lon: float) -> Optional[dict]:
    """
    Busca el punto más cercano en ruta_activa y devuelve {'camion','dia'}.
    Usa distancia euclídea simple para elegir vecino.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT camion, dia, latitud, longitud
            FROM public.ruta_activa
            WHERE latitud IS NOT NULL AND longitud IS NOT NULL
            ORDER BY ((latitud - %s)^2 + (longitud - %s)^2) ASC
            LIMIT 1;
            """,
            (lat, lon),
        )
        row = cur.fetchone()
        if not row:
            return None
        camion, dia, _nlat, _nlon = row
        return {"camion": camion, "dia": dia}

@app.post("/registrar-nuevo-punto-auto")
def registrar_nuevo_punto_auto(body: PuntoNuevo = Body(...), activar: bool = True):
    """
    Registra en 'nuevos_puntos' y, si activar=True (default), también en 'ruta_activa'
    para que el punto quede visible en Rutas Activas y en el Mapa.
    """
    if pool is None:
        raise HTTPException(status_code=503, detail="DB no configurada")

    conn = get_conn()
    try:
        ensure_table_nuevos_puntos(conn)
        if activar:
            ensure_table_ruta_activa(conn)

        # --- calcular asignación ---
        asignacion = {"camion": None, "dia": None}
        override = normalize_camion(body.camion_override)
        if override:
            asignacion["camion"] = override
            asignacion["dia"] = body.dia
        else:
            vecino = nearest_assignment(conn, body.latitud, body.longitud)
            if vecino:
                asignacion["camion"] = vecino.get("camion")
                asignacion["dia"] = body.dia or vecino.get("dia")
            else:
                asignacion["camion"] = "A1"
                asignacion["dia"] = body.dia

        # --- insertar en nuevos_puntos ---
        rec_id = str(uuid.uuid4())
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.nuevos_puntos
                (id, nombre, telefono, litros, latitud, longitud, camion, dia, fuente)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s);
                """,
                (
                    rec_id,
                    body.nombre.strip(),
                    (body.telefono or None),
                    int(body.litros),
                    float(body.latitud),
                    float(body.longitud),
                    asignacion["camion"],
                    asignacion["dia"],
                    "manual",
                ),
            )

        # --- insertar en ruta_activa (para que se vea de inmediato) ---
        ruta_id = None
        if activar:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.ruta_activa
                    (camion, nombre, dia, litros, telefono, latitud, longitud)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id;
                    """,
                    (
                        asignacion["camion"],
                        body.nombre.strip(),
                        asignacion["dia"],
                        int(body.litros),
                        (body.telefono or None),
                        float(body.latitud),
                        float(body.longitud),
                    ),
                )
                ruta_id = cur.fetchone()[0]

        conn.commit()

        return {
            "ok": True,
            "id": rec_id,
            "ruta_activa_id": ruta_id,
            "asignacion": asignacion
        }
    finally:
        put_conn(conn)

# =============================================================================
# MAPA – Unificación de puntos (ruta_activa + nuevos_puntos)
# =============================================================================
def rows_to_dicts(cur):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

@app.get("/puntos-mapa")
@app.get("/mapa-puntos")
@app.get("/puntos")
@app.get("/rutas-mapa")
def puntos_mapa():
    """
    Devuelve puntos para mapa: une ruta_activa + nuevos_puntos (mínimos campos).
    El frontend puede estar apuntando a cualquiera de estos paths.
    """
    if pool is None:
        raise HTTPException(status_code=503, detail="DB no configurada")
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT nombre, litros, telefono, latitud, longitud, camion, dia
                FROM public.ruta_activa
                WHERE latitud IS NOT NULL AND longitud IS NOT NULL
            """)
            a = rows_to_dicts(cur)

            cur.execute("""
                SELECT nombre, litros, telefono, latitud, longitud, camion, dia
                FROM public.nuevos_puntos
                WHERE latitud IS NOT NULL AND longitud IS NOT NULL
            """)
            b = rows_to_dicts(cur)

        # Priorizar ruta_activa (si hay duplicados por nombre+coords)
        seen = set((r["nombre"], r["latitud"], r["longitud"]) for r in a)
        merged = a + [r for r in b if (r["nombre"], r["latitud"], r["longitud"]) not in seen]
        return {"ok": True, "count": len(merged), "items": merged}
    finally:
        put_conn(conn)

# =============================================================================
# SINCRONIZACIÓN MASIVA (opcional)
# =============================================================================
@app.post("/sincronizar-nuevos-a-ruta-activa")
def sync_nuevos_a_ruta_activa():
    if pool is None:
        raise HTTPException(status_code=503, detail="DB no configurada")
    conn = get_conn()
    try:
        ensure_table_ruta_activa(conn)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO public.ruta_activa (camion, nombre, dia, litros, telefono, latitud, longitud)
                SELECT camion, nombre, dia, litros, telefono, latitud, longitud
                FROM public.nuevos_puntos np
                WHERE NOT EXISTS (
                    SELECT 1 FROM public.ruta_activa ra
                    WHERE ra.nombre = np.nombre
                      AND ra.latitud = np.latitud
                      AND ra.longitud = np.longitud
                );
            """)
            inserted = cur.rowcount
        conn.commit()
        return {"ok": True, "inserted": inserted}
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
