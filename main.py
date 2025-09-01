from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from typing import Dict, Optional, List
from contextlib import contextmanager
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import execute_values
from zoneinfo import ZoneInfo
import pandas as pd
import io
import os
import math
import datetime as dt
import uuid
import time
from pathlib import Path

# -----------------------------------------------------------------------------
# Configuración inicial
# -----------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL no está configurada en variables de entorno")

def _augment_dsn(url: str) -> str:
    out = url
    if "sslmode=" not in out:
        out += ("&sslmode=require" if "?" in out else "?sslmode=require")
    if "connect_timeout=" not in out:
        out += ("&connect_timeout=5" if "?" in out else "?connect_timeout=5")
    if "application_name=" not in out:
        out += ("&application_name=aguaruta-api" if "?" in out else "?application_name=aguaruta-api")
    return out

DATABASE_URL = _augment_dsn(DATABASE_URL)

app = FastAPI(title="AguaRuta API", version="3.2.3")

# CORS (Netlify + local dev) — evita "*" con credentials
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://aguaruta.netlify.app",
        "http://localhost:3000",
        "http://localhost:5173",
        # "http://localhost:19006",  # descomentar si usas Expo Web
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Pool de conexiones (lazy) + retries
# -----------------------------------------------------------------------------
_pool: Optional[SimpleConnectionPool] = None

def _init_pool_with_retries(max_attempts: int = 6) -> None:
    """Inicializa el pool con reintentos exponenciales sin botar el proceso."""
    global _pool
    if _pool is not None:
        return
    last_err = None
    for attempt in range(max_attempts):
        try:
            _pool = SimpleConnectionPool(
                1, 20,
                dsn=DATABASE_URL,
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=5,
            )
            # Smoke test
            conn = _pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                    cur.fetchone()
            finally:
                _pool.putconn(conn)
            return
        except Exception as e:
            last_err = e
            time.sleep(min(10, 2 ** attempt))  # 1,2,4,8,10,10
    raise last_err

@app.on_event("startup")
def _startup_try_pool():
    try:
        _init_pool_with_retries(max_attempts=3)
    except Exception as e:
        print(f"[WARN] No se pudo inicializar el pool en startup: {e}")

# -----------------------------------------------------------------------------
# Archivos estáticos (fotos locales opcionales)
# -----------------------------------------------------------------------------
UPLOAD_ROOT = Path(os.getenv("UPLOAD_ROOT", "uploads")).resolve()
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_ROOT)), name="uploads")

def _safe_ext(filename: str) -> str:
    ext = (filename or "").split(".")[-1].lower()
    return ext if ext in {"jpg", "jpeg", "png", "webp"} else "jpg"

def _save_upload_file(f: UploadFile, subdir: str = "evidencias") -> str:
    today = dt.datetime.now()
    folder = UPLOAD_ROOT / subdir / f"{today:%Y}" / f"{today:%m}"
    folder.mkdir(parents=True, exist_ok=True)
    ext = _safe_ext(f.filename)
    name = f"{today:%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}.{ext}"
    disk_path = folder / name
    with open(disk_path, "wb") as out:
        out.write(f.file.read())
    rel = disk_path.relative_to(UPLOAD_ROOT).as_posix()
    return f"/uploads/{rel}"

# -----------------------------------------------------------------------------
# Helpers DB
# -----------------------------------------------------------------------------
def _get_pool_or_503() -> SimpleConnectionPool:
    global _pool
    if _pool is None:
        try:
            _init_pool_with_retries(max_attempts=6)
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Base de datos no disponible: {e}")
    return _pool

@contextmanager
def get_conn_cursor():
    pool = _get_pool_or_503()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
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
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(p1) * math.cos(p2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

def _today_str_tzcl():
    return dt.datetime.now(ZoneInfo("America/Santiago")).date().isoformat()

def _get_first(data: Dict, *keys, cast="float"):
    for k in keys:
        if k in data and data[k] not in (None, ""):
            return _to_float_or_none(data[k]) if cast == "float" else data[k]
    return None

# -----------------------------------------------------------------------------
# Rutas/paths de datos (Excel oficial del mapa)
# -----------------------------------------------------------------------------
DATA_DIR = Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
MAP_XLSX = DATA_DIR / "base_datos_todos_con_coordenadas.xlsx"

def _sync_mapa_internal() -> Dict:
    with get_conn_cursor() as (_, cur):
        cur.execute("""
            SELECT nombre, litros, telefono, latitud, longitud
            FROM ruta_activa
            WHERE latitud IS NOT NULL AND longitud IS NOT NULL
        """)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]

    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        return {"ok": False, "puntos_exportados": 0, "archivo": str(MAP_XLSX)}

    for c in ["latitud", "longitud", "litros"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[
        df["latitud"].between(-90, 90) &
        df["longitud"].between(-180, 180)
    ]

    with pd.ExcelWriter(MAP_XLSX, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="puntos")

    return {"ok": True, "puntos_exportados": int(len(df)), "archivo": str(MAP_XLSX)}

# -----------------------------------------------------------------------------
# Routers externos (FREE Cloudinary sign)
# -----------------------------------------------------------------------------
try:
    from routers.cloudinary import router as cloudinary_router
    app.include_router(cloudinary_router)
except Exception:
    pass

# -----------------------------------------------------------------------------
# Salud
# -----------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/db/ping")
def db_ping():
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("SELECT 1;")
            cur.fetchone()
        return {"ok": True}
    except HTTPException as he:
        raise he
    except Exception as e:
        return {"ok": False, "error": str(e)}

# -----------------------------------------------------------------------------
# RUTA ACTIVA — listar / editar
# -----------------------------------------------------------------------------
@app.get("/rutas-activas")
def obtener_rutas_activas(camion: Optional[str] = None, dia: Optional[str] = None):
    try:
        where = []
        params: List[str] = []
        if camion:
            where.append("UPPER(camion) = UPPER(%s)")
            params.append(camion)
        if dia:
            where.append("UPPER(dia) = UPPER(%s)")
            params.append(dia)

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        with get_conn_cursor() as (_, cur):
            cur.execute(f"""
                SELECT id, camion, nombre, dia, litros, telefono, latitud, longitud
                FROM ruta_activa
                {where_sql}
                ORDER BY camion, dia, nombre
            """, params)
            filas = cur.fetchall()
            return _rows_to_dicts(cur, filas)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/rutas-activas/{id}")
def editar_ruta_activa(id: int, data: Dict):
    try:
        if not data:
            raise HTTPException(status_code=400, detail="Body vacío")
        with get_conn_cursor() as (_, cur):
            sets = ", ".join([f"{k} = %s" for k in data.keys()])
            values = list(data.values()) + [id]
            cur.execute(f"UPDATE ruta_activa SET {sets} WHERE id = %s", values)
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Registro no encontrado")
        try:
            _sync_mapa_internal()
        except Exception:
            pass
        return {"mensaje": "✅ Registro actualizado correctamente", "id": id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
        try:
            _sync_mapa_internal()
        except Exception:
            pass
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
# IMPORTAR RUTA ACTIVA desde CSV/XLSX (reemplaza todo)
# -----------------------------------------------------------------------------
@app.post("/admin/importar-ruta-activa-file")
def importar_ruta_activa_file(
    archivo: UploadFile = File(...),
    truncate: bool = Form(True),
):
    try:
        content = archivo.file.read()
        nombre = archivo.filename.lower()
        if nombre.endswith(".xlsx"):
            df = pd.read_excel(io.BytesIO(content), dtype=str)
        elif nombre.endswith(".csv"):
            try:
                df = pd.read_csv(io.BytesIO(content), dtype=str, encoding="utf-8")
            except Exception:
                df = pd.read_csv(io.BytesIO(content), dtype=str, encoding="latin-1")
        else:
            raise HTTPException(status_code=400, detail="Formato no soportado. Sube .csv o .xlsx")

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

        try:
            _sync_mapa_internal()
        except Exception:
            pass

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
# REGISTRAR NUEVO PUNTO (manual) / (auto)
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
        try:
            _sync_mapa_internal()
        except Exception:
            pass
        return {"mensaje": "✅ Nuevo punto registrado en ruta activa", "id": new_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/registrar-nuevo-punto-auto")
def registrar_nuevo_punto_auto(data: Dict):
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

        with get_conn_cursor() as (_, cur):
            cur.execute("""
                SELECT id, camion, dia, latitud, longitud
                FROM ruta_activa
                WHERE camion IS NOT NULL
                  AND latitud IS NOT NULL
                  AND longitud IS NOT NULL
            """)
            filas = cur.fetchall() or []

            mejor = None
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
                dia_final = dia_in or dia_sel
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

        try:
            _sync_mapa_internal()
        except Exception:
            pass

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
                SELECT nombre, camion, litros, estado, fecha, latitud, longitud, foto_url, motivo, usuario
                FROM entregas_app
                ORDER BY fecha DESC
            """)
            filas = cur.fetchall()
            return _rows_to_dicts(cur, filas)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/entregas-app")
def registrar_entrega_json(data: Dict):
    try:
        lat = _get_first(data, "latitud", "gps_lat", "lat")
        lon = _get_first(data, "longitud", "gps_lng", "lng", "lon")
        fecha_sql = data.get("fecha") or None
        estado = _to_int_or_none(data.get("estado"))

        with get_conn_cursor() as (_, cur):
            cur.execute("""
                INSERT INTO entregas_app (nombre, camion, litros, estado, fecha, latitud, longitud, foto_url, motivo, usuario)
                VALUES (%s, %s, %s, %s, COALESCE(%s, NOW()::timestamp), %s, %s, %s, %s, %s)
            """, (
                data.get("nombre"), data.get("camion"), data.get("litros"),
                estado, fecha_sql,
                lat, lon,
                data.get("foto_url") or data.get("foto") or data.get("foto_uri"),
                data.get("motivo"), data.get("usuario"),
            ))
        return {"mensaje": "✅ Entrega registrada correctamente"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/entregas-app-form")
async def registrar_entrega_form(
    nombre: str = Form(...),
    camion: str = Form(...),
    litros: Optional[int] = Form(None),
    estado: int = Form(...),
    fecha: Optional[str] = Form(None),
    latitud: Optional[float] = Form(None),
    longitud: Optional[float] = Form(None),
    motivo: Optional[str] = Form(None),
    usuario: Optional[str] = Form(None),
    foto: UploadFile = File(None),
):
    try:
        foto_url = None
        if foto is not None:
            foto_url = _save_upload_file(foto, subdir="evidencias")

        fecha_sql = fecha or None
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                INSERT INTO entregas_app (nombre, camion, litros, estado, fecha, latitud, longitud, foto_url, motivo, usuario)
                VALUES (%s, %s, %s, %s, COALESCE(%s, NOW()::timestamp), %s, %s, %s, %s, %s)
            """, (
                nombre, camion, litros, estado, fecha_sql, latitud, longitud, foto_url, motivo, usuario
            ))
        return {"mensaje": "✅ Entrega registrada correctamente", "foto_url": foto_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# SHIMs de listados
# -----------------------------------------------------------------------------
@app.get("/entregas")
def listar_entregas(
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    estado: Optional[str] = None,
    camion: Optional[str] = None,
    nombre: Optional[str] = None,
):
    try:
        where = []
        params: List[str] = []

        if desde:
            where.append("fecha::date >= %s"); params.append(desde)
        if hasta:
            where.append("fecha::date <= %s"); params.append(hasta)
        if estado:
            where.append("UPPER(estado::text) = UPPER(%s)"); params.append(estado)
        if camion:
            where.append("UPPER(camion) = UPPER(%s)"); params.append(camion)
        if nombre:
            where.append("UPPER(nombre) LIKE UPPER(%s)"); params.append(f"%{nombre}%")

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        sql = f"""
            SELECT nombre, camion, litros, estado, fecha, latitud, longitud, foto_url, motivo, usuario
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
    try:
        where = ["estado IN (0,2,3)"]
        params: List[str] = []
        if desde:
            where.append("fecha::date >= %s"); params.append(desde)
        if hasta:
            where.append("fecha::date <= %s"); params.append(hasta)
        if camion:
            where.append("UPPER(camion) = UPPER(%s)"); params.append(camion)

        where_sql = "WHERE " + " AND ".join(where)
        sql = f"""
            SELECT nombre, camion, litros, estado, fecha, latitud, longitud, foto_url, motivo, usuario
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
# NUEVO: ESTADOS DEL DÍA (para pintar verde/rojo en la app)
# -----------------------------------------------------------------------------
@app.get("/estados-dia")
def estados_del_dia(
    camion: str,
    dia: Optional[str] = None,
    fecha: Optional[str] = None,
):
    try:
        fecha_d = fecha or _today_str_tzcl()
        with get_conn_cursor() as (_, cur):
            params_r = [camion]
            where_r = ["UPPER(camion) = UPPER(%s)"]
            if dia:
                where_r.append("UPPER(dia) = UPPER(%s)")
                params_r.append(dia)
            where_r_sql = " AND ".join(where_r)

            cur.execute(f"""
                WITH base_ruta AS (
                  SELECT id, camion, nombre
                  FROM ruta_activa
                  WHERE {where_r_sql}
                ),
                ult_entrega AS (
                  SELECT DISTINCT ON (camion, nombre)
                         camion, nombre, estado, fecha
                  FROM entregas_app
                  WHERE fecha::date = %s
                  ORDER BY camion, nombre, fecha DESC
                )
                SELECT r.id, e.estado
                FROM base_ruta r
                JOIN ult_entrega e
                  ON UPPER(e.camion)=UPPER(r.camion) AND UPPER(e.nombre)=UPPER(r.nombre)
                WHERE e.estado IS NOT NULL
            """, params_r + [fecha_d])
            filas = cur.fetchall()
            return [{"id": rid, "estado": est} for (rid, est) in filas]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# Limpieza / utilidades / migraciones simples
# -----------------------------------------------------------------------------
@app.post("/limpiar-tablas")
def limpiar_tablas():
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("TRUNCATE TABLE ruta_activa;")
        try:
            _sync_mapa_internal()
        except Exception:
            pass
        return {"mensaje": "✅ Tabla ruta_activa limpiada"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/drop-redistribucion")
def drop_redistribucion():
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("DROP TABLE IF EXISTS redistribucion;")
        return {"mensaje": "✅ Tabla redistribucion eliminada (si existía)"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/migrar-entregas-app")
def migrar_entregas_app():
    """
    Agrega columnas faltantes a entregas_app (idempotente).
    Ejecuta esto una sola vez si tu tabla es antigua.
    """
    try:
        with get_conn_cursor() as (_, cur):
            cur.execute("""
                DO $$
                BEGIN
                  IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='entregas_app' AND column_name='foto_url'
                  ) THEN
                    ALTER TABLE entregas_app ADD COLUMN foto_url TEXT;
                  END IF;
                  IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='entregas_app' AND column_name='motivo'
                  ) THEN
                    ALTER TABLE entregas_app ADD COLUMN motivo TEXT;
                  END IF;
                  IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='entregas_app' AND column_name='usuario'
                  ) THEN
                    ALTER TABLE entregas_app ADD COLUMN usuario TEXT;
                  END IF;
                END$$;
            """)
        return {"ok": True, "mensaje": "✅ Migración aplicada (entregas_app)"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# ✅ Endpoint público para sincronizar Excel del mapa
# -----------------------------------------------------------------------------
@app.post("/admin/sync-mapa")
def sync_mapa():
    try:
        return _sync_mapa_internal()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
