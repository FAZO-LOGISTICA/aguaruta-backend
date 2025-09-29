# main.py — Backend AguaRuta (versión nube con importador Excel)
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
import pandas as pd

# =============================================================================
# CONFIG / LOGGING
# =============================================================================
APP_NAME = "AguaRuta Backend"
BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "RUTA ACTIVA.xlsx"
FOTOS_DIR = BASE_DIR / "fotos" / "evidencias"
FOTOS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger(APP_NAME)

# =============================================================================
# DB POOL
# =============================================================================
DB_URL = os.getenv("DATABASE_URL") or os.getenv("DB_URL") or os.getenv("POSTGRES_URL")

if 'pool' not in globals():
    if not DB_URL:
        log.warning("No hay DATABASE_URL/DB_URL/POSTGRES_URL en entorno.")
        pool = None
    else:
        pool = SimpleConnectionPool(1, 10, dsn=DB_URL)
        log.info("Pool Postgres creado.")

def db_conn():
    if not pool:
        raise RuntimeError("Pool de DB no inicializado.")
    return pool.getconn()

def db_put(conn):
    if pool and conn:
        pool.putconn(conn)

# =============================================================================
# APP
# =============================================================================
try:
    app  # type: ignore
except NameError:
    app = FastAPI(title=APP_NAME)
    log.info("Instancia FastAPI creada.")

try:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[os.getenv("FRONTEND_ORIGIN", "https://aguaruta.netlify.app"), "*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
except Exception:
    pass

try:
    app.mount("/fotos", StaticFiles(directory=FOTOS_DIR, check_dir=False), name="fotos")
except Exception:
    pass

# =============================================================================
# MODELOS
# =============================================================================
class RutaActivaUpdate(BaseModel):
    camion: Optional[str] = None
    nombre: Optional[str] = None
    dia: Optional[str] = None
    telefono: Optional[str] = None
    litros: Optional[int] = None
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
    url_file = BASE_DIR / "url.txt"
    if not url_file.exists():
        return Response(status_code=204)
    try:
        return PlainTextResponse(url_file.read_text(encoding="utf-8").strip())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error leyendo url.txt: {e}")

# =============================================================================
# IMPORTAR RUTA ACTIVA DESDE EXCEL
# =============================================================================
@app.post("/importar-ruta-activa")
def importar_ruta_activa():
    """
    Carga el Excel 'RUTA ACTIVA.xlsx' en la tabla rutas_activas.
    """
    if not DATA_FILE.exists():
        raise HTTPException(status_code=404, detail="No se encontró RUTA ACTIVA.xlsx")

    try:
        df = pd.read_excel(DATA_FILE)

        # Normalizar columnas
        df.rename(columns={
            "ID CAMIÓN": "camion",
            "DIA": "dia_asignado",
            "LITROS DE ENTREGA": "litros_entrega",
        }, inplace=True)

        conn = db_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM rutas_activas")

        for _, row in df.iterrows():
            cur.execute("""
                INSERT INTO rutas_activas (camion, patente, conductor, dia_asignado, nombre, sector,
                                           litros_entrega, telefono, latitud, longitud)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                row.get("camion"),
                row.get("PATENTE"),
                row.get("CONDUCTOR"),
                row.get("dia_asignado"),
                row.get("NOMBRE"),
                row.get("SECTOR"),
                row.get("litros_entrega"),
                row.get("telefono"),
                row.get("latitud"),
                row.get("longitud"),
            ))

        conn.commit()
        cur.close()
        db_put(conn)
        return {"status": "ok", "rows_imported": len(df)}
    except Exception as e:
        log.error(f"Error importando Excel: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# RUTAS ACTIVAS (GET / PUT / DELETE)
# =============================================================================
@app.get("/rutas-activas")
def get_rutas_activas():
    try:
        conn = db_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, camion, patente, conductor, dia_asignado, nombre, sector,
                   litros_entrega, telefono, COALESCE(latitud,NULL), COALESCE(longitud,NULL)
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
    campos, valores = [], []
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
# ENTREGAS APP
# =============================================================================
@app.post("/entregas-app")
async def registrar_entrega_app(
    nombre: str = Form(...),
    camion: str = Form(...),
    litros: int = Form(...),
    estado: int = Form(...),
    fecha: str = Form(...),
    latitud: Optional[float] = Form(None),
    longitud: Optional[float] = Form(None),
    foto: Optional[UploadFile] = File(None),
):
    foto_path_rel = None
    if foto and foto.filename:
        ext = Path(foto.filename).suffix.lower() or ".jpg"
        fname = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex}{ext}"
        dest = FOTOS_DIR / fname
        with dest.open("wb") as f:
            shutil.copyfileobj(foto.file, f)
        foto_path_rel = f"/fotos/{fname}"

    try:
        conn = db_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO entregas_app (nombre, camion, litros, estado, fecha, latitud, longitud, foto_path)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """, (nombre, camion, litros, estado, fecha, latitud, longitud, foto_path_rel))
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        db_put(conn)
        return {"status": "ok", "id": new_id, "foto": foto_path_rel}
    except psycopg2.errors.UndefinedTable:
        try:
            conn = db_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO entregas (nombre, camion, litros, estado, fecha, latitud, longitud, foto_path)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
            """, (nombre, camion, litros, estado, fecha, latitud, longitud, foto_path_rel))
            new_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            db_put(conn)
            log.info("Fallback: tabla 'entregas' usada.")
            return {"status": "ok", "id": new_id, "foto": foto_path_rel}
        except Exception as e2:
            log.error(f"Fallback entregas error: {e2}")
            raise HTTPException(status_code=500, detail=str(e2))
    except Exception as e:
        log.error(f"POST /entregas-app error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
