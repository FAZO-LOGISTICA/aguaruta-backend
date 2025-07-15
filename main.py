from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd

app = FastAPI()

# Habilitar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permitir todos los orígenes
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def inicio():
    return {"message": "API AguaRuta funcionando correctamente"}

@app.get("/ruta-asignada")
def obtener_ruta_asignada(conductor: str = Query(...), dia: str = Query(...)):
    try:
        df = pd.read_csv("datos/base_datos_todos_con_coordenadas.csv")

        # Normalizar nombres de columnas
        df.columns = [col.lower().strip() for col in df.columns]

        # Asegurar nombres esperados
        if 'conductor' not in df.columns or 'dia_asignado' not in df.columns:
            return {"error": "Faltan columnas en el archivo: ['conductor', 'dia_asignado']"}

        # Filtrar por conductor y día
        filtro = (
            df["conductor"].str.strip().str.upper() == conductor.strip().upper()
        ) & (
            df["dia_asignado"].str.strip().str.upper() == dia.strip().upper()
        )

        resultado = df[filtro]

        if resultado.empty:
            return {"message": "No se encontraron rutas para ese conductor y día."}

        # Convertir a lista de diccionarios
        datos = resultado.to_dict(orient="records")
        return {"datos": datos}

    except FileNotFoundError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Error inesperado: {str(e)}"}
