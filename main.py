# main.py — AguaRuta Backend (Ultra-robusto, modo mixto Excel/DB, con auditoría y estadísticas)
# Autor: Mateo (tu senior full-stack) — 2025-09-28
import os
import uuid
import json
import math
import shutil
import logging
import hashlib
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Body, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import pandas as pd

# === Config DB opcional ===
import psycopg2
from psycopg2.pool import SimpleConnectionPool

# === JWT básico (sin dependencias externas) ===
import base64
import hmac

# =============================================================================
# CONFIG / LOGGING
# =============================================================================
APP_NAME = "AguaRuta Backend"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Archivos oficiales
EXCEL_FILE = DATA_DIR / "rutas_activas.xlsx"          # Fuente Excel
FOTOS_DIR = BASE_DIR / "fotos" / "evidencias"
FOTOS_DIR.mkdir(parents=True, exist_ok=True)

# Modo de datos: "excel" o "db"
DATA_MODE = os.getenv("DATA_MODE", "excel").lower().strip()

# JWT config
JWT_SECRET = os.getenv("JWT_SECRET", "aguaruta_super_secreto")
JWT_ISSUER = "AguaRuta"
JWT_EXP_MIN = int(os.getenv("JWT_EXP_MIN", "720"))  # 12 horas

# Colores por camión (oficial)
CAMION_COLORS: Dict[str, str] = {
    "A1": "#2563eb", "A2": "#059669", "A3": "#dc2626", "A4": "#f59e0b", "A5": "#7c3aed",
    "M1": "#0ea5e9", "M2": "#22c55e", "M3": "#6b7280"  # M3 especial
}

# Camiones oficiales (memoria)
CAMP_CAMIONES = ["A1", "A2", "A3", "A4", "A5", "M1", "M2", "M3"]

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger(APP_NAME)

# =============================================================================
# DB POOL (solo si DATA_MODE=db)
# =============================================================================
DB_URL = os.getenv("DATABASE_URL") or os.getenv("DB_URL") or os.getenv("POSTGRES_URL")
if DATA_MODE == "db" and DB_URL:
    if 'pool' not in globals():
        pool = SimpleConnectionPool(1, 10, dsn=DB_URL)
        log.info("Pool Postgres creado.")
else:
    pool = None

def db_conn():
    if not pool:
        raise RuntimeError("DATA_MODE=db pero pool no inicializado")
    return pool.getconn()

def db_put(conn):
    if pool and conn:
        pool.putconn(conn)

# =============================================================================
# APP
# =============================================================================
app = FastAPI(title=APP_NAME)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_ORIGIN", "https://aguaruta.netlify.app"), "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static de fotos (evidencias)
app.mount("/fotos", StaticFiles(directory=FOTOS_DIR, check_dir=False), name="fotos")

# =============================================================================
# MODELOS (Pydantic)
# =============================================================================
class RutaActivaUpdate(BaseModel):
    camion: Optional[str] = None
    nombre: Optional[str] = None
    dia: Optional[str] = None
    telefono: Optional[str] = None
    litros: Optional[int] = None
    latitud: Optional[float] = None
    longitud: Optional[float] = None

class NuevoPunto(BaseModel):
    camion: str
    nombre: str
    dia: str
    litros: int
    telefono: Optional[str] = None
    latitud: Optional[float] = None
    longitud: Optional[float] = None

class Credenciales(BaseModel):
    usuario: str
    password: str

# =============================================================================
# UTILS: JWT, Auditoría, Helpers
# =============================================================================
def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

def _b64d(s: str) -> bytes:
    s += "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s)

def jwt_encode(payload: dict) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    p = payload.copy()
    p["iss"] = JWT_ISSUER
    if "exp" not in p:
        p["exp"] = int((datetime.utcnow() + timedelta(minutes=JWT_EXP_MIN)).timestamp())
    header_b64 = _b64e(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64e(json.dumps(p, separators=(",", ":")).encode())
    sig = hmac.new(JWT_SECRET.encode(), f"{header_b64}.{payload_b64}".encode(), hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64e(sig)}"

def jwt_decode(token: str) -> dict:
    try:
        h_b64, p_b64, s_b64 = token.split(".")
        sig_check = hmac.new(JWT_SECRET.encode(), f"{h_b64}.{p_b64}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(sig_check, _b64d(s_b64)):
            raise ValueError("Firma inválida")
        payload = json.loads(_b64d(p_b64).decode())
        if int(datetime.utcnow().timestamp()) > int(payload["exp"]):
            raise ValueError("Token expirado")
        if payload.get("iss") != JWT_ISSUER:
            raise ValueError("Issuer inválido")
        return payload
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token inválido: {e}")

def require_auth(authorization: str = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Falta token Bearer")
    token = authorization.split(" ", 1)[1]
    return jwt_decode(token)

def audit_log(user: str, action: str, meta: dict):
    """Audita a DB si existe, sino a log."""
    meta_str = json.dumps(meta, ensure_ascii=False)
    ts = datetime.utcnow().isoformat()
    try:
        if DATA_MODE == "db" and pool:
            conn = db_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO auditoria (usuario, accion, metadata, ts_utc)
                VALUES (%s, %s, %s, %s)
            """, (user, action, meta_str, ts))
            conn.commit()
            cur.close()
            db_put(conn)
        else:
            log.info(f"[AUDIT] user={user} action={action} meta={meta_str}")
    except Exception as e:
        log.warning(f"Auditoría fallback log. Error DB: {e}")
        log.info(f"[AUDIT] user={user} action={action} meta={meta_str}")

def ensure_camion(c: Optional[str]) -> Optional[str]:
    if c and c.upper() in CAMION_COLORS:
        return c.upper()
    return c

# =============================================================================
# ENDPOINTS BASE / CONFIG
# =============================================================================
@app.get("/health", response_class=PlainTextResponse)
def health():
    return "ok"

@app.get("/mode", response_class=PlainTextResponse)
def get_mode():
    return DATA_MODE

@app.get("/url", response_class=PlainTextResponse)
def leer_url_actual():
    url_file = BASE_DIR / "url.txt"
    if not url_file.exists():
        return Response(status_code=204)
    try:
        return PlainTextResponse(url_file.read_text(encoding="utf-8").strip())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error leyendo url.txt: {e}")

@app.get("/colores-camion")
def colores_camion():
    return {"status": "ok", "colors": CAMION_COLORS}

# =============================================================================
# LOGIN / USUARIOS (simple)
# =============================================================================
@app.post("/login")
def login(creds: Credenciales):
    """
    Usuarios en DB (tabla usuarios con columnas: usuario, password_hash, rol) o
    fallback de usuario admin:admin si no hay DB.
    """
    usuario = creds.usuario.strip()
    pwd = creds.password.strip()
    ok = False
    rol = "invitado"
    if DATA_MODE == "db" and pool:
        try:
            conn = db_conn()
            cur = conn.cursor()
            cur.execute("SELECT password_hash, rol FROM usuarios WHERE usuario=%s", (usuario,))
            row = cur.fetchone()
            cur.close()
            db_put(conn)
            if row:
                phash, rol = row
                ok = hashlib.sha256(pwd.encode()).hexdigest() == phash
        except Exception as e:
            log.warning(f"Login DB error: {e}")
    else:
        # Fallback
        if usuario == "admin" and pwd == "admin":
            ok = True
            rol = "admin"

    if not ok:
        raise HTTPException(status_code=401, detail="Usuario/clave inválidos")

    token = jwt_encode({"sub": usuario, "rol": rol})
    audit_log(usuario, "login", {"rol": rol})
    return {"status": "ok", "token": token, "rol": rol}

# =============================================================================
# LECTURA DE DATOS: Excel o DB (helpers)
# =============================================================================
RUTAS_COLUMNS = ["id", "camion", "nombre", "dia", "litros", "telefono", "latitud", "longitud"]

def read_rutas_excel() -> pd.DataFrame:
    if not EXCEL_FILE.exists():
        raise HTTPException(status_code=404, detail="No se encontró rutas_activas.xlsx en /data")
    df = pd.read_excel(EXCEL_FILE)
    keep = [c for c in RUTAS_COLUMNS if c in df.columns]
    df = df[keep]
    return df

def write_rutas_excel(df: pd.DataFrame):
    df.to_excel(EXCEL_FILE, index=False)

def read_rutas_db() -> pd.DataFrame:
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, camion, nombre, dia_asignado AS dia, litros_entrega AS litros,
               telefono, latitud, longitud
        FROM rutas_activas
        ORDER BY camion, dia, nombre
    """)
    rows = cur.fetchall()
    cur.close()
    db_put(conn)
    return pd.DataFrame(rows, columns=RUTAS_COLUMNS)

def insert_ruta_db(n: NuevoPunto) -> int:
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO rutas_activas (camion, nombre, dia_asignado, litros_entrega, telefono, latitud, longitud)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """, (n.camion, n.nombre, n.dia, n.litros, n.telefono, n.latitud, n.longitud))
    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    db_put(conn)
    return new_id

def update_ruta_db(id_: int, payload: RutaActivaUpdate):
    campos, valores = [], []
    body = payload.dict(exclude_unset=True)
    for k, v in body.items():
        if k == "dia":
            campos.append("dia_asignado=%s"); valores.append(v)
        elif k == "litros":
            campos.append("litros_entrega=%s"); valores.append(v)
        else:
            campos.append(f"{k}=%s"); valores.append(v)
    if not campos:
        return
    valores.append(id_)
    q = f"UPDATE rutas_activas SET {', '.join(campos)} WHERE id=%s"
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(q, valores)
    conn.commit()
    cur.close()
    db_put(conn)

def delete_ruta_db(id_: int):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM rutas_activas WHERE id=%s", (id_,))
    conn.commit()
    cur.close()
    db_put(conn)

# =============================================================================
# RUTAS ACTIVAS — API
# =============================================================================
@app.get("/rutas-activas")
def get_rutas_activas(
    camion: Optional[str] = Query(None),
    dia: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    only_geocoded: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=5000)
):
    """
    Lista rutas activas (filtrable + paginable).
    - camion, dia, q(nombre/telefono)
    - only_geocoded: True para mapa
    """
    df = read_rutas_db() if DATA_MODE == "db" else read_rutas_excel()
    if camion:
        df = df[df["camion"].str.upper() == camion.upper()]
    if dia:
        df = df[df["dia"].str.upper() == dia.upper()]
    if q:
        qs = str(q).strip().lower()
        df = df[df["nombre"].str.lower().str.contains(qs) | df["telefono"].astype(str).str.contains(qs)]
    if only_geocoded:
        df = df.dropna(subset=["latitud", "longitud"])

    total = len(df)
    df = df.iloc[skip: skip + limit]
    data = df.to_dict(orient="records")
    return {"status": "ok", "total": total, "data": data}

@app.post("/rutas-activas")
def add_ruta_activa(nuevo: NuevoPunto, user=Depends(require_auth)):
    nuevo.camion = ensure_camion(nuevo.camion)
    if DATA_MODE == "db":
        new_id = insert_ruta_db(nuevo)
    else:
        df = read_rutas_excel()
        new_id = int(df["id"].max() + 1 if not df.empty else 1)
        df.loc[len(df)] = {
            "id": new_id,
            "camion": nuevo.camion,
            "nombre": nuevo.nombre,
            "dia": nuevo.dia,
            "litros": nuevo.litros,
            "telefono": nuevo.telefono,
            "latitud": nuevo.latitud,
            "longitud": nuevo.longitud,
        }
        write_rutas_excel(df)
    audit_log(user["sub"], "add_ruta", nuevo.dict())
    return {"status": "ok", "new_id": new_id}

@app.put("/rutas-activas/{id}")
def update_ruta_activa(id: int, payload: RutaActivaUpdate, user=Depends(require_auth)):
    payload.camion = ensure_camion(payload.camion)
    if DATA_MODE == "db":
        update_ruta_db(id, payload)
    else:
        df = read_rutas_excel()
        if id not in df["id"].values:
            raise HTTPException(status_code=404, detail="ID no encontrado")
        for k, v in payload.dict(exclude_unset=True).items():
            df.loc[df["id"] == id, k] = v
        write_rutas_excel(df)
    audit_log(user["sub"], "update_ruta", {"id": id, "changes": payload.dict(exclude_unset=True)})
    return {"status": "ok", "updated_id": id}

@app.delete("/rutas-activas/{id}")
def delete_ruta_activa(id: int, user=Depends(require_auth)):
    if DATA_MODE == "db":
        delete_ruta_db(id)
    else:
        df = read_rutas_excel()
        if id not in df["id"].values:
            raise HTTPException(status_code=404, detail="ID no encontrado")
        df = df[df["id"] != id]
        write_rutas_excel(df)
    audit_log(user["sub"], "delete_ruta", {"id": id})
    return {"status": "ok", "deleted_id": id}

# =============================================================================
# PREVIEW/IMPORT EXCEL (útiles en nube)
# =============================================================================
@app.get("/preview-excel")
def preview_excel(rows: int = 20):
    df = read_rutas_excel()
    return {"status": "ok", "columns": list(df.columns), "rows": df.head(rows).to_dict(orient="records")}

@app.post("/importar-excel-a-db")
def importar_excel_a_db(user=Depends(require_auth)):
    """
    Carga el Excel en la tabla rutas_activas (cuando DATA_MODE=db).
    """
    if DATA_MODE != "db":
        raise HTTPException(status_code=400, detail="Requiere DATA_MODE=db")
    df = read_rutas_excel()
    # Mapa de columnas en DB
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM rutas_activas")
    for _, r in df.iterrows():
        cur.execute("""
            INSERT INTO rutas_activas (id, camion, nombre, dia_asignado, litros_entrega, telefono, latitud, longitud)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            int(r.get("id")) if pd.notna(r.get("id")) else None,
            r.get("camion"), r.get("nombre"), r.get("dia"),
            r.get("litros"), r.get("telefono"), r.get("latitud"), r.get("longitud"),
        ))
    conn.commit()
    cur.close()
    db_put(conn)
    audit_log(user["sub"], "import_excel_to_db", {"rows": len(df)})
    return {"status": "ok", "rows_imported": len(df)}

# =============================================================================
# MAPA (solo geocodificados, popups nombre+litros, color por camión opcional)
# =============================================================================
@app.get("/mapa-puntos")
def mapa_puntos(camion: Optional[str] = None):
    df = read_rutas_db() if DATA_MODE == "db" else read_rutas_excel()
    df = df.dropna(subset=["latitud", "longitud"])
    if camion:
        df = df[df["camion"].str.upper() == camion.upper()]
    # añade color
    df["color"] = df["camion"].apply(lambda c: CAMION_COLORS.get(str(c).upper(), "#1e40af"))
    return {"status": "ok", "data": df.to_dict(orient="records")}

# =============================================================================
# ENTREGAS (APP móvil) + NO ENTREGADAS + ESTADÍSTICAS
# =============================================================================
@app.post("/entregas-app")
async def registrar_entrega_app(
    nombre: str = Form(...),
    camion: str = Form(...),
    litros: int = Form(...),
    estado: int = Form(...),      # 1=entregada, 0/2/3=no entregada (0 y 2 con foto; 3 sin foto)
    fecha: str = Form(...),       # YYYY-MM-DD o ISO
    latitud: Optional[float] = Form(None),
    longitud: Optional[float] = Form(None),
    foto: Optional[UploadFile] = File(None),
    authorization: Optional[str] = Header(None),
):
    # guardar foto
    foto_path_rel = None
    if foto and foto.filename:
        ext = Path(foto.filename).suffix.lower() or ".jpg"
        fname = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex}{ext}"
        dest = FOTOS_DIR / fname
        with dest.open("wb") as f:
            shutil.copyfileobj(foto.file, f)
        foto_path_rel = f"/fotos/{fname}"

    # persistir si hay DB
    new_id = None
    try:
        if DATA_MODE == "db" and pool:
            conn = db_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO entregas_app (nombre, camion, litros, estado, fecha, latitud, longitud, foto_path)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
            """, (nombre, camion, litros, estado, fecha, latitud, longitud, foto_path_rel))
            new_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            db_put(conn)
    except Exception as e:
        log.error(f"POST /entregas-app error DB: {e}")

    user = {"sub": "invitado"}
    if authorization and authorization.startswith("Bearer "):
        try:
            user = jwt_decode(authorization.split(" ", 1)[1])
        except Exception:
            pass

    audit_log(user["sub"], "registrar_entrega", {
        "nombre": nombre, "camion": camion, "estado": estado, "fecha": fecha, "foto": bool(foto_path_rel)
    })

    return {
        "status": "ok",
        "id": new_id,
        "nombre": nombre,
        "camion": camion,
        "litros": litros,
        "estado": estado,
        "fecha": fecha,
        "latitud": latitud,
        "longitud": longitud,
        "foto": foto_path_rel,
    }

@app.get("/no-entregadas")
def no_entregadas(
    dia: Optional[str] = None,
    camion: Optional[str] = None,
    skip: int = 0,
    limit: int = 500
):
    """
    Lista no entregadas (estados 0,2,3). Requiere DB para evidencias persistentes.
    """
    if DATA_MODE != "db":
        # Fallback: devolver vacío si no hay DB
        return {"status": "ok", "total": 0, "data": []}
    conn = db_conn()
    cur = conn.cursor()
    q = """SELECT id, nombre, camion, litros, estado, fecha, latitud, longitud, foto_path
           FROM entregas_app WHERE estado IN (0,2,3)"""
    params = []
    if dia:
        q += " AND fecha::text LIKE %s"; params.append(f"%{dia}%")
    if camion:
        q += " AND camion=%s"; params.append(camion)
    q += " ORDER BY fecha DESC, camion LIMIT %s OFFSET %s"
    params += [limit, skip]
    cur.execute(q, params)
    rows = cur.fetchall()
    cur.close()
    db_put(conn)
    cols = ["id","nombre","camion","litros","estado","fecha","latitud","longitud","foto"]
    df = pd.DataFrame(rows, columns=cols)
    return {"status": "ok", "total": len(df), "data": df.to_dict(orient="records")}

@app.get("/graficos")
def graficos_resumen(camion: Optional[str] = None, dia: Optional[str] = None):
    """
    Conteo por tipo de entrega: 1 entregada, 0/2/3 no entregada (distintos motivos).
    Requiere DB para datos en tiempo real; si no hay DB, usa heurística vacía.
    """
    result = {"entregada": 0, "no_entregada_foto": 0, "no_ubicado": 0, "no_protocolo": 0}
    if DATA_MODE != "db":
        return {"status": "ok", "data": result}

    conn = db_conn()
    cur = conn.cursor()
    q = "SELECT estado, COUNT(*) FROM entregas_app WHERE 1=1"
    params = []
    if camion:
        q += " AND camion=%s"; params.append(camion)
    if dia:
        q += " AND fecha::text LIKE %s"; params.append(f"%{dia}%")
    q += " GROUP BY estado"
    cur.execute(q, params)
    for estado, cnt in cur.fetchall():
        if estado == 1:
            result["entregada"] += cnt
        elif estado in (0,2):
            result["no_entregada_foto"] += cnt
        elif estado == 3:
            result["no_ubicado"] += cnt
    cur.close()
    db_put(conn)
    # no_protocolo lo dejamos disponible si luego agregas estado 4
    return {"status": "ok", "data": result}

@app.get("/estadisticas-camion")
def estadisticas_camion(camion: Optional[str] = None, fecha_desde: Optional[str] = None, fecha_hasta: Optional[str] = None):
    """
    Litros por día y por camión (para CamionEstadisticas.js)
    """
    if DATA_MODE != "db":
        return {"status": "ok", "data": []}

    conn = db_conn()
    cur = conn.cursor()
    q = """
        SELECT camion, fecha::date AS dia, SUM(litros) AS litros_dia, COUNT(*) AS entregas
        FROM entregas_app WHERE 1=1
    """
    params = []
    if camion:
        q += " AND camion=%s"; params.append(camion)
    if fecha_desde:
        q += " AND fecha::date >= %s"; params.append(fecha_desde)
    if fecha_hasta:
        q += " AND fecha::date <= %s"; params.append(fecha_hasta)
    q += " GROUP BY camion, dia ORDER BY dia ASC"
    cur.execute(q, params)
    rows = cur.fetchall()
    cur.close()
    db_put(conn)
    cols = ["camion","dia","litros","entregas"]
    df = pd.DataFrame(rows, columns=cols)
    return {"status": "ok", "data": df.to_dict(orient="records")}

@app.get("/comparacion-semanal")
def comparacion_semanal(camion: Optional[str] = None, semanas: int = 8):
    """
    Devuelve litros por semana (ISO) y por camión.
    """
    if DATA_MODE != "db":
        return {"status": "ok", "data": []}
    conn = db_conn()
    cur = conn.cursor()
    q = """
        SELECT camion, EXTRACT(ISOWEEK FROM fecha::date)::int AS semana,
               DATE_TRUNC('week', fecha::date)::date AS lunes, SUM(litros) AS litros
        FROM entregas_app WHERE 1=1
    """
    params = []
    if camion:
        q += " AND camion=%s"; params.append(camion)
    q += " GROUP BY camion, semana, lunes ORDER BY lunes DESC LIMIT %s"
    params.append(semanas)
    cur.execute(q, params)
    rows = cur.fetchall()
    cur.close()
    db_put(conn)
    cols = ["camion","semana","lunes","litros"]
    df = pd.DataFrame(rows, columns=cols)
    return {"status": "ok", "data": df.to_dict(orient="records")}

# =============================================================================
# AUDITORÍA
# =============================================================================
@app.get("/auditoria")
def auditoria_list(user=Depends(require_auth), skip: int = 0, limit: int = 200):
    if DATA_MODE != "db":
        # Si no hay DB, devolvemos logs fingidos
        return {"status": "ok", "total": 0, "data": []}
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT usuario, accion, metadata, ts_utc
        FROM auditoria ORDER BY ts_utc DESC LIMIT %s OFFSET %s
    """, (limit, skip))
    rows = cur.fetchall()
    cur.close()
    db_put(conn)
    cols = ["usuario","accion","metadata","ts_utc"]
    df = pd.DataFrame(rows, columns=cols)
    # Metadata a dict
    def meta_parse(m):
        try: return json.loads(m)
        except: return {"raw": m}
    out = []
    for _, r in df.iterrows():
        out.append({
            "usuario": r["usuario"],
            "accion": r["accion"],
            "metadata": meta_parse(r["metadata"]),
            "ts_utc": r["ts_utc"].isoformat() if hasattr(r["ts_utc"], "isoformat") else r["ts_utc"]
        })
    return {"status": "ok", "total": len(out), "data": out}

# =============================================================================
# REDISTRIBUCIÓN (esqueleto, listo para conectar lógica)
# =============================================================================
@app.post("/redistribuir")
def redistribuir_puntos(
    incluir_existentes: bool = Body(True),
    excluir_m3: bool = Body(True),
    user=Depends(require_auth)
):
    """
    Esqueleto: aquí engancha la lógica de redistribución A1-A5, M1, M2 (excluyendo M3).
    Retorna un dict con el nuevo plan (no persiste).
    """
    df = read_rutas_db() if DATA_MODE == "db" else read_rutas_excel()
    if excluir_m3:
        df = df[df["camion"].str.upper() != "M3"]
    # TODO: aquí implementar tu algoritmo de balanceo por litros/personas/tiempo.
    resumen = df.groupby("camion")["litros"].sum().reset_index().to_dict(orient="records")
    audit_log(user["sub"], "redistribuir_preview", {"filas": len(df)})
    return {"status": "ok", "resumen": resumen, "mensaje": "Esqueleto OK. Falta algoritmo de balanceo."}
