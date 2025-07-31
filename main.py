from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

EXCEL_PATH = "data/base_datos_todos_con_coordenadas.xlsx"
REDIST_PATH = "data/redistribucion.xlsx"

# 1. RUTAS ACTIVAS

@app.get("/rutas-activas")
def obtener_rutas_activas():
    try:
        df = pd.read_excel(EXCEL_PATH)
        columnas_requeridas = [
            'id camión', 'nombre (jefe de hogar)', 'latitud', 'longitud',
            'litros de entrega', 'dia'
        ]
        for col in columnas_requeridas:
            if col not in df.columns:
                return {"error": f"Falta columna requerida: {col}"}
        rutas = []
        for _, row in df.iterrows():
            if pd.notnull(row["latitud"]) and pd.notnull(row["longitud"]):
                ruta = {
                    "camion": row["id camión"],
                    "nombre": row["nombre (jefe de hogar)"],
                    "latitud": row["latitud"],
                    "longitud": row["longitud"],
                    "litros": row["litros de entrega"],
                    "dia_asignado": row["dia"],
                }
                if "telefono" in df.columns and pd.notnull(row["telefono"]):
                    ruta["telefono"] = row["telefono"]
                rutas.append(ruta)
        return rutas
    except Exception as e:
        return {"error": str(e)}

@app.put("/editar-ruta")
async def editar_ruta(request: Request):
    try:
        data = await request.json()
        df = pd.read_excel(EXCEL_PATH)
        index = df[df["nombre (jefe de hogar)"] == data["nombre"]].index
        if len(index) == 0:
            return {"error": "No se encontró el registro"}
        i = index[0]
        df.at[i, "id camión"] = data.get("camion", df.at[i, "id camión"])
        df.at[i, "litros de entrega"] = data.get("litros", df.at[i, "litros de entrega"])
        df.at[i, "dia"] = data.get("dia_asignado", df.at[i, "dia"])
        if "telefono" in data:
            df.at[i, "telefono"] = data.get("telefono", df.at[i, "telefono"])
        df.at[i, "latitud"] = data.get("latitud", df.at[i, "latitud"])
        df.at[i, "longitud"] = data.get("longitud", df.at[i, "longitud"])
        df.to_excel(EXCEL_PATH, index=False)
        return {"mensaje": "Ruta actualizada correctamente"}
    except Exception as e:
        return {"error": str(e)}

# 2. REDISTRIBUCIÓN

@app.get("/redistribucion")
def obtener_redistribucion():
    try:
        if not os.path.exists(REDIST_PATH):
            return []
        df = pd.read_excel(REDIST_PATH)
        # Aquí ajusta los nombres según tus columnas reales:
        columnas = df.columns.tolist()
        data = []
        for _, row in df.iterrows():
            fila = {col: row[col] for col in columnas}
            data.append(fila)
        return data
    except Exception as e:
        return {"error": str(e)}

@app.put("/editar-redistribucion")
async def editar_redistribucion(request: Request):
    try:
        data = await request.json()
        df = pd.read_excel(REDIST_PATH)
        # Editar por nombre, cambia la clave si tu columna de ID es otra:
        index = df[df["nombre (jefe de hogar)"] == data["nombre"]].index
        if len(index) == 0:
            return {"error": "No se encontró el registro"}
        i = index[0]
        # Actualiza lo que corresponda, agrega o cambia columnas según tus datos:
        if "nuevo_camion" in data:
            df.at[i, "nuevo camión"] = data.get("nuevo_camion", df.at[i, "nuevo camión"])
        if "nuevo_litros" in data:
            df.at[i, "litros de entrega"] = data.get("nuevo_litros", df.at[i, "litros de entrega"])
        if "dia" in data:
            df.at[i, "dia"] = data.get("dia", df.at[i, "dia"])
        if "telefono" in data:
            df.at[i, "telefono"] = data.get("telefono", df.at[i, "telefono"])
        # Puedes agregar más campos según tus columnas
        df.to_excel(REDIST_PATH, index=False)
        return {"mensaje": "Redistribución actualizada correctamente"}
    except Exception as e:
        return {"error": str(e)}

# Puedes seguir agregando endpoints aquí (registrar entrega, registrar punto, etc.)
