from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd

app = FastAPI()

# Configurar CORS para permitir conexión desde cualquier origen
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ruta raíz de prueba
@app.get("/")
def root():
    return {"message": "API AguaRuta funcionando correctamente"}

# Ruta para obtener entregas por conductor y día
@app.get("/ruta-asignada")
def obtener_ruta_asignada(conductor: str = Query(...), dia: str = Query(...)):
    try:
        df = pd.read_excel("base_datos_todos_con_coordenadas.xlsx")

        # Normalizar nombres de columnas
        df.columns = [col.strip().lower() for col in df.columns]

        # Filtrar por conductor y día
        conductor_rutas = df[
            (df["conductor"] == conductor) & (df["dia"] == dia)
        ]

        resultados = []
        for _, row in conductor_rutas.iterrows():
            resultados.append({
                "camion": row["id camión"],
                "dia": row["dia"],
                "litros": row["litros de entrega"],
                "latitud": row["latitud"],
                "longitud": row["longitud"]
            })

        return resultados

    except Exception as e:
        return {"error": str(e)}

# Ruta adicional si se requiere por camión
@app.get("/rutas-por-camion")
def obtener_rutas_por_camion(camion: str = Query(...)):
    try:
        df = pd.read_excel("base_datos_todos_con_coordenadas.xlsx")
        df.columns = [col.strip().lower() for col in df.columns]

        data = df[df["id camión"] == camion]

        resultados = []
        for _, row in data.iterrows():
            resultados.append({
                "nombre": row["nombre (jefe de hogar)"],
                "dia": row["dia"],
                "litros": row["litros de entrega"],
                "latitud": row["latitud"],
                "longitud": row["longitud"]
            })

        return resultados

    except Exception as e:
        return {"error": str(e)}
