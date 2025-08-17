# main.py
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, Any, List, Dict, Tuple, Iterator
from datetime import datetime
import os
import io
import shutil
import logging
import json
import ssl
from urllib.request import urlopen

import pandas as pd
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor, execute_values

# -----------------------------------------------------------------------------
# App & CORS
# -----------------------------------------------------------------------------
app = FastAPI(title="AguaRuta API", version="1.7")

ALLOWED_ORIGINS = [
    "https://aguaruta.netlify.app",  # Producción
    "http://localhost:3000",         # CRA local
    "http://localhost:5173",         # Vite local
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
log = logging.getLogger("aguaruta")
logging.basicConfig(level=logging.INFO)

# -----------------------------------------------------------------------------
# DB Pool (+ airbag)
# -----------------------------------------------------------------------------
DB_URL = os.getenv("DATABASE_URL") or os.getenv("DB_URL") or \
    "postgresql://aguaruta_db_user:u1JUg0dcbEYzzzoF8N4lsbdZ6c2ZXyPb@dpg-d25b5mripnbc73dpod0g-a.oregon-postgres.render.com:5432/aguaruta_db"

DB_URL = DB_URL.strip()
# Corrige nombre con guion
if "aguaruta-db" in DB_URL:
    DB_URL = DB_URL.replace("aguaruta-db", "aguaruta_db")
# Fuerza SSL
if "sslmode=" not in DB_URL:
    DB_URL += ("&" if "?" in DB_URL else "?") + "sslmode=require"

pool: Optional[SimpleConnectionPool] = None


def get_conn_cursor() -> Iterator[Tuple[psycopg2.extensions.connection, psycopg2.extensions.cursor]]:  # type: ignore[name-defined]
    class _Ctx:
        def __enter__(self):
            if pool is None:
                raise RuntimeError("DB pool no inicializado")
            self.conn = pool.getconn()
            self.cur = self.conn.cursor(cursor_factory=RealDictCursor)
            return self.conn, self.cur

        def __exit__(self, exc_type, exc, tb):
            try:
                self.cur.close()
                (self.conn.rollback() if exc else self.conn.commit())
            finally:
                pool.putconn(self.conn)
    return _Ctx()

# -----------------------------------------------------------------------------
# Fallback JSON para redistribución (solo lectura)
# -----------------------------------------------------------------------------
FALLBACK_JSON_URL = os.getenv(
    "REDIST_FALLBACK_URL",
    "https://aguaruta.netlify.app/datos/RutasMapaFinal_con_telefono.json",
)


def cargar_fallback_redistribucion(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Lee y normaliza el JSON público cuando la DB no tiene datos."""
    try:
        ctx = ssl.create_default_context()
        with urlopen(FALLBACK_JSON_URL, context=ctx, timeout=10) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        out: List[Dict[str, Any]] = []
        for i, r in enumerate(raw, start=1):
            lat = r.get("latitud") or r.get("lat") or r.get("latitude")
            lon = r.get("longitud") or r.get("lon") or r.get("lng") or r.get("longitude")
            if lat is None or lon is None:
                continue
            out.append({
                "id": r.get("id") or i,
                "camion": r.get("camion") or r.get("CAMION") or r.get("camion_asignado") or "Sin asignar",
                "nombre": r.get("nombre") or r.get("NOMBRE") or r.get("jefe_hogar") or r.get("jefe") or "Desconocido",
                "dia": r.get("dia_asignado") or r.get("dia") or r.get("DIA") or "N/D",
                "litros": r.get("litros") or r.get("LITROS") or r.get("litros_de_entrega") or 0,
                "telefono": r.get("telefono") or r.get("TELEFONO") or r.get("phone") or "N/D",
                "latitud": float(lat),
                "longitud": float(lon),
            })
            if limit and len(out) >= limit:
                break
        return out
    except Exception as e:
        log.warning("Fallback JSON de redistribución no disponible: %s", e)
        return []

# -----------------------------------------------------------------------------
# Helpers de DB para Redistribución / Entregas App
# -----------------------------------------------------------------------------
def ensure_table_redistribucion() -> None:
    """Crea la tabla de redistribución si no existe."""
    with get_conn_cursor() as (_, cur):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS redistribucion (
              id SERIAL PRIMARY KEY,
              camion    TEXT,
              nombre    TEXT,
              dia       TEXT,
              litros    DOUBLE PRECISION,
              telefono  TEXT,
              latitud   DOUBLE PRECISION,
              longitud  DOUBLE PRECISION
            );
        """)


def count_redistribucion() -> int:
    with get_conn_cursor() as (_, cur):
        cur.execute("SELECT COUNT(1) AS c FROM redistribucion;")
        row = cur.fetchone()
        return int(row["c"] if row and "c" in row else 0)


def seed_redistribucion_from_fallback(limit: Optional[int] = None) -> int:
    """Carga el fallback JSON a la DB si hay datos y devuelve cuántos insertó."""
    datos = cargar_fallback_redistribucion(limit=limit)
    if not datos:
        return 0
    norm = []
    for d in datos:
        norm.append((
            d.get("camion") or "Sin asignar",
            d.get("nombre") or "Desconocido",
            d.get("dia") or "N/D",
            float(d.get("litros") or 0),
            d.get("telefono") or "N/D",
            float(d["latitud"]),
            float(d["longitud"]),
        ))
    with get_conn_cursor() as (_, cur):
        cur.execute("SET LOCAL statement_timeout TO 3000;")
        execute_values(cur, """
            INSERT INTO redistribucion
            (camion, nombre, dia, litros, telefono, latitud, longitud)
            VALUES %s
        """, norm)
        return len(norm)


def ensure_table_entregas_app() -> None:
    """Evita el 500 de /entregas-app creando la tabla si faltaba."""
    with get_conn_cursor() as (_, cur):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS entregas_app (
              id SERIAL PRIMARY KEY,
              nombre   TEXT,
              camion   TEXT,
              litros   INTEGER,
              estado   INTEGER,
              fecha    TIMESTAMP,
              foto_url TEXT,
              latitud  DOUBLE PRECISION,
              longitud DOUBLE PRECISION
            );
        """)

# -----------------------------------------------------------------------------
# Eventos app
# -----------------------------------------------------------------------------
@app.on_event("startup")
def startup() -> None:
    global pool
    log.info("Inicializando pool de conexiones…")
    pool = SimpleConnectionPool(minconn=1, maxconn=8, dsn=DB_URL)

    # Asegura tablas y, si redistribución está vacía, siembra desde el JSON
    try:
        ensure_table_redistribucion()
        ensure_table_entregas_app()
        if count_redistribucion() == 0:
            ins = seed_redistribucion_from_fallback()
            log.info("Redistribución inicial cargada desde JSON: %s filas.", ins)
        else:
            log.info("Redistribución ya tiene datos en DB.")
    except Exception as e:
        log.warning("Boot DB incompleto: %s", e)


@app.on_event("shutdown")
def shutdown() -> None:
    global pool
    if pool:
        log.info("Cerrando pool de conexiones…")
        pool.closeall()

# -----------------------------------------------------------------------------
# Modelos
# -----------------------------------------------------------------------------
class EditarRutaPayload(BaseModel):
    id: Optional[int] = Field(None)
    camion: Optional[str] = None
    litros: Optional[float] = None
    dia: Optional[str] = None
    telefono: Optional[str] = None
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    nombre: Optional[str] = None
    nombre_lookup: Optional[str] = None


class EditarRedistribucionPayload(BaseModel):
    id: Optional[int] = Field(None)
    camion: Optional[str] = None
    litros: Optional[float] = None
    dia: Optional[str] = None
    telefono: Optional[str] = None
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    nombre: Optional[str] = None
    nombre_lookup: Optional[str] = None

# -----------------------------------------------------------------------------
# Endpoints básicos
# -----------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

# -----------------------------------------------------------------------------
# Rutas activas (DB)
# -----------------------------------------------------------------------------
@app.get("/rutas-activas")
def obtener_rutas_activas() -> List[Dict[str, Any]]:
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                SELECT id, camion, nombre, latitud, longitud, litros, dia, telefono
                FROM ruta_activa
                ORDER BY camion, dia, nombre
            """)
            return cur.fetchall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/editar-ruta")
def editar_ruta(payload: EditarRutaPayload):
    try:
        id_ruta = payload.id
        if id_ruta is None:
            if not payload.nombre_lookup:
                raise HTTPException(status_code=400, detail="Debes enviar 'id' o 'nombre_lookup'.")
            with get_conn_cursor() as (_, cur):
                cur.execute("SELECT id FROM ruta_activa WHERE nombre = %s", (payload.nombre_lookup,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="No se encontró el registro")
                id_ruta = row["id"]

        with get_conn_cursor() as (_, cur):
            cur.execute("""
                UPDATE ruta_activa SET
                    camion   = COALESCE(%s, camion),
                    litros   = COALESCE(%s, litros),
                    dia      = COALESCE(%s, dia),
                    telefono = COALESCE(%s, telefono),
                    latitud  = COALESCE(%s, latitud),
                    longitud = COALESCE(%s, longitud),
                    nombre   = COALESCE(%s, nombre)
                WHERE id = %s
                RETURNING id
            """, (
                payload.camion,
                payload.litros,
                payload.dia,
                payload.telefono,
                payload.latitud,
                payload.longitud,
                payload.nombre,
                id_ruta
            ))
            updated = cur.fetchone()
            if not updated:
                raise HTTPException(status_code=404, detail="No se actualizó ningún registro")
            return {"mensaje": "Ruta actualizada correctamente", "id": updated["id"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# Redistribución (DB -> JSON fallback)
# -----------------------------------------------------------------------------
@app.get("/redistribucion")
def obtener_redistribucion() -> List[Dict[str, Any]]:
    # 1) Intento DB rápido (máx 3s)
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("SET LOCAL statement_timeout TO 3000;")
            cur.execute("""
                SELECT id, camion, nombre, dia, litros, telefono, latitud, longitud
                FROM redistribucion
                ORDER BY camion, dia, nombre
            """)
            filas = cur.fetchall()
        if filas:
            return filas
    except Exception as e:
        log.warning("DB error en /redistribucion, probando fallback JSON: %s", e)

    # 2) Fallback JSON (solo lectura si DB vacía o falla)
    datos = cargar_fallback_redistribucion()
    if datos:
        log.info("Usando fallback JSON para /redistribucion (%s registros).", len(datos))
    return datos


@app.get("/redistribucion/source")
def redistribucion_source():
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("SELECT 1 FROM redistribucion LIMIT 1;")
            if cur.fetchone():
                return {"source": "db"}
    except Exception:
        pass
    return {"source": "json"}


@app.put("/editar-redistribucion")
def editar_redistribucion(payload: EditarRedistribucionPayload):
    try:
        id_redist = payload.id
        if id_redist is None:
            if not payload.nombre_lookup:
                raise HTTPException(status_code=400, detail="Debes enviar 'id' o 'nombre_lookup'.")
            with get_conn_cursor() as (_, cur):
                cur.execute("SELECT id FROM redistribucion WHERE nombre = %s", (payload.nombre_lookup,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="No se encontró el registro")
                id_redist = row["id"]

        with get_conn_cursor() as (_, cur):
            cur.execute("""
                UPDATE redistribucion SET
                    camion   = COALESCE(%s, camion),
                    litros   = COALESCE(%s, litros),
                    dia      = COALESCE(%s, dia),
                    telefono = COALESCE(%s, telefono),
                    latitud  = COALESCE(%s, latitud),
                    longitud = COALESCE(%s, longitud),
                    nombre   = COALESCE(%s, nombre)
                WHERE id = %s
                RETURNING id
            """, (
                payload.camion,
                payload.litros,
                payload.dia,
                payload.telefono,
                payload.latitud,
                payload.longitud,
                payload.nombre,
                id_redist
            ))
            updated = cur.fetchone()
            if not updated:
                raise HTTPException(status_code=404, detail="No se actualizó ningún registro")
            return {"mensaje": "Redistribución actualizada correctamente", "id": updated["id"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# Admin: bootstrap manual (opcional)
# -----------------------------------------------------------------------------
@app.post("/admin/bootstrap-redistribucion")
def admin_bootstrap_redistribucion(limit: Optional[int] = None):
    ensure_table_redistribucion()
    if count_redistribucion() > 0:
        return {"ok": True, "msg": "La tabla ya tiene datos; no se insertó nada."}
    inserted = seed_redistribucion_from_fallback(limit=limit)
    return {"ok": True, "insertados": inserted}

# -----------------------------------------------------------------------------
# Exportar Excel (rutas activas)
# -----------------------------------------------------------------------------
@app.get("/exportar-excel")
def exportar_excel():
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                SELECT camion, nombre, latitud, longitud, litros, dia, telefono
                FROM ruta_activa
                ORDER BY camion, dia, nombre
            """)
            filas = cur.fetchall()
        if not filas:
            raise HTTPException(status_code=404, detail="No hay datos para exportar")

        df = pd.DataFrame(filas)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Rutas")
        output.seek(0)

        filename = f"rutas_activas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        headers = {'Content-Disposition': f'attachment; filename="{filename}"'}
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# Limpiezas rápidas (DB)
# -----------------------------------------------------------------------------
@app.get("/eliminar-ficticio")
def eliminar_ficticio():
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                DELETE FROM ruta_activa
                WHERE nombre = 'Juan Pérez' OR telefono = '123456789'
            """)
            count = cur.rowcount
        return {"mensaje": "Ficticios eliminados", "eliminados": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/eliminar-nulos")
def eliminar_nulos():
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                DELETE FROM ruta_activa
                WHERE camion IS NULL AND nombre IS NULL AND
                      latitud IS NULL AND longitud IS NULL AND
                      litros IS NULL AND dia IS NULL AND telefono IS NULL
            """)
            count = cur.rowcount
        return {"mensaje": "Nulos eliminados", "eliminados": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# Entregas App
# -----------------------------------------------------------------------------
@app.get("/entregas-app")
def obtener_entregas_app():
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                SELECT
                    nombre, camion, litros, estado, fecha, foto_url, latitud, longitud
                FROM entregas_app
                ORDER BY fecha DESC
            """)
            return cur.fetchall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/entregas-app")
def registrar_entrega_app(
    nombre: str = Form(...),
    camion: str = Form(...),
    litros: int = Form(...),
    estado: int = Form(...),
    fecha: str = Form(...),
    latitud: float = Form(...),
    longitud: float = Form(...),
    foto: Optional[UploadFile] = File(None),
):
    try:
        foto_url = None
        if foto:
            carpeta = "uploads/entregas"
            os.makedirs(carpeta, exist_ok=True)
            nombre_archivo = f"{fecha}_{nombre.replace(' ', '_')}_{camion}.jpg"
            ruta_archivo = os.path.join(carpeta, nombre_archivo)
            with open(ruta_archivo, "wb") as buffer:
                shutil.copyfileobj(foto.file, buffer)
            foto_url = ruta_archivo

        with get_conn_cursor() as (_, cur):
            cur.execute("""
                INSERT INTO entregas_app (nombre, camion, litros, estado, fecha, foto_url, latitud, longitud)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (nombre, camion, litros, estado, fecha, foto_url, latitud, longitud))

        return {"mensaje": "Entrega registrada correctamente"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# Routers externos opcionales
# -----------------------------------------------------------------------------
try:
    from routers.redistribucion import router as nueva_redis_router  # prefix="/nueva-distribucion"
    app.include_router(nueva_redis_router)
    log.info("Router '/nueva-distribucion' cargado")
except Exception as e:
    log.warning("No se pudo cargar router /nueva-distribucion: %s", e)

try:
    # Actívalo solo si existe ese archivo/paquete
    if os.getenv("ENABLE_RUTAS_ACTIVAS_EXCEL") == "1":
        from routers.rutas_activas_excel import router as rutas_excel_router  # prefix="/rutas-activas-excel"
        app.include_router(rutas_excel_router)
        log.info("Router '/rutas-activas-excel' cargado")
except Exception as e:
    log.warning("No se pudo cargar router /rutas-activas-excel: %s", e)
