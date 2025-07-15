from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import uvicorn

app = FastAPI()

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
        # ✅ Ruta correcta al archivo Excel
        df = pd.read_excel("datos/base_datos_todos_con_coordenadas.xlsx")

        # Limpieza de columnas y nombres
        df.columns = df.columns.str.strip().str.lower()
        conductor = conductor.strip().lower()
        dia = dia.strip().lower()

        # Verificación de columnas requeridas
        if "conductor" not in df.columns or "dia_asignado" not in df.columns:
            return {"error": "Faltan columnas necesarias en el archivo Excel"}

        # Filtrar según el conductor y día
        resultados = df[
            (df["conductor"].str.lower().str.strip() == conductor) &
            (df["dia_asignado"].str.lower().str.strip() == dia)
        ]

        return resultados.to_dict(orient="records")
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=10000)
