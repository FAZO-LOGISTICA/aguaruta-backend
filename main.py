# main.py
# AguaRuta Backend + Auditoría de cambios en ruta_activa

import os
import uuid
import math
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import psycopg2
from psycopg2.pool import SimpleConnectionPool

# -----------------------------------------------------------------------------
APP_NAME = "AguaRuta Backend"
BASE_DIR = Path(__file__).resolve().parent
FOTOS_DIR = BASE_DIR / "fotos" / "evidencias"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("aguaruta")

DB_URL = os.getenv("DATABASE_URL") or os.getenv("DB_URL") or os.getenv("POSTGRES_URL")
if DB_URL and "sslmode=" not in DB_URL:
    DB_URL += ("&" if "?" in DB_URL else "?") + "sslmode=require"
if not DB_URL:
    log.warning("⚠️ Falta DATABASE_URL/DB_URL/POSTGRES_URL")

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

# -----------------------------------------------------------------------------
# App / CORS / estáticos
app = FastAPI(title=APP_NAME)
allow_origins = [
    os.getenv("FRONTEND_ORIGIN", "https://aguaruta.netlify.app"),
    "http://localhost", "http://localhost:3000", "http://localhost:5173",
]
app.add_middleware(CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
FOTOS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/fotos", StaticFiles(directory=str(BASE_DIR / "fotos")), name="fotos")

# -----------------------------------------------------------------------------
# Salud / descubrimiento
@app.get("/", response_class=PlainTextResponse)
def root(): return f"{APP_NAME} OK"

@app.head("/", include_in_schema=False)
def head_root(): return PlainTextResponse("")

@app.get("/health")
def health():
    try:
        if DB_URL:
            conn = get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            finally:
                put_conn(conn)
        return {"ok": True}
    except Exception as e:
        log.exception("Health failed")
        return {"ok": False, "error": str(e)}

@app.get("/url.txt", response_class=PlainTextResponse)
def url_txt():
    p = BASE_DIR / "url.txt"
    if not p.exists(): raise HTTPException(404, "url.txt no existe")
    return p.read_text(encoding="utf-8").strip()

# -----------------------------------------------------------------------------
# Utils
def to_float(v): 
    try: return float(str(v).replace(",", ".").strip())
    except: return None

def to_int(v):
    f = to_float(v)
    return int(round(f)) if f is not None else None

def dictfetchall(cur) -> List[Dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlmb/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def req_user_meta(request: Request):
    user = request.headers.get("X-User") or "anon"
    ip = (request.client.host if request.client else "") or request.headers.get("X-Forwarded-For", "")
    ua = request.headers.get("User-Agent", "")
    return user, ip, ua

# -----------------------------------------------------------------------------
# Auditoría: tabla + trigger (OLD/NEW JSONB + usuario, ip, ua)
def ensure_audit(conn):
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS public.audit_ruta_activa (
            id BIGSERIAL PRIMARY KEY,
            ruta_id INTEGER,
            accion TEXT,           -- INSERT / UPDATE / DELETE
            antes JSONB,
            despues JSONB,
            usuario TEXT,
            ip TEXT,
            user_agent TEXT,
            ts TIMESTAMP DEFAULT now()
        );
        """)
        # función del trigger
        cur.execute("""
        CREATE OR REPLACE FUNCTION public.trg_fn_ruta_activa_audit()
        RETURNS trigger AS $$
        DECLARE
            v_user TEXT := current_setting('app.user', true);
            v_ip   TEXT := current_setting('app.ip',   true);
            v_ua   TEXT := current_setting('app.ua',   true);
        BEGIN
            IF TG_OP = 'INSERT' THEN
                INSERT INTO public.audit_ruta_activa(ruta_id, accion, antes, despues, usuario, ip, user_agent)
                VALUES (NEW.id, 'INSERT', NULL, to_jsonb(NEW), v_user, v_ip, v_ua);
                RETURN NEW;
            ELSIF TG_OP = 'UPDATE' THEN
                INSERT INTO public.audit_ruta_activa(ruta_id, accion, antes, despues, usuario, ip, user_agent)
                VALUES (NEW.id, 'UPDATE', to_jsonb(OLD), to_jsonb(NEW), v_user, v_ip, v_ua);
                RETURN NEW;
            ELSIF TG_OP = 'DELETE' THEN
                INSERT INTO public.audit_ruta_activa(ruta_id, accion, antes, despues, usuario, ip, user_agent)
                VALUES (OLD.id, 'DELETE', to_jsonb(OLD), NULL, v_user, v_ip, v_ua);
                RETURN OLD;
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """)
        # crea trigger si no existe
        cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_trigger WHERE tgname = 'trg_ruta_activa_audit'
            ) THEN
                CREATE TRIGGER trg_ruta_activa_audit
                AFTER INSERT OR UPDATE OR DELETE ON public.ruta_activa
                FOR EACH ROW EXECUTE FUNCTION public.trg_fn_ruta_activa_audit();
            END IF;
        END $$;
        """)
    conn.commit()

# endpoint para ver auditoría (últimos N o por ruta_id)
@app.get("/auditoria/rutas-activas")
def audit_list(limit: int = 200, ruta_id: Optional[int] = None):
    if pool is None: raise HTTPException(503, "DB no configurada")
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if ruta_id:
                cur.execute("""
                    SELECT id, ruta_id, accion, antes, despues, usuario, ip, user_agent, ts
                    FROM public.audit_ruta_activa
                    WHERE ruta_id = %s
                    ORDER BY id DESC
                    LIMIT %s
                """, (ruta_id, limit))
            else:
                cur.execute("""
                    SELECT id, ruta_id, accion, antes, despues, usuario, ip, user_agent, ts
                    FROM public.audit_ruta_activa
                    ORDER BY id DESC
                    LIMIT %s
                """, (limit,))
            return dictfetchall(cur)
    finally:
        put_conn(conn)

# -----------------------------------------------------------------------------
# Modelos
class RutaUpdate(BaseModel):
    camion: Optional[str] = None
    nombre: Optional[str] = None
    dia: Optional[str] = None
    litros: Optional[int] = Field(default=None)
    telefono: Optional[str] = None
    latitud: Optional[float] = None
    longitud: Optional[float] = None

class NuevoPunto(BaseModel):
    nombre: str
    litros: int
    telefono: Optional[str] = None
    latitud: float
    longitud: float
    dia: Optional[str] = None
    camion_override: Optional[str] = None

# -----------------------------------------------------------------------------
# CRUD ruta_activa
@app.get("/rutas-activas")
def rutas_activas():
    if pool is None: raise HTTPException(503, "DB no configurada")
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, camion, nombre, dia, litros, telefono, latitud, longitud
                FROM public.ruta_activa
                ORDER BY camion, nombre
            """)
            return dictfetchall(cur)
    finally:
        put_conn(conn)

@app.put("/rutas-activas/{id}")
def rutas_activas_update(id: int, payload: RutaUpdate, request: Request):
    if pool is None: raise HTTPException(503, "DB no configurada")
    campos, valores = [], []
    if payload.camion is not None:   campos += ["camion=%s"];   valores += [payload.camion.strip() or None]
    if payload.nombre is not None:   campos += ["nombre=%s"];   valores += [payload.nombre.strip() or None]
    if payload.dia is not None:      campos += ["dia=%s"];      valores += [payload.dia.strip() or None]
    if payload.litros is not None:   campos += ["litros=%s"];   valores += [int(payload.litros)]
    if payload.telefono is not None: campos += ["telefono=%s"]; valores += [payload.telefono.strip() or None]
    if payload.latitud is not None:  campos += ["latitud=%s"];  valores += [to_float(payload.latitud)]
    if payload.longitud is not None: campos += ["longitud=%s"]; valores += [to_float(payload.longitud)]
    if not campos: return {"ok": True, "updated": 0}

    user, ip, ua = req_user_meta(request)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL app.user=%s", (user,))
            cur.execute("SET LOCAL app.ip=%s", (ip,))
            cur.execute("SET LOCAL app.ua=%s", (ua,))
            cur.execute(f"UPDATE public.ruta_activa SET {', '.join(campos)} WHERE id=%s", valores + [id])
        conn.commit()
        return {"ok": True, "updated": 1}
    finally:
        put_conn(conn)

@app.delete("/rutas-activas/{id}")
def rutas_activas_delete(id: int, request: Request):
    if pool is None: raise HTTPException(503, "DB no configurada")
    user, ip, ua = req_user_meta(request)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL app.user=%s", (user,))
            cur.execute("SET LOCAL app.ip=%s", (ip,))
            cur.execute("SET LOCAL app.ua=%s", (ua,))
            cur.execute("DELETE FROM public.ruta_activa WHERE id=%s", (id,))
            if cur.rowcount == 0:
                raise HTTPException(404, "Registro no encontrado")
        conn.commit()
        return {"ok": True, "deleted": 1}
    finally:
        put_conn(conn)

# -----------------------------------------------------------------------------
# Registrar nuevo punto (auto-assign por vecino / override camión)
@app.post("/registrar-nuevo-punto-auto")
def registrar_nuevo_punto_auto(data: NuevoPunto, request: Request):
    if pool is None: raise HTTPException(503, "DB no configurada")
    nombre = (data.nombre or "").strip()
    if not nombre: raise HTTPException(400, "Nombre obligatorio")
    litros = int(data.litros)
    lat, lon = float(data.latitud), float(data.longitud)
    telefono = (data.telefono or "").strip() or None

    asign_camion = (data.camion_override or "").strip().upper() or None
    asign_dia = (data.dia or "").strip().upper() or None
    vecino_id = None

    user, ip, ua = req_user_meta(request)
    conn = get_conn()
    try:
        if not asign_camion:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, camion, dia, latitud, longitud
                    FROM public.ruta_activa
                    WHERE latitud IS NOT NULL AND longitud IS NOT NULL
                """)
                vecinos = dictfetchall(cur)
            best, best_d = None, 1e12
            for v in vecinos:
                try:
                    d = haversine_km(lat, lon, float(v["latitud"]), float(v["longitud"]))
                    if d < best_d: best, best_d = v, d
                except: pass
            if best:
                vecino_id = best["id"]
                asign_camion = (best.get("camion") or "A1").strip()
                asign_dia = asign_dia or (best.get("dia") or None)
        if not asign_camion: asign_camion = "A1"

        with conn.cursor() as cur:
            cur.execute("SET LOCAL app.user=%s", (user,))
            cur.execute("SET LOCAL app.ip=%s", (ip,))
            cur.execute("SET LOCAL app.ua=%s", (ua,))
            cur.execute("""
                INSERT INTO public.ruta_activa (camion, nombre, dia, litros, telefono, latitud, longitud)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
            """, (asign_camion, nombre, asign_dia, litros, telefono, lat, lon))
            new_id = cur.fetchone()[0]
        conn.commit()
        return {"ok": True, "id": new_id, "asignacion": {"camion": asign_camion, "dia": asign_dia}, "vecino_id": vecino_id}
    finally:
        put_conn(conn)

# -----------------------------------------------------------------------------
# Camiones (opcional para picker)
class CamionUpsert(BaseModel):
    codigo: str
    nombre: Optional[str] = None
    capacidad_litros: Optional[int] = None
    activo: Optional[bool] = True

def ensure_table_camiones(conn):
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS public.camiones (
            codigo TEXT PRIMARY KEY,
            nombre TEXT,
            capacidad_litros INTEGER,
            activo BOOLEAN DEFAULT TRUE
        )
        """)
    conn.commit()

@app.get("/camiones")
def camiones_list(only_active: bool = True):
    if pool is None: raise HTTPException(503, "DB no configurada")
    conn = get_conn()
    try:
        ensure_table_camiones(conn)
        with conn.cursor() as cur:
            if only_active:
                cur.execute("SELECT codigo, nombre, capacidad_litros, activo FROM public.camiones WHERE activo=true")
            else:
                cur.execute("SELECT codigo, nombre, capacidad_litros, activo FROM public.camiones")
            return dictfetchall(cur)
    finally:
        put_conn(conn)

@app.post("/camiones")
def camiones_upsert(payload: CamionUpsert, request: Request):
    if pool is None: raise HTTPException(503, "DB no configurada")
    codigo = (payload.codigo or "").strip().upper()
    if not codigo: raise HTTPException(400, "Código inválido")
    user, ip, ua = req_user_meta(request)
    conn = get_conn()
    try:
        ensure_table_camiones(conn)
        with conn.cursor() as cur:
            cur.execute("SET LOCAL app.user=%s", (user,))
            cur.execute("SET LOCAL app.ip=%s", (ip,))
            cur.execute("SET LOCAL app.ua=%s", (ua,))
            cur.execute("""
                INSERT INTO public.camiones (codigo, nombre, capacidad_litros, activo)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (codigo)
                DO UPDATE SET nombre=EXCLUDED.nombre, capacidad_litros=EXCLUDED.capacidad_litros, activo=EXCLUDED.activo
            """, (codigo, payload.nombre, payload.capacidad_litros, payload.activo))
        conn.commit()
        return {"ok": True, "codigo": codigo}
    finally:
        put_conn(conn)

# -----------------------------------------------------------------------------
# Entregas con evidencia
def ensure_table_entregas_app(conn):
    with conn.cursor() as cur:
        cur.execute("""
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
        )
        """)
    conn.commit()

@app.post("/entregas-app")
async def entregas_app(
    request: Request,
    nombre: str = Form(...),
    camion: str = Form(...),
    litros: str = Form(...),
    estado: int = Form(...),
    fecha: str = Form(...),
    lat: Optional[float] = Form(None),
    lon: Optional[float] = Form(None),
    foto: Optional[UploadFile] = File(None),
):
    if pool is None: raise HTTPException(503, "DB no configurada")
    try: litros_int = int(float(litros))
    except: litros_int = None

    try:
        dt = datetime.strptime(fecha, "%Y-%m-%d") if len(fecha)<=10 else datetime.fromisoformat(fecha.replace("Z","+00:00"))
    except: dt = datetime.utcnow()

    foto_rel = None
    if foto is not None:
        if not str(foto.content_type).lower().startswith("image/"):
            raise HTTPException(400, "Archivo de foto inválido")
        y, m = dt.year, f"{dt.month:02d}"
        destino = FOTOS_DIR / str(y) / m
        destino.mkdir(parents=True, exist_ok=True)
        fname = f"evidencia_{uuid.uuid4().hex}.jpg"
        with open(destino / fname, "wb") as out:
            shutil.copyfileobj(foto.file, out)
        foto_rel = f"/fotos/evidencias/{y}/{m}/{fname}"

    user, ip, ua = req_user_meta(request)
    conn = get_conn()
    try:
        ensure_table_entregas_app(conn)
        with conn.cursor() as cur:
            cur.execute("SET LOCAL app.user=%s", (user,))
            cur.execute("SET LOCAL app.ip=%s", (ip,))
            cur.execute("SET LOCAL app.ua=%s", (ua,))
            rec_id = str(uuid.uuid4())
            cur.execute("""
                INSERT INTO public.entregas_app (id, nombre, camion, litros, estado, fecha, lat, lon, foto_ruta)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (rec_id, nombre, camion, litros_int, estado, dt, lat, lon, foto_rel))
        conn.commit()
        return {"ok": True, "id": rec_id, "foto_url": foto_rel}
    finally:
        put_conn(conn)

# -----------------------------------------------------------------------------
# Startup/Shutdown
@app.on_event("startup")
def on_startup():
    try:
        init_pool()
        if pool:
            conn = get_conn()
            try:
                ensure_audit(conn)   # << activa auditoría en arranque
            finally:
                put_conn(conn)
    except Exception as e:
        log.warning(f"No se pudo inicializar: {e}")
    log.info("Aplicación iniciada.")

@app.on_event("shutdown")
def on_shutdown():
    try:
        if pool: pool.closeall()
    except: pass
