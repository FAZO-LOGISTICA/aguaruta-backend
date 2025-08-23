# backend/main.py
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from typing import Dict, Optional, List
from contextlib import contextmanager
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import execute_values
import pandas as pd
import io
import os
import math  # ✅ para Haversine

# -----------------------------------------------------------------------------
# Configuración inicial
# -----------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL no está configurada en variables de entorno")

# Render requiere SSL
pool = SimpleConnectionPool(1, 20, dsn=DATABASE_URL, sslmode="require")

app = FastAPI(title="AguaRuta API", version="2.4.0")

# CORS (Netlify + local dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://aguaruta.netlify.app",
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Helpers DB
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

def _rows_to_dicts(cur, rows):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]

# -----------------------------------------------------------------------------
# Helpers numéricos y geo
# -----------------------------------------------------------------------------
def _to_float_or_none(x):
    if x is None or x == "":
        return None
    try:
        return float(str(x).strip().replace(",", "."))
    except Exception:
        return None

def _to_int_or_none(x):
    v = _to_float_or_none(x)
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None

def _valid_lat_lon(lat, lon) -> bool:
    try:
        return (-90.0 <= float(lat) <= 90.0) and (-180.0 <= float(lon) <= 180.0)
    except Exception:
        return False

def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Distancia en km entre (lat1,lon1) y (lat2,lon2) usando Haversine."""
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(p1) * math.cos(p2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

# -----------------------------------------------------------------------------
# Salud
# -----------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

# -----------------------------------------------------------------------------
# RUTA ACTIVA — listar / editar
# -----------------------------------------------------------------------------
@app.get("/rutas-activas")
def obtener_rutas_activas():
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                SELECT id, camion, nombre, dia, litros, telefono, latitud, longitud
                FROM ruta_activa
                ORDER BY camion, dia, nombre
            """)
            filas = cur.fetchall()
            return _rows_to_dicts(cur, filas)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/rutas-activas/{id}")
def editar_ruta_activa(id: int, data: Dict):
    """
    Body JSON con las claves a actualizar. Ej:
    { "camion":"A5", "dia":"MARTES", "latitud":-33.1, "longitud":-71.5 }
    """
    try:
        if not data:
            raise HTTPException(status_code=400, detail="Body vacío")
        with get_conn_cursor() as (_, cur):
            sets = ", ".join([f"{k} = %s" for k in data.keys()])
            values = list(data.values()) + [id]
            cur.execute(f"UPDATE ruta_activa SET {sets} WHERE id = %s", values)
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Registro no encontrado")
        return {"mensaje": "✅ Registro actualizado correctamente", "id": id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# COMPAT — algunos frontends llaman PUT /editar-ruta (sin {id})
# -----------------------------------------------------------------------------
@app.put("/editar-ruta")
def editar_ruta_legacy(payload: Dict):
    try:
        rid = payload.get("id") or payload.get("ID") or payload.get("Id")
        if not rid:
            raise HTTPException(status_code=400, detail="Falta 'id' en el payload")

        allowed = {"camion", "nombre", "dia", "litros", "telefono", "latitud", "longitud"}
        data = {k.lower(): v for k, v in (payload or {}).items() if k.lower() in allowed}

        if "litros"   in data: data["litros"]   = _to_int_or_none(data["litros"])
        if "latitud"  in data: data["latitud"]  = _to_float_or_none(data["latitud"])
        if "longitud" in data: data["longitud"] = _to_float_or_none(data["longitud"])

        if not data:
            raise HTTPException(status_code=400, detail="Sin campos para actualizar")

        with get_conn_cursor() as (_, cur):
            sets = ", ".join([f"{k} = %s" for k in data.keys()])
            values = list(data.values()) + [rid]
            cur.execute(f"UPDATE ruta_activa SET {sets} WHERE id = %s", values)
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Registro no encontrado")

        return {"ok": True, "id": rid, "mensaje": "✅ Registro actualizado"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/editar-ruta/{id}")
def editar_ruta_legacy_with_id(id: int, payload: Dict):
    payload = dict(payload or {})
    payload["id"] = id
    return editar_ruta_legacy(payload)

# -----------------------------------------------------------------------------
# IMPORTAR **RUTA ACTIVA** desde CSV/XLSX (reemplaza todo)
# -----------------------------------------------------------------------------
@app.post("/admin/importar-ruta-activa-file")
def importar_ruta_activa_file(
    archivo: UploadFile = File(...),
    truncate: bool = Form(True),
):
    """
    Sube un CSV/XLSX y carga DIRECTO en ruta_activa.
    Columnas aceptadas (en cualquier orden y con alias):
      camion | nombre | litros | latitud | longitud | dia (o dia_asignado) | telefono
    - Reemplaza comas decimales por punto.
    - Ignora vacíos (no rompe).
    - Si truncate=True (default), limpia ruta_activa antes de insertar.
    """
    try:
        content = archivo.file.read()
        nombre = archivo.filename.lower()

        # Leer archivo a DataFrame
        if nombre.endswith(".xlsx"):
            df = pd.read_excel(io.BytesIO(content), dtype=str)
        elif nombre.endswith(".csv"):
            try:
                df = pd.read_csv(io.BytesIO(content), dtype=str, encoding="utf-8")
            except Exception:
                df = pd.read_csv(io.BytesIO(content), dtype=str, encoding="latin-1")
        else:
            raise HTTPException(status_code=400, detail="Formato no soportado. Sube .csv o .xlsx")

        # Normalizar nombres de columnas
        df.columns = [c.strip().lower() for c in df.columns]

        def pick(df, col, *alts):
            for c in (col, *alts):
                if c in df.columns:
                    return df[c]
            return None

        out = pd.DataFrame({
            "camion":   pick(df, "camion"),
            "nombre":   pick(df, "nombre", "jefe_hogar"),
            "dia":      pick(df, "dia", "dia_asignado"),
            "litros":   pick(df, "litros", "litros_de_entrega"),
            "telefono": pick(df, "telefono", "phone"),
            "latitud":  pick(df, "latitud", "lat", "latitude"),
            "longitud": pick(df, "longitud", "lon", "lng", "longitude"),
        })

        # Limpiar/tipar
        for c in ["latitud", "longitud", "litros"]:
            out[c] = pd.to_numeric(out[c].astype(str).str.replace(",", ".", regex=False), errors="coerce")
        for c in ["camion", "nombre", "dia", "telefono"]:
            out[c] = out[c].astype(str).str.strip().replace({"nan": None, "None": None, "": None})
        out = out.where(pd.notnull(out), None)

        rows = list(out.itertuples(index=False, name=None))
        if not rows:
            raise HTTPException(status_code=400, detail="Archivo sin filas útiles")

        with get_conn_cursor() as (_, cur):
            if truncate:
                cur.execute("TRUNCATE TABLE ruta_activa;")
            execute_values(cur, """
                INSERT INTO ruta_activa (camion, nombre, dia, litros, telefono, latitud, longitud)
                VALUES %s
            """, rows)

        return {"ok": True, "insertados": len(rows)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# EXPORTAR RUTA ACTIVA a Excel
# -----------------------------------------------------------------------------
@app.get("/exportar-excel")
def exportar_excel():
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                SELECT camion, nombre, dia, litros, telefono, latitud, longitud
                FROM ruta_activa
                ORDER BY camion, dia, nombre
            """)
            filas = cur.fetchall()
            cols = [d[0] for d in cur.description]

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
# REGISTRAR NUEVO PUNTO (manual)
# -----------------------------------------------------------------------------
@app.post("/registrar-nuevo-punto")
def registrar_nuevo_punto(data: Dict):
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                INSERT INTO ruta_activa (camion, nombre, dia, litros, telefono, latitud, longitud)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                data.get("camion"), data.get("nombre"), data.get("dia"),
                data.get("litros"), data.get("telefono"),
                data.get("latitud"), data.get("longitud")
            ))
            new_id = cur.fetchone()[0]
        return {"mensaje": "✅ Nuevo punto registrado en ruta activa", "id": new_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# REGISTRAR NUEVO PUNTO (auto-asignación por proximidad)
# -----------------------------------------------------------------------------
@app.post("/registrar-nuevo-punto-auto")
def registrar_nuevo_punto_auto(data: Dict):
    """
    Inserta un nuevo punto auto-asignando el CAMION y el DIA en base al punto más cercano de ruta_activa.
    Requiere: nombre, litros, latitud, longitud (telefono y dia son opcionales).
    """
    try:
        nombre = (data.get("nombre") or "").strip()
        litros = _to_int_or_none(data.get("litros"))
        telefono = (data.get("telefono") or None)

        lat = _to_float_or_none(data.get("latitud"))
        lon = _to_float_or_none(data.get("longitud"))
        dia_in = (data.get("dia") or None)

        if not nombre:
            raise HTTPException(status_code=400, detail="Falta 'nombre'")
        if litros is None or litros <= 0:
            raise HTTPException(status_code=400, detail="'litros' inválido")
        if lat is None or lon is None or not _valid_lat_lon(lat, lon):
            raise HTTPException(status_code=400, detail="Coordenadas inválidas")

        # Buscar punto más cercano existente
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                SELECT id, camion, dia, latitud, longitud
                FROM ruta_activa
                WHERE camion IS NOT NULL
                  AND latitud IS NOT NULL
                  AND longitud IS NOT NULL
            """)
            filas = cur.fetchall() or []

            mejor = None  # (dist_km, camion, dia, id_ref)
            for (rid, camion_ref, dia_ref, lat_ref, lon_ref) in filas:
                try:
                    dkm = _haversine_km(lat, lon, float(lat_ref), float(lon_ref))
                except Exception:
                    continue
                if (mejor is None) or (dkm < mejor[0]):
                    mejor = (dkm, str(camion_ref).upper() if camion_ref else None, dia_ref, rid)

            if mejor:
                dist_km, camion_sel, dia_sel, ref_id = mejor
                camion_final = camion_sel or "A1"
                dia_final = dia_in or dia_sel  # prioriza día enviado; si no, usa del vecino
                ref = {"id_ref": ref_id, "dist_km": round(dist_km, 3)}
            else:
                camion_final = "A1"
                dia_final = dia_in
                ref = {"id_ref": None, "dist_km": None}

            cur.execute("""
                INSERT INTO ruta_activa (camion, nombre, dia, litros, telefono, latitud, longitud)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (camion_final, nombre, dia_final, litros, telefono, lat, lon))
            new_id = cur.fetchone()[0]

        return {
            "ok": True,
            "mensaje": "✅ Punto registrado y asignado por proximidad",
            "id": new_id,
            "asignacion": {"camion": camion_final, "dia": dia_final},
            "referencia": ref,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# ENTREGAS APP (historial y registro)
# -----------------------------------------------------------------------------
@app.get("/entregas-app")
def obtener_entregas_app():
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                SELECT nombre, camion, litros, estado, fecha, latitud, longitud, foto
                FROM entregas_app
                ORDER BY fecha DESC
            """)
            filas = cur.fetchall()
            return _rows_to_dicts(cur, filas)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/entregas-app")
def registrar_entrega_app(data: Dict):
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
# SHIM de compatibilidad: /entregas y /entregas/no-entregadas
# -----------------------------------------------------------------------------
@app.get("/entregas")
def listar_entregas(
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    estado: Optional[str] = None,
    camion: Optional[str] = None,
):
    """
    Devuelve entregas filtradas por rango de fechas y/o estado/camion.
    - desde/hasta: YYYY-MM-DD (se comparan contra fecha::date)
    - estado y camion: match case-insensitive exacto
    """
    try:
        where = []
        params: List[str] = []

        if desde:
            where.append("fecha::date >= %s")
            params.append(desde)
        if hasta:
            where.append("fecha::date <= %s")
            params.append(hasta)
        if estado:
            where.append("UPPER(estado) = UPPER(%s)")
            params.append(estado)
        if camion:
            where.append("UPPER(camion) = UPPER(%s)")
            params.append(camion)

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        sql = f"""
            SELECT nombre, camion, litros, estado, fecha, latitud, longitud, foto
            FROM entregas_app
            {where_sql}
            ORDER BY fecha DESC
        """

        with get_conn_cursor() as (_, cur):
            cur.execute(sql, params)
            rows = cur.fetchall()
            return _rows_to_dicts(cur, rows)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/entregas/no-entregadas")
def listar_no_entregadas(
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    camion: Optional[str] = None,
):
    """
    Atajo para 'no entregadas'.
    Considera cualquier estado que comience con 'NO' (NO ENTREGADO/NO ENTREGADA).
    """
    try:
        where = ["UPPER(estado) LIKE 'NO%'"]
        params: List[str] = []

        if desde:
            where.append("fecha::date >= %s")
            params.append(desde)
        if hasta:
            where.append("fecha::date <= %s")
            params.append(hasta)
        if camion:
            where.append("UPPER(camion) = UPPER(%s)")
            params.append(camion)

        where_sql = "WHERE " + " AND ".join(where)
        sql = f"""
            SELECT nombre, camion, litros, estado, fecha, latitud, longitud, foto
            FROM entregas_app
            {where_sql}
            ORDER BY fecha DESC
        """

        with get_conn_cursor() as (_, cur):
            cur.execute(sql, params)
            rows = cur.fetchall()
            return _rows_to_dicts(cur, rows)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# Limpieza / utilidades
# -----------------------------------------------------------------------------
@app.post("/limpiar-tablas")
def limpiar_tablas():
    """Limpia SOLO ruta_activa."""
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("TRUNCATE TABLE ruta_activa;")
        return {"mensaje": "✅ Tabla ruta_activa limpiada"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/drop-redistribucion")
def drop_redistribucion():
    """Opcional: elimina la tabla redistribucion si existe (por si quedó de versiones antiguas)."""
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("DROP TABLE IF EXISTS redistribucion;")
        return {"mensaje": "✅ Tabla redistribucion eliminada (si existía)"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
