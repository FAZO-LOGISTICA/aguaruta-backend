from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, Any, List, Dict
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor
import pandas as pd
import io
import os
from datetime import datetime

app = FastAPI(title="AguaRuta API", version="1.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ajusta en prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Config DB ---
DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://aguaruta_db_user:u1JUg0dcbEYzzzoF8N4lsbdZ6c2ZXyPb@dpg-d25b5mripnbc73dpod0g-a.oregon-postgres.render.com/aguaruta_db"
)

pool: Optional[SimpleConnectionPool] = None

@app.on_event("startup")
def on_startup():
    global pool
    pool = SimpleConnectionPool(minconn=1, maxconn=8, dsn=DB_URL)

@app.on_event("shutdown")
def on_shutdown():
    global pool
    if pool:
        pool.closeall()

def get_conn_cursor():
    """Context manager para obtener conexión + cursor dict."""
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

# --------- MODELOS ---------

class EditarRutaPayload(BaseModel):
    # Recomiendo SIEMPRE enviar id para editar de forma segura:
    id: Optional[int] = Field(None, description="ID del registro en ruta_activa")
    # Campos editables (se actualizan solo si vienen):
    camion: Optional[str] = None
    litros: Optional[float] = None
    dia: Optional[str] = None
    telefono: Optional[str] = None
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    # Para compat: si no mandas id, intenta por nombre (no recomendado)
    nombre: Optional[str] = None

class EditarRedistribucionPayload(BaseModel):
    id: Optional[int] = Field(None, description="ID del registro en redistribucion")
    camion: Optional[str] = None
    litros: Optional[float] = None
    dia: Optional[str] = None
    telefono: Optional[str] = None
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    # Compat: permitir nombre si aún lo usas (no recomendado)
    nombre: Optional[str] = None

# --------- ENDPOINTS ---------

@app.get("/health")
def health():
    return {"status": "ok"}

# RUTAS ACTIVAS
@app.get("/rutas-activas")
def obtener_rutas_activas() -> List[Dict[str, Any]]:
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                SELECT id, camion, nombre, latitud, longitud, litros, dia, telefono
                FROM ruta_activa
                ORDER BY camion, dia, nombre
            """)
            filas = cur.fetchall()
            return filas
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/editar-ruta")
async def editar_ruta(payload: EditarRutaPayload):
    try:
        # 1) Resolver ID de forma segura
        id_ruta = payload.id
        if id_ruta is None:
            # Compat: intentar por nombre (no recomendado)
            if not payload.nombre:
                raise HTTPException(status_code=400, detail="Debes enviar 'id' o 'nombre'. Se recomienda 'id'.")
            with get_conn_cursor() as (_, cur):
                cur.execute("SELECT id FROM ruta_activa WHERE nombre = %s", (payload.nombre,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="No se encontró el registro por nombre")
                id_ruta = row["id"]

        # 2) Actualización parcial con COALESCE
        with get_conn_cursor() as (conn, cur):
            cur.execute("""
                UPDATE ruta_activa SET
                    camion   = COALESCE(%s, camion),
                    litros   = COALESCE(%s, litros),
                    dia      = COALESCE(%s, dia),
                    telefono = COALESCE(%s, telefono),
                    latitud  = COALESCE(%s, latitud),
                    longitud = COALESCE(%s, longitud)
                WHERE id = %s
                RETURNING id
            """, (
                payload.camion,
                payload.litros,
                payload.dia,
                payload.telefono,
                payload.latitud,
                payload.longitud,
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

# REDISTRIBUCIÓN
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
            if not payload.nombre:
                raise HTTPException(status_code=400, detail="Debes enviar 'id' o 'nombre'. Se recomienda 'id'.")
            with get_conn_cursor() as (_, cur):
                cur.execute("SELECT id FROM redistribucion WHERE nombre = %s", (payload.nombre,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="No se encontró el registro por nombre")
                id_redist = row["id"]

        with get_conn_cursor() as (_, cur):
            cur.execute("""
                UPDATE redistribucion SET
                    camion   = COALESCE(%s, camion),
                    litros   = COALESCE(%s, litros),
                    dia      = COALESCE(%s, dia),
                    telefono = COALESCE(%s, telefono),
                    latitud  = COALESCE(%s, latitud),
                    longitud = COALESCE(%s, longitud)
                WHERE id = %s
                RETURNING id
            """, (
                payload.camion,
                payload.litros,
                payload.dia,
                payload.telefono,
                payload.latitud,
                payload.longitud,
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

# EXPORTAR EXCEL (rutas_activas)
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
        # Usar openpyxl para evitar dependencia extra
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# LIMPIEZA: FICTICIOS
@app.get("/eliminar-ficticio")
def eliminar_ficticio():
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                DELETE FROM ruta_activa
                WHERE nombre = 'Juan Pérez' OR telefono = '123456789'
            """)
            count = cur.rowcount
        return {"mensaje": "Registro(s) ficticio(s) eliminado(s)", "eliminados": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# LIMPIEZA: NULOS COMPLETOS
@app.get("/eliminar-nulos")
def eliminar_nulos():
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                DELETE FROM ruta_activa
                WHERE camion IS NULL
                  AND nombre IS NULL
                  AND latitud IS NULL
                  AND longitud IS NULL
                  AND litros IS NULL
                  AND dia IS NULL
                  AND telefono IS NULL
            """)
            count = cur.rowcount
        return {"mensaje": "Registros nulos eliminados", "eliminados": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
