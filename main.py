from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import psycopg2
import pandas as pd
import io

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuración de la base de datos
DB_URL = "postgresql://aguaruta_db_user:u1JUg0dcbEYzzzoF8N4lsbdZ6c2ZXyPb@dpg-d25b5mripnbc73dpod0g-a.oregon-postgres.render.com/aguaruta_db"

def get_connection():
    return psycopg2.connect(DB_URL)

# RUTAS ACTIVAS

@app.get("/rutas-activas")
def obtener_rutas_activas():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT camion, nombre, latitud, longitud, litros, dia, telefono FROM ruta_activa")
        filas = cur.fetchall()
        columnas = [desc[0] for desc in cur.description]
        rutas = [dict(zip(columnas, fila)) for fila in filas]
        cur.close()
        conn.close()
        return rutas
    except Exception as e:
        return {"error": str(e)}

@app.put("/editar-ruta")
async def editar_ruta(request: Request):
    try:
        data = await request.json()
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM ruta_activa WHERE nombre = %s", (data["nombre"],))
        row = cur.fetchone()
        if not row:
            return {"error": "No se encontró el registro"}
        id_ruta = row[0]
        cur.execute("""
            UPDATE ruta_activa SET
                camion = %s,
                litros = %s,
                dia = %s,
                telefono = %s,
                latitud = %s,
                longitud = %s
            WHERE id = %s
        """, (
            data.get("camion"),
            data.get("litros"),
            data.get("dia_asignado"),
            data.get("telefono"),
            data.get("latitud"),
            data.get("longitud"),
            id_ruta
        ))
        conn.commit()
        cur.close()
        conn.close()
        return {"mensaje": "Ruta actualizada correctamente"}
    except Exception as e:
        return {"error": str(e)}

# REDISTRIBUCIÓN

@app.get("/redistribucion")
def obtener_redistribucion():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT camion, nombre, dia, litros, telefono, latitud, longitud FROM redistribucion")
        filas = cur.fetchall()
        columnas = [desc[0] for desc in cur.description]
        data = [dict(zip(columnas, fila)) for fila in filas]
        cur.close()
        conn.close()
        return data
    except Exception as e:
        return {"error": str(e)}

@app.put("/editar-redistribucion")
async def editar_redistribucion(request: Request):
    try:
        data = await request.json()
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM redistribucion WHERE nombre = %s", (data["nombre"],))
        row = cur.fetchone()
        if not row:
            return {"error": "No se encontró el registro"}
        id_redist = row[0]
        cur.execute("""
            UPDATE redistribucion SET
                camion = %s,
                litros = %s,
                dia = %s,
                telefono = %s,
                latitud = %s,
                longitud = %s
            WHERE id = %s
        """, (
            data.get("nuevo_camion"),
            data.get("nuevo_litros"),
            data.get("dia"),
            data.get("telefono"),
            data.get("latitud"),
            data.get("longitud"),
            id_redist
        ))
        conn.commit()
        cur.close()
        conn.close()
        return {"mensaje": "Redistribución actualizada correctamente"}
    except Exception as e:
        return {"error": str(e)}

# EXPORTAR EXCEL

@app.get("/exportar-excel")
def exportar_excel():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT camion, nombre, latitud, longitud, litros, dia, telefono FROM ruta_activa")
        filas = cur.fetchall()
        columnas = [desc[0] for desc in cur.description]
        cur.close()
        conn.close()
        # Pandas DataFrame
        df = pd.DataFrame(filas, columns=columnas)
        # Excel en memoria
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name="Rutas")
        output.seek(0)
        headers = {
            'Content-Disposition': 'attachment; filename="rutas_activas.xlsx"'
        }
        return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)
    except Exception as e:
        return {"error": str(e)}

# ELIMINAR REGISTRO FICTICIO

@app.delete("/eliminar-ficticio")
def eliminar_ficticio():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM ruta_activa
            WHERE nombre = 'Juan Pérez' OR telefono = '123456789'
        """)
        conn.commit()
        cur.close()
        conn.close()
        return {"mensaje": "Registro ficticio eliminado"}
    except Exception as e:
        return {"error": str(e)}
        @app.delete("/eliminar-nulos")
def eliminar_nulos():
    try:
        conn = get_connection()
        cur = conn.cursor()
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
        conn.commit()
        cur.close()
        conn.close()
        return {"mensaje": "Registros nulos eliminados"}
    except Exception as e:
        return {"error": str(e)}
        @app.get("/eliminar-nulos")
def eliminar_nulos():
    try:
        conn = get_connection()
        cur = conn.cursor()
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
        conn.commit()
        cur.close()
        conn.close()
        return {"mensaje": "Registros nulos eliminados"}
    except Exception as e:
        return {"error": str(e)}


