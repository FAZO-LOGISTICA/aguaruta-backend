# main.py — AguaRuta Backend (ultra completo)
# Autor: Equipo AguaRuta — 2025-09-28
# Modo de operación mixto: Excel o Postgres (DATA_MODE=excel|db)
# Características:
# - Rutas Activas CRUD (Excel/DB), Mapa con colores por camión
# - Entregas App (foto + GPS) con persistencia (DB)
# - Estadísticas y Gráficos, No Entregadas, Comparación Semanal
# - Usuarios avanzados (CRUD, roles admin/operador/visor)
# - Auditoría avanzada (filtros por usuario/fechas + export Excel/PDF)
# - Exportaciones de estadísticas
# - Alertas operativas (sobrecarga y no entregadas altas)
# - Preview/Import Excel -> DB, Colores por camión
# - Bootstrap opcional de DB con AGUARUTA_BOOTSTRAP_DB=1

import os
import uuid
import shutil
import logging
import hashlib
import json
import base64
import hmac
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import (
    FastAPI, HTTPException, UploadFile, File, Form, Body,
    Depends, Header, Query
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import pandas as pd
from io import BytesIO
from reportlab.pdfgen import canvas

# Postgres opcional
import psycopg2
from psycopg2.pool import SimpleConnectionPool

# =============================================================================
# CONFIG / RUTAS LOCALES
# =============================================================================
APP_NAME = "AguaRuta Backend"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

EXCEL_FILE = DATA_DIR / "rutas_activas.xlsx"
FOTOS_DIR = BASE_DIR / "fotos" / "evidencias"
FOTOS_DIR.mkdir(parents=True, exist_ok=True)

# Modo de datos: "excel" (por defecto) o "db"
DATA_MODE = os.getenv("DATA_MODE", "excel").lower().strip()

# JWT
JWT_SECRET = os.getenv("JWT_SECRET", "aguaruta_super_secreto")
JWT_EXP_MIN = int(os.getenv("JWT_EXP_MIN", "720"))  # 12 horas

# Colores por camión (mapa)
CAMION_COLORS: Dict[str, str] = {
    "A1": "#2563eb", "A2": "#059669", "A3": "#dc2626", "A4": "#f59e0b", "A5": "#7c3aed",
    "M1": "#0ea5e9", "M2": "#22c55e", "M3": "#6b7280"
}

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger(APP_NAME)

# =============================================================================
# DB (solo si DATA_MODE=db)
# =============================================================================
DB_URL = os.getenv("DATABASE_URL")
pool = SimpleConnectionPool(1, 10, dsn=DB_URL) if DATA_MODE == "db" and DB_URL else None

def db_conn():
    if not pool:
        raise RuntimeError("DB no inicializada (DATA_MODE=db y DATABASE_URL requerido)")
    return pool.getconn()

def db_put(conn):
    if pool and conn:
        pool.putconn(conn)

# =============================================================================
# APP + CORS + STATIC
# =============================================================================
app = FastAPI(title=APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_ORIGIN", "https://aguaruta.netlify.app"), "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

class UsuarioCreate(BaseModel):
    usuario: str
    password: str
    rol: str  # admin|operador|visor

# =============================================================================
# JWT Helpers
# =============================================================================
def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

def _b64d(s: str) -> bytes:
    s += "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s)

def jwt_encode(payload: dict) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    p = payload.copy()
    if "exp" not in p:
        p["exp"] = int((datetime.utcnow() + timedelta(minutes=JWT_EXP_MIN)).timestamp())
    h_b64 = _b64e(json.dumps(header, separators=(",", ":")).encode())
    p_b64 = _b64e(json.dumps(p, separators=(",", ":")).encode())
    sig = hmac.new(JWT_SECRET.encode(), f"{h_b64}.{p_b64}".encode(), hashlib.sha256).digest()
    return f"{h_b64}.{p_b64}.{_b64e(sig)}"

def jwt_decode(token: str) -> dict:
    try:
        h_b64, p_b64, s_b64 = token.split(".")
        sig_check = hmac.new(JWT_SECRET.encode(), f"{h_b64}.{p_b64}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(sig_check, _b64d(s_b64)):
            raise ValueError("Firma inválida")
        payload = json.loads(_b64d(p_b64).decode())
        if int(datetime.utcnow().timestamp()) > int(payload["exp"]):
            raise ValueError("Token expirado")
        return payload
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token inválido: {e}")

def require_auth(authorization: str = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Falta token Bearer")
    token = authorization.split(" ", 1)[1]
    return jwt_decode(token)

def require_admin(user=Depends(require_auth)):
    if user.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Requiere rol admin")
    return user

# =============================================================================
# AUDITORÍA
# =============================================================================
def audit_log(user: str, action: str, meta: dict):
    """
    Intenta persistir auditoría en DB; si no hay DB, loguea a consola.
    """
    ts = datetime.utcnow().isoformat()
    meta_json = json.dumps(meta, ensure_ascii=False)
    if DATA_MODE == "db" and pool:
        try:
            conn = db_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO auditoria (usuario, accion, metadata, ts_utc)
                VALUES (%s, %s, %s, %s)
            """, (user, action, meta_json, ts))
            conn.commit()
            cur.close()
            db_put(conn)
        except Exception as e:
            log.warning(f"Auditoría DB error, fallback log: {e}")
            log.info(f"[AUDIT] user={user} action={action} meta={meta_json}")
    else:
        log.info(f"[AUDIT] user={user} action={action} meta={meta_json}")

# =============================================================================
# HELPERS Rutas (Excel/DB)
# =============================================================================
RUTAS_COLUMNS = ["id", "camion", "nombre", "dia", "litros", "telefono", "latitud", "longitud"]

def ensure_camion(c: Optional[str]) -> Optional[str]:
    if c:
        c = str(c).upper().strip()
        return c
    return c

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
        INSERT INTO rutas_activas (camion, nombre, dia_asignado, litros_entrega, telefono, latitud, longitud, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())
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
    campos.append("updated_at=NOW()")
    conn = db_conn()
    cur = conn.cursor()
    q = f"UPDATE rutas_activas SET {', '.join(campos)} WHERE id=%s"
    valores.append(id_)
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
# ENDPOINTS BASE / UTILIDADES
# =============================================================================
@app.get("/health", response_class=PlainTextResponse)
def health():
    return "ok"

@app.get("/mode", response_class=PlainTextResponse)
def get_mode():
    return DATA_MODE

@app.get("/colores-camion")
def colores_camion():
    return {"status": "ok", "colors": CAMION_COLORS}

@app.get("/url", response_class=PlainTextResponse)
def leer_url_actual():
    url_file = BASE_DIR / "url.txt"
    if not url_file.exists():
        return Response(status_code=204)
    try:
        return PlainTextResponse(url_file.read_text(encoding="utf-8").strip())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error leyendo url.txt: {e}")

# =============================================================================
# LOGIN / USUARIOS AVANZADOS (CRUD)
# =============================================================================
@app.post("/login")
def login(creds: Credenciales):
    usuario = creds.usuario.strip()
    pwd = creds.password.strip()
    phash = hashlib.sha256(pwd.encode()).hexdigest()

    if DATA_MODE == "db" and pool:
        conn = db_conn()
        cur = conn.cursor()
        cur.execute("SELECT password_hash, rol, active FROM usuarios WHERE usuario=%s", (usuario,))
        row = cur.fetchone()
        cur.close(); db_put(conn)
        if not row or row[0] != phash or row[2] is False:
            raise HTTPException(status_code=401, detail="Credenciales inválidas o usuario inactivo")
        rol = row[1]
    else:
        # Fallback simple sin DB
        if usuario == "admin" and pwd == "admin":
            rol = "admin"
        else:
            raise HTTPException(status_code=401, detail="Credenciales inválidas")

    token = jwt_encode({"sub": usuario, "rol": rol})
    audit_log(usuario, "login", {"rol": rol})
    return {"status": "ok", "token": token, "rol": rol}

class UsuarioUpdate(BaseModel):
    password: Optional[str] = None
    rol: Optional[str] = None
    active: Optional[bool] = None

@app.post("/usuarios")
def crear_usuario(u: UsuarioCreate, user=Depends(require_admin)):
    if DATA_MODE != "db":
        raise HTTPException(status_code=400, detail="Solo DB soporta usuarios avanzados")
    phash = hashlib.sha256(u.password.encode()).hexdigest()
    conn = db_conn(); cur = conn.cursor()
    cur.execute("INSERT INTO usuarios (usuario,password_hash,rol,active) VALUES (%s,%s,%s,TRUE)",
                (u.usuario, phash, u.rol))
    conn.commit(); cur.close(); db_put(conn)
    audit_log(user["sub"], "crear_usuario", {"usuario": u.usuario, "rol": u.rol})
    return {"status": "ok"}

@app.get("/usuarios")
def listar_usuarios(user=Depends(require_admin)):
    if DATA_MODE != "db":
        # Fallback mínimo
        return {"status": "ok", "data": [{"usuario": "admin", "rol": "admin", "active": True}]}
    conn = db_conn(); cur = conn.cursor()
    cur.execute("SELECT usuario, rol, active, created_at FROM usuarios ORDER BY usuario")
    rows = cur.fetchall(); cur.close(); db_put(conn)
    data = [{"usuario": r[0], "rol": r[1], "active": r[2], "created_at": r[3]} for r in rows]
    return {"status": "ok", "data": data}

@app.put("/usuarios/{usuario}")
def actualizar_usuario(usuario: str, u: UsuarioUpdate, user=Depends(require_admin)):
    if DATA_MODE != "db":
        raise HTTPException(status_code=400, detail="Solo DB soporta usuarios avanzados")
    sets, vals = [], []
    if u.password is not None:
        sets.append("password_hash=%s"); vals.append(hashlib.sha256(u.password.encode()).hexdigest())
    if u.rol is not None:
        sets.append("rol=%s"); vals.append(u.rol)
    if u.active is not None:
        sets.append("active=%s"); vals.append(u.active)
    if not sets:
        raise HTTPException(400, "Nada que actualizar")
    vals.append(usuario)
    conn = db_conn(); cur = conn.cursor()
    cur.execute(f"UPDATE usuarios SET {', '.join(sets)} WHERE usuario=%s", vals)
    conn.commit(); cur.close(); db_put(conn)
    audit_log(user["sub"], "actualizar_usuario", {"usuario": usuario, "changes": u.dict(exclude_unset=True)})
    return {"status": "ok"}

@app.delete("/usuarios/{usuario}")
def eliminar_usuario(usuario: str, user=Depends(require_admin)):
    if DATA_MODE != "db":
        raise HTTPException(status_code=400, detail="Solo DB soporta usuarios avanzados")
    conn = db_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM usuarios WHERE usuario=%s", (usuario,))
    conn.commit(); cur.close(); db_put(conn)
    audit_log(user["sub"], "eliminar_usuario", {"usuario": usuario})
    return {"status": "ok"}

# =============================================================================
# RUTAS ACTIVAS (CRUD), con filtros/paginación y dual Excel/DB
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
    Filtros: camion, dia, q (nombre/telefono), only_geocoded.
    """
    df = read_rutas_db() if DATA_MODE == "db" else read_rutas_excel()
    if camion:
        df = df[df["camion"].astype(str).str.upper() == camion.upper()]
    if dia:
        df = df[df["dia"].astype(str).str.upper() == dia.upper()]
    if q:
        qs = str(q).strip().lower()
        df = df[
            df["nombre"].astype(str).str.lower().str.contains(qs) |
            df["telefono"].astype(str).str.contains(qs)
        ]
    if only_geocoded:
        df = df.dropna(subset=["latitud", "longitud"])

    total = len(df)
    df = df.iloc[skip: skip + limit]
    return {"status": "ok", "total": total, "data": df.to_dict(orient="records")}

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
# PREVIEW / IMPORT Excel
# =============================================================================
@app.get("/preview-excel")
def preview_excel(rows: int = 20):
    df = read_rutas_excel()
    return {"status": "ok", "columns": list(df.columns), "rows": df.head(rows).to_dict(orient="records")}

@app.post("/importar-excel-a-db")
def importar_excel_a_db(user=Depends(require_admin)):
    """
    Carga el Excel en la tabla rutas_activas (solo DATA_MODE=db).
    """
    if DATA_MODE != "db":
        raise HTTPException(status_code=400, detail="Requiere DATA_MODE=db")
    df = read_rutas_excel()
    conn = db_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM rutas_activas")
    for _, r in df.iterrows():
        cur.execute("""
            INSERT INTO rutas_activas (id, camion, nombre, dia_asignado, litros_entrega, telefono, latitud, longitud, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW())
        """, (
            int(r.get("id")) if pd.notna(r.get("id")) else None,
            r.get("camion"), r.get("nombre"), r.get("dia"),
            r.get("litros"), r.get("telefono"), r.get("latitud"), r.get("longitud")
        ))
    conn.commit(); cur.close(); db_put(conn)
    audit_log(user["sub"], "import_excel_to_db", {"rows": len(df)})
    return {"status": "ok", "rows_imported": len(df)}

# =============================================================================
# MAPA (geocodificados) + color por camión
# =============================================================================
@app.get("/mapa-puntos")
def mapa_puntos(camion: Optional[str] = None):
    df = read_rutas_db() if DATA_MODE == "db" else read_rutas_excel()
    df = df.dropna(subset=["latitud", "longitud"])
    if camion:
        df = df[df["camion"].astype(str).str.upper() == camion.upper()]
    df["color"] = df["camion"].astype(str).str.upper().apply(lambda c: CAMION_COLORS.get(c, "#1e40af"))
    # popups: solo nombre + litros (confirmado)
    out = df.to_dict(orient="records")
    return {"status": "ok", "data": out}

# =============================================================================
# ENTREGAS APP (foto + GPS) + No Entregadas + Estadísticas
# =============================================================================
@app.post("/entregas-app")
async def registrar_entrega_app(
    nombre: str = Form(...),
    camion: str = Form(...),
    litros: int = Form(...),
    estado: int = Form(...),      # 1=entregada, 0/2 no entregada (con foto), 3 no ubicado (sin foto)
    fecha: str = Form(...),       # YYYY-MM-DD o ISO
    latitud: Optional[float] = Form(None),
    longitud: Optional[float] = Form(None),
    foto: Optional[UploadFile] = File(None),
    authorization: Optional[str] = Header(None),
):
    # Guardar foto (si viene)
    foto_path_rel = None
    if foto and foto.filename:
        ext = Path(foto.filename).suffix.lower() or ".jpg"
        fname = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex}{ext}"
        dest = FOTOS_DIR / fname
        with dest.open("wb") as f:
            shutil.copyfileobj(foto.file, f)
        foto_path_rel = f"/fotos/{fname}"

    # Persistir en DB si corresponde
    new_id = None
    if DATA_MODE == "db" and pool:
        try:
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

    # Auditoría
    actor = "invitado"
    if authorization and authorization.startswith("Bearer "):
        try:
            actor = jwt_decode(authorization.split(" ", 1)[1]).get("sub", "invitado")
        except Exception:
            pass
    audit_log(actor, "registrar_entrega", {
        "nombre": nombre, "camion": camion, "litros": litros, "estado": estado, "fecha": fecha, "foto": bool(foto_path_rel)
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
    Lista no entregadas (estados 0,2,3).
    Requiere DB para evidencias persistentes; en modo Excel devuelve vacío.
    """
    if DATA_MODE != "db":
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
    cur.close(); db_put(conn)
    cols = ["id","nombre","camion","litros","estado","fecha","latitud","longitud","foto"]
    df = pd.DataFrame(rows, columns=cols)
    return {"status": "ok", "total": len(df), "data": df.to_dict(orient="records")}

@app.get("/graficos")
def graficos_resumen(camion: Optional[str] = None, dia: Optional[str] = None):
    """
    Conteo por tipo de entrega.
    Requiere DB; en Excel devolvemos 0s.
    """
    result = {"entregada": 0, "no_entregada_foto": 0, "no_ubicado": 0}
    if DATA_MODE != "db":
        return {"status": "ok", "data": result}
    conn = db_conn(); cur = conn.cursor()
    q = "SELECT estado, COUNT(*) FROM entregas_app WHERE 1=1"
    params=[]
    if camion: q += " AND camion=%s"; params.append(camion)
    if dia: q += " AND fecha::date = %s"; params.append(dia)
    q += " GROUP BY estado"
    cur.execute(q, params)
    for estado, cnt in cur.fetchall():
        if estado == 1: result["entregada"] += cnt
        elif estado in (0,2): result["no_entregada_foto"] += cnt
        elif estado == 3: result["no_ubicado"] += cnt
    cur.close(); db_put(conn)
    return {"status": "ok", "data": result}

@app.get("/estadisticas-camion")
def estadisticas_camion(camion: Optional[str] = None, fecha_desde: Optional[str] = None, fecha_hasta: Optional[str] = None):
    if DATA_MODE != "db":
        return {"status": "ok", "data": []}
    conn = db_conn(); cur = conn.cursor()
    q = """
        SELECT camion, fecha::date AS dia, SUM(litros) AS litros_dia, COUNT(*) AS entregas
        FROM entregas_app WHERE 1=1
    """
    params=[]
    if camion: q += " AND camion=%s"; params.append(camion)
    if fecha_desde: q += " AND fecha::date >= %s"; params.append(fecha_desde)
    if fecha_hasta: q += " AND fecha::date <= %s"; params.append(fecha_hasta)
    q += " GROUP BY camion, dia ORDER BY dia ASC"
    cur.execute(q, params)
    rows = cur.fetchall(); cur.close(); db_put(conn)
    cols = ["camion","dia","litros","entregas"]
    df = pd.DataFrame(rows, columns=cols)
    return {"status": "ok", "data": df.to_dict(orient="records")}

@app.get("/comparacion-semanal")
def comparacion_semanal(camion: Optional[str] = None, semanas: int = 8):
    if DATA_MODE != "db":
        return {"status": "ok", "data": []}
    conn = db_conn(); cur = conn.cursor()
    q = """
        SELECT camion, EXTRACT(ISOWEEK FROM fecha::date)::int AS semana,
               DATE_TRUNC('week', fecha::date)::date AS lunes, SUM(litros) AS litros
        FROM entregas_app WHERE 1=1
    """
    params=[]
    if camion: q += " AND camion=%s"; params.append(camion)
    q += " GROUP BY camion, semana, lunes ORDER BY lunes DESC LIMIT %s"
    params.append(semanas)
    cur.execute(q, params)
    rows = cur.fetchall(); cur.close(); db_put(conn)
    cols = ["camion","semana","lunes","litros"]
    df = pd.DataFrame(rows, columns=cols)
    return {"status": "ok", "data": df.to_dict(orient="records")}

# =============================================================================
# EXPORTACIONES
# =============================================================================
@app.get("/estadisticas/export")
def export_estadisticas(formato: str = "excel", user=Depends(require_admin)):
    """
    Ejemplo de export de estadísticas; amplíalo con consultas reales que uses.
    """
    if DATA_MODE == "db":
        # Simple ejemplo: litros totales por camión (últimos 7 días)
        conn = db_conn(); cur = conn.cursor()
        cur.execute("""
            SELECT camion, SUM(litros) AS litros
            FROM entregas_app
            WHERE fecha >= NOW() - INTERVAL '7 days'
            GROUP BY camion ORDER BY camion
        """)
        rows = cur.fetchall(); cur.close(); db_put(conn)
        df = pd.DataFrame(rows, columns=["camion","litros"])
    else:
        df = pd.DataFrame([{"camion": "A1", "litros": 0}])

    if formato == "excel":
        out = BytesIO(); df.to_excel(out, index=False); out.seek(0)
        return StreamingResponse(out,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=estadisticas.xlsx"})
    elif formato == "pdf":
        out = BytesIO(); c = canvas.Canvas(out); y = 800
        c.drawString(30, y, "Estadísticas (últimos 7 días)"); y -= 25
        for _, r in df.iterrows():
            c.drawString(30, y, f"{r['camion']}: {r['litros']} L"); y -= 18
        c.save(); out.seek(0)
        return StreamingResponse(out, media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=estadisticas.pdf"})
    else:
        raise HTTPException(status_code=400, detail="Formato inválido")

# =============================================================================
# AUDITORÍA AVANZADA (filtros + export)
# =============================================================================
@app.get("/auditoria")
def auditoria_list(
    user=Depends(require_admin),
    usuario: Optional[str] = None,
    fecha_desde: Optional[str] = None,
    fecha_hasta: Optional[str] = None,
    limit: int = 500
):
    if DATA_MODE != "db":
        return {"status": "ok", "data": []}
    q = "SELECT usuario, accion, metadata, ts_utc FROM auditoria WHERE 1=1"
    params=[]
    if usuario: q += " AND usuario=%s"; params.append(usuario)
    if fecha_desde: q += " AND ts_utc >= %s"; params.append(fecha_desde)
    if fecha_hasta: q += " AND ts_utc <= %s"; params.append(fecha_hasta)
    q += " ORDER BY ts_utc DESC LIMIT %s"
    params.append(limit)
    conn = db_conn(); cur = conn.cursor()
    cur.execute(q, params)
    rows = cur.fetchall(); cur.close(); db_put(conn)
    data = [{"usuario": r[0], "accion": r[1], "metadata": r[2], "ts": r[3]} for r in rows]
    return {"status": "ok", "data": data}

@app.get("/auditoria/export")
def auditoria_export(formato: str = "excel", user=Depends(require_admin)):
    data = auditoria_list(user)["data"]
    df = pd.DataFrame(data)
    if formato == "excel":
        out = BytesIO(); df.to_excel(out, index=False); out.seek(0)
        return StreamingResponse(out,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=auditoria.xlsx"})
    elif formato == "pdf":
        out = BytesIO(); c = canvas.Canvas(out); y = 800
        c.drawString(30, y, "Auditoría"); y -= 25
        for row in data[:70]:
            c.drawString(30, y, f"{row}"); y -= 12
            if y < 40: c.showPage(); y = 800
        c.save(); out.seek(0)
        return StreamingResponse(out, media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=auditoria.pdf"})
    else:
        raise HTTPException(status_code=400, detail="Formato inválido")

# =============================================================================
# ALERTAS (sobrecarga y no entregadas > umbral)
# =============================================================================
@app.get("/alertas")
def alertas(umbral_litros: int = 45000, umbral_no_ent: float = 0.2):
    """
    - Alerta si algún camión supera 'umbral_litros' en un día.
    - Alerta si no entregadas/total > umbral_no_ent (20% por defecto) por día.
    Requiere DB.
    """
    alerts=[]
    if DATA_MODE == "db" and pool:
        conn = db_conn(); cur = conn.cursor()
        try:
            cur.execute("""
                SELECT camion, fecha::date, SUM(litros)
                FROM entregas_app
                GROUP BY camion, fecha::date
            """)
            for camion, dia, litros in cur.fetchall():
                if litros and litros > umbral_litros:
                    alerts.append(f"Sobrecarga: {camion} el {dia} con {litros} L")

            cur.execute("""
                SELECT fecha::date, COUNT(*) FILTER(WHERE estado!=1) AS no_ok, COUNT(*) AS tot
                FROM entregas_app GROUP BY fecha::date
            """)
            for dia, no_ok, tot in cur.fetchall():
                if tot and (no_ok / tot) > umbral_no_ent:
                    pct = round((no_ok / tot) * 100, 1)
                    alerts.append(f"No entregadas altas: {dia} -> {no_ok}/{tot} ({pct}%)")
        finally:
            cur.close(); db_put(conn)
    return {"status": "ok", "alertas": alerts}

# =============================================================================
# BOOTSTRAP DB (opcional) — CREA TABLAS Y USUARIO ADMIN SI NO EXISTEN
# =============================================================================
def _exec_sql(sql: str, params=None):
    conn = db_conn(); cur = conn.cursor()
    cur.execute(sql, params or [])
    conn.commit(); cur.close(); db_put(conn)

if DATA_MODE == "db" and pool and os.getenv("AGUARUTA_BOOTSTRAP_DB", "0") == "1":
    log.info("Bootstrapping DB…")
    ddl = """
    CREATE TABLE IF NOT EXISTS usuarios (
      usuario TEXT PRIMARY KEY,
      password_hash TEXT NOT NULL,
      rol TEXT NOT NULL DEFAULT 'operador' CHECK (rol IN ('admin','operador','visor')),
      active BOOLEAN NOT NULL DEFAULT TRUE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS auditoria (
      id BIGSERIAL PRIMARY KEY,
      usuario TEXT REFERENCES usuarios(usuario) ON DELETE SET NULL,
      accion TEXT NOT NULL,
      metadata JSONB,
      ts_utc TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_auditoria_ts ON auditoria(ts_utc DESC);
    CREATE INDEX IF NOT EXISTS idx_auditoria_usuario ON auditoria(usuario);
    CREATE INDEX IF NOT EXISTS idx_auditoria_meta_gin ON auditoria USING GIN (metadata);

    CREATE TABLE IF NOT EXISTS rutas_activas (
      id SERIAL PRIMARY KEY,
      camion TEXT, nombre TEXT, dia_asignado TEXT,
      litros_entrega INTEGER, telefono TEXT,
      latitud DOUBLE PRECISION, longitud DOUBLE PRECISION,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_rutas_camion ON rutas_activas(camion);
    CREATE INDEX IF NOT EXISTS idx_rutas_dia ON rutas_activas(dia_asignado);

    CREATE TABLE IF NOT EXISTS entregas_app (
      id BIGSERIAL PRIMARY KEY,
      nombre TEXT, camion TEXT, litros INTEGER, estado INTEGER,
      fecha TIMESTAMPTZ NOT NULL,
      latitud DOUBLE PRECISION, longitud DOUBLE PRECISION,
      foto_path TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_entregas_fecha ON entregas_app(fecha);
    CREATE INDEX IF NOT EXISTS idx_entregas_camion_fecha ON entregas_app(camion, fecha);
    """
    _exec_sql(ddl)
    admin_user = os.getenv("ADMIN_USER", "admin")
    admin_pass = os.getenv("ADMIN_PASS", "admin")
    phash = hashlib.sha256(admin_pass.encode()).hexdigest()
    _exec_sql("""
      INSERT INTO usuarios(usuario,password_hash,rol,active)
      VALUES (%s,%s,'admin',TRUE)
      ON CONFLICT (usuario) DO NOTHING
    """, (admin_user, phash))
    log.info("Bootstrap DB OK")
