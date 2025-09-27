# main.py — Backend AguaRuta (conservador: no rompe lo existente)
import os
import uuid
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import psycopg2
from psycopg2.pool import SimpleConnectionPool

# =============================================================================
# CONFIG / LOGGING
# =============================================================================
APP_NAME = "AguaRuta Backend"
BASE_DIR = Path(__file__).resolve().parent
FOTOS_DIR = BASE_DIR / "fotos" / "evidencias"
FOTOS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger(APP_NAME)

# =============================================================================
# DB POOL (reutiliza si ya existe)
# =============================================================================
DB_URL = os.getenv("DATABASE_URL") or os.getenv("DB_URL") or os.getenv("POSTGRES_URL")

if 'pool' not in globals():
    if not DB_URL:
        log.warning("No hay DATABASE_URL/DB_URL/POSTGRES_URL en entorno. Se asume pool existente o endpoints que no usan DB.")
        pool = None
    else:
        pool = SimpleConnectionPool(1, 10, dsn=DB_URL)
        log.info("Pool Postgres creado.")

# Helper DB
def db_conn():
    if not pool:
        raise RuntimeError("Pool de DB no inicializado.")
    return pool.getconn()

def db_put(conn):
    if pool and conn:
        pool.putconn(conn)

# =============================================================================
# APP (reutiliza si ya existe)
# =============================================================================
try:
    app  # type: ignore
except NameError:
    app = FastAPI(title=APP_NAME)
    log.info("Instancia FastAPI creada.")

# CORS (idempotente: no falla si se aplica dos veces)
try:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            os.getenv("FRONTEND_ORIGIN", "https://aguaruta.netlify.app"),
            "*",  # respaldo
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
except Exception as _e:
    log.warning("No se pudo aplicar CORS (posible middleware duplicado). Continuando...")

# Static de evidencias (idempotente)
try:
    app.mount("/fotos", StaticFiles(directory=FOTOS_DIR, check_dir=False), name="fotos")
except Exception:
    # Si ya estaba montado, ignorar
    pass

# =============================================================================
# MODELOS
# =============================================================================
class RutaActivaUpdate(BaseModel):
    camion: Optional[str] = None
    nombre: Optional[str] = None
    dia: Optional[str] = None            # mapea a dia_asignado
    telefono: Optional[str] = None
    litros: Optional[int] = None         # mapea a litros_entrega
    latitud: Optional[float] = None
    longitud: Optional[float] = None

# =============================================================================
# ENDPOINTS BASE
# =============================================================================
@app.get("/health", response_class=PlainTextResponse)
def health():
    return "ok"

@app.get("/url", response_class=PlainTextResponse)
def leer_url_actual():
    """
    Devuelve el contenido de url.txt (útil para exponer la URL dinámica de ngrok/render a la app móvil).
    """
    url_file = BASE_DIR / "url.txt"
    if not url_file.exists():
        return Response(status_code=204)
    try:
        return PlainTextResponse(url_file.read_text(encoding="utf-8").strip())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error leyendo url.txt: {e}")

# =============================================================================
# RUTAS ACTIVAS (GET / PUT / DELETE) — Conserva nombres de columnas existentes
# =============================================================================
@app.get("/rutas-activas")
def get_rutas_activas():
    """
    Devuelve rutas activas con columnas usadas por el frontend histórico.
    """
    try:
        conn = db_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, camion, patente, conductor, dia_asignado, nombre, sector,
                   litros_entrega, telefono, COALESCE(latitud, NULL), COALESCE(longitud, NULL)
            FROM rutas_activas
            ORDER BY camion, dia_asignado, nombre
        """)
        rows = cur.fetchall()
        cur.close()
        db_put(conn)

        cols = ["id","camion","patente","conductor","dia_asignado","nombre","sector",
                "litros_entrega","telefono","latitud","longitud"]
        data = [dict(zip(cols, r)) for r in rows]
        return {"status": "ok", "data": data}
    except Exception as e:
        log.error(f"/rutas-activas error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/rutas-activas/{id}")
def update_ruta_activa(id: int, payload: RutaActivaUpdate):
    """
    Actualiza columnas puntuales respetando nombres reales en DB.
    - dia -> dia_asignado
    - litros -> litros_entrega
    """
    campos = []
    valores = []

    body = payload.dict(exclude_unset=True)
    for k, v in body.items():
        if k == "dia":
            campos.append("dia_asignado = %s"); valores.append(v)
        elif k == "litros":
            campos.append("litros_entrega = %s"); valores.append(v)
        else:
            campos.append(f"{k} = %s"); valores.append(v)

    if not campos:
        raise HTTPException(status_code=400, detail="No hay campos para actualizar.")

    valores.append(id)
    q = f"UPDATE rutas_activas SET {', '.join(campos)} WHERE id = %s"

    try:
        conn = db_conn()
        cur = conn.cursor()
        cur.execute(q, valores)
        conn.commit()
        cur.close()
        db_put(conn)
        return {"status": "ok", "updated_id": id}
    except Exception as e:
        log.error(f"PUT /rutas-activas/{id} error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/rutas-activas/{id}")
def delete_ruta_activa(id: int):
    try:
        conn = db_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM rutas_activas WHERE id = %s", (id,))
        conn.commit()
        cur.close()
        db_put(conn)
        return {"status": "ok", "deleted_id": id}
    except Exception as e:
        log.error(f"DELETE /rutas-activas/{id} error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# ENTREGAS APP (POST) — Mantiene compatibilidad: foto opcional + GPS
# =============================================================================
@app.post("/entregas-app")
async def registrar_entrega_app(
    nombre: str = Form(...),
    camion: str = Form(...),
    litros: int = Form(...),
    estado: int = Form(...),                 # 1=entregada, 0/2/3=no entregada (según tu codificación)
    fecha: str = Form(...),                  # "YYYY-MM-DD" o ISO8601
    latitud: Optional[float] = Form(None),
    longitud: Optional[float] = Form(None),
    foto: Optional[UploadFile] = File(None),
):
    """
    Guarda una entrega (con o sin foto). Si hay foto, se almacena en /fotos/evidencias
    y se persiste la ruta en la DB. Reutiliza esquema existente si ya lo tenías.
    """
    foto_path_rel = None

    # Guardado de foto (opcional)
    if foto and foto.filename:
        ext = Path(foto.filename).suffix.lower() or ".jpg"
        fname = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex}{ext}"
        dest = FOTOS_DIR / fname
        with dest.open("wb") as f:
            shutil.copyfileobj(foto.file, f)
        foto_path_rel = f"/fotos/{fname}"

    # Inserción en DB — ajusta al nombre de tu tabla real si difiere
    try:
        conn = db_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO entregas_app (nombre, camion, litros, estado, fecha, latitud, longitud, foto_path)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (nombre, camion, litros, estado, fecha, latitud, longitud, foto_path_rel))
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        db_put(conn)
        return {"status": "ok", "id": new_id, "foto": foto_path_rel}
    except psycopg2.errors.UndefinedTable:
        # Si tu tabla se llama distinto (p.ej. "entregas"), intenta fallback conservador
        try:
            conn = db_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO entregas (nombre, camion, litros, estado, fecha, latitud, longitud, foto_path)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (nombre, camion, litros, estado, fecha, latitud, longitud, foto_path_rel))
            new_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            db_put(conn)
            log.info("Fallback: se usó tabla 'entregas' en vez de 'entregas_app'.")
            return {"status": "ok", "id": new_id, "foto": foto_path_rel}
        except Exception as e2:
            log.error(f"POST /entregas-app fallback error: {e2}")
            raise HTTPException(status_code=500, detail=str(e2))
    except Exception as e:
        log.error(f"POST /entregas-app error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
