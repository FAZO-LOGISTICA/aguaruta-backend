from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import pandas as pd

app = FastAPI()

# Permitir acceso desde cualquier origen
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "API AguaRuta funcionando correctamente"}

@app.get("/ruta-asignada")
def get_ruta_asignada(conductor: str = Query(...), dia: str = Query(...)):
    try:
        # Lee el archivo Excel desde la carpeta /data
        df = pd.read_excel("data/base_datos_todos_con_coordenadas.xlsx")

        # Normaliza nombres de columnas para evitar errores
        df.columns = [col.strip().lower() for col in df.columns]

        # Filtra por conductor y día
        datos_filtrados = df[
            (df["conductor"].str.upper() == conductor.upper()) &
            (df["dia"].str.upper() == dia.upper())
        ]

        # Selecciona columnas útiles
        resultado = datos_filtrados[["camion", "dia", "litros", "latitud", "longitud"]].to_dict(orient="records")
        return resultado

    except FileNotFoundError:
        return JSONResponse(content={"error": "No se encuentra el archivo Excel"}, status_code=500)
    except KeyError as e:
        return JSONResponse(content={"error": f"Columna faltante: {str(e)}"}, status_code=500)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
