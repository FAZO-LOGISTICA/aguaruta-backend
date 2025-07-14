# backend/rutas_activas.py
from fastapi import APIRouter, HTTPException
import pandas as pd
from pathlib import Path

router = APIRouter()

RUTA_BASE = Path("data/base_datos_todos_con_coordenadas.xlsx")
CAMIONES_VALIDOS = ['A1', 'A2', 'A3', 'A4', 'A5', 'M1', 'M2']

@router.get("/rutas-activas")
def obtener_rutas_activas():
    try:
        df = pd.read_excel(RUTA_BASE)
        df.columns = [col.lower().strip().replace(" ", "_") for col in df.columns]
        df = df.fillna("")
        return df.to_dict(orient="records")
    except Exception as e:
        return {"error": str(e)}

@router.get("/puntos")
def obtener_puntos():
    try:
        df = pd.read_excel(RUTA_BASE)
        df.columns = [col.lower().strip().replace(" ", "_") for col in df.columns]

        nombre_col = next((c for c in df.columns if "nombre" in c), None)
        litros_col = next((c for c in df.columns if "litro" in c), None)
        lat_col = next((c for c in df.columns if "lat" in c), None)
        lon_col = next((c for c in df.columns if "lon" in c or "long" in c), None)

        if not all([lat_col, lon_col, nombre_col, litros_col]):
            return {"error": "Faltan columnas necesarias"}

        df = df.rename(columns={
            nombre_col: "nombre",
            litros_col: "litros",
            lat_col: "latitud",
            lon_col: "longitud"
        })

        df = df.dropna(subset=["latitud", "longitud", "nombre", "litros"])
        return df[["latitud", "longitud", "nombre", "litros"]].to_dict(orient="records")
    except Exception as e:
        return {"error": str(e)}

@router.post("/registrar-nuevo-punto")
def registrar_nuevo_punto(punto: dict):
    try:
        if not RUTA_BASE.exists():
            raise HTTPException(status_code=404, detail="Base de datos no encontrada")

        df = pd.read_excel(RUTA_BASE)
        df.columns = [col.lower().strip().replace(" ", "_") for col in df.columns]
        df = df.fillna("")

        # Agrupar por camión actual
        df_actual = df[df['id_camión'].isin(CAMIONES_VALIDOS)]
        resumen = df_actual.groupby('id_camión')['litros_de_entrega'].sum().to_dict()

        # Elegir camión con menor carga total
        asignar_a = min(CAMIONES_VALIDOS, key=lambda c: resumen.get(c, 0))

        # Asignar día tentativo (puedes ajustar lógica más adelante)
        dia = "LUNES"

        nuevo = {
            "id_camión": asignar_a,
            "patente": "",
            "conductor": "",
            "dia": dia,
            "nombre_(jefe_de_hogar)": punto["nombre"],
            "telefono": punto["telefono"],
            "sector": punto["sector"],
            "litros_de_entrega": punto["litros"],
            "latitud": punto["latitud"],
            "longitud": punto["longitud"]
        }

        df_nuevo = pd.concat([df, pd.DataFrame([nuevo])], ignore_index=True)
        df_nuevo.to_excel(RUTA_BASE, index=False)

        return {"mensaje": "✅ Punto registrado", "camion_asignado": asignar_a}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
