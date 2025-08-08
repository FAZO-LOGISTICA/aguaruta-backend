from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, Any, List, Dict
import os
import io
from datetime import datetime

import pandas as pd
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor

app = FastAPI(title="AguaRuta API", version="1.2")

# ---------------- CORS ----------------
ALLOWED_ORIGINS = [
    "https://aguaruta.netlify.app",  # frontend producción
    "http://localhost:5173",         # dev Vite (si usas)
    "http://localhost:3000",         # dev CRA (si usas)
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    max_age=3600,
)

# ---------------- DB ----------------
DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://aguaruta_db_user:u1JUg0dcbEYzzzoF8N4lsbdZ6c2ZXyPb@dpg-d25b5mripnbc73dpod0g-a.oregon-postgres.render.com/aguaruta_db",
)

pool: Optional[SimpleConnectionPool] = None

@app.on_event("startup")
def startup():
    global pool
    pool = SimpleConnectionPool(minconn=1, maxconn=8, dsn=DB_URL)

@app.on_event("shutdown")
def shutdown():
    global pool
    if pool:
        pool.closeall()

def get_conn_cursor():
    class _Ctx:
        def __enter__(self):
            self.conn = pool.getconn()
            self.cur = self.conn.cursor(cursor_factory=RealDictCursor)
            return self.conn, self.cur
        def __exit__(self, exc_type, exc, tb):
            try:
                self.cur.close()
                if exc:
                    self.conn.rollback()
                else:
                    self.conn.commit()
            finally:
                pool.putconn(self.conn)
    return _Ctx()

# ---------------- MODELOS ----------------
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

# ---------------- ENDPOINTS ----------------

@app.get("/health")
def health():
    return {"status": "ok"}

# ---------- RUTAS ACTIVAS ----------
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
async def editar_ruta(payload: EditarRutaPayload):
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------- REDISTRIBUCIÓN ----------
@app.get("/redistribucion")
def obtener_redistribucion() -> List[Dict[str, Any]]:
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                SELECT id, camion, nombre, dia, litros, telefono, latitud, longitud
                FROM redistribucion
                ORDER BY camion, dia, nombre
            """)
            return cur.fetchall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/editar-redistribucion")
async def editar_redistribucion(payload: EditarRedistribucionPayload):
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------- EXPORTAR EXCEL ----------
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

# ---------- LIMPIEZA ----------
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

# ---------- NUEVO: ENTREGAS APP ----------
@app.get("/entregas-app")
def obtener_entregas_app():
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                SELECT
                    nombre,
                    camion,
                    litros,
                    estado,
                    fecha,
                    foto_url,
                    latitud,
                    longitud
                FROM entregas_app
                ORDER BY fecha DESC
            """)
            return cur.fetchall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
