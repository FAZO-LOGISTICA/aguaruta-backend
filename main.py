from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from contextlib import contextmanager
import pandas as pd
import io
import os
import shutil
from datetime import datetime

# -----------------------------------------------------------------------------
# Configuración inicial
# -----------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL no está configurada en variables de entorno")

pool = SimpleConnectionPool(
    1, 20, dsn=DATABASE_URL, sslmode="require"
)

app = FastAPI()

# CORS para Netlify
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://aguaruta.netlify.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
@contextmanager
def get_conn_cursor():
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        yield conn, cur
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        pool.putconn(conn)

# -----------------------------------------------------------------------------
# ENDPOINTS RUTAS ACTIVAS
# -----------------------------------------------------------------------------
@app.get("/rutas-activas")
def obtener_rutas_activas():
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                SELECT id, camion, nombre, dia, litros, telefono, latitud, longitud
                FROM ruta_activa
            """)
            filas = cur.fetchall()
            cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, fila)) for fila in filas]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/rutas-activas/{id}")
def editar_ruta_activa(id: int, data: dict):
    try:
        with get_conn_cursor() as (conn, cur):
            sets = ", ".join([f"{k} = %s" for k in data.keys()])
            values = list(data.values()) + [id]
            cur.execute(f"UPDATE ruta_activa SET {sets} WHERE id = %s", values)
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Registro no encontrado")
        return {"mensaje": "✅ Registro actualizado correctamente"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# ENDPOINTS REDISTRIBUCIÓN
# -----------------------------------------------------------------------------
@app.get("/redistribucion")
def obtener_redistribucion():
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                SELECT id, camion, nombre, dia, litros, telefono, latitud, longitud
                FROM redistribucion
            """)
            filas = cur.fetchall()
            cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, fila)) for fila in filas]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/redistribucion")
def cargar_redistribucion(file: UploadFile = File(...)):
    try:
        # Guardar archivo temporal
        temp_path = f"temp_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        df = pd.read_excel(temp_path)
        os.remove(temp_path)

        # Limpiar tabla redistribucion
        with get_conn_cursor() as (_, cur):
            cur.execute("TRUNCATE TABLE redistribucion;")

        # Insertar nuevos datos
        with get_conn_cursor() as (_, cur):
            for _, row in df.iterrows():
                cur.execute("""
                    INSERT INTO redistribucion (camion, nombre, dia, litros, telefono, latitud, longitud)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    row["camion"], row["nombre"], row["dia"], row["litros"],
                    row.get("telefono"), row.get("latitud"), row.get("longitud")
                ))

        return {"mensaje": f"✅ Redistribución cargada con {len(df)} registros."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# EXPORTAR A EXCEL
# -----------------------------------------------------------------------------
@app.get("/exportar-excel")
def exportar_excel():
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                SELECT camion, nombre, dia, litros, telefono, latitud, longitud
                FROM ruta_activa
            """)
            filas = cur.fetchall()
            cols = [desc[0] for desc in cur.description]

        df = pd.DataFrame(filas, columns=cols)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Rutas Activas")
        output.seek(0)

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=rutas_activas.xlsx"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# REGISTRAR ENTREGA DESDE APP MÓVIL
# -----------------------------------------------------------------------------
@app.post("/entregas-app")
async def registrar_entrega(data: dict):
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                INSERT INTO entregas_app (nombre, camion, litros, estado, fecha, latitud, longitud, foto)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                data.get("nombre"), data.get("camion"), data.get("litros"),
                data.get("estado"), data.get("fecha"),
                data.get("latitud"), data.get("longitud"), data.get("foto")
            ))
        return {"mensaje": "✅ Entrega registrada correctamente"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# LIMPIAR TABLAS
# -----------------------------------------------------------------------------
@app.post("/limpiar-tablas")
def limpiar_tablas():
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("TRUNCATE TABLE ruta_activa;")
            cur.execute("TRUNCATE TABLE redistribucion;")
        return {"mensaje": "✅ Tablas limpiadas"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# REGISTRAR NUEVO PUNTO
# -----------------------------------------------------------------------------
@app.post("/registrar-nuevo-punto")
def registrar_nuevo_punto(data: dict):
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                INSERT INTO ruta_activa (camion, nombre, dia, litros, telefono, latitud, longitud)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                data.get("camion"), data.get("nombre"), data.get("dia"),
                data.get("litros"), data.get("telefono"),
                data.get("latitud"), data.get("longitud")
            ))
        return {"mensaje": "✅ Nuevo punto registrado en ruta activa"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# ACTIVAR REDISTRIBUCIÓN (NUEVO)
# -----------------------------------------------------------------------------
@app.post("/activar-redistribucion")
def activar_redistribucion():
    try:
        with get_conn_cursor() as (_, cur):
            # 1. Vaciar ruta_activa
            cur.execute("TRUNCATE TABLE ruta_activa;")
            # 2. Copiar redistribucion -> ruta_activa
            cur.execute("""
                INSERT INTO ruta_activa (camion, nombre, dia, litros, telefono, latitud, longitud)
                SELECT camion, nombre, dia, litros, telefono, latitud, longitud
                FROM redistribucion
            """)
            insertados = cur.rowcount
        return {"mensaje": f"✅ Redistribución activada: {insertados} registros movidos a ruta_activa."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
