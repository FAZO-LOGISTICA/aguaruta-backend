# main.py — AguaRuta Backend (ULTRA COMPLETO)
# Fecha: 2025-10-02
# Incluye:
# - CORS FIX (Netlify -> Render)
# - CRUD Rutas Activas (DB/Excel) + filtros + sincronización opcional
# - Mapa con colores por camión
# - Usuarios (JWT login + CRUD roles)
# - Auditoría (filtros + export Excel/PDF)
# - Entregas App (POST + GET) con foto + GPS
# - Estadísticas: gráficos, por camión, comparaciones
# - No Entregadas
# - Exportaciones Excel/PDF
# - Endpoints de compatibilidad: /entregas-todas, GET /entregas-app, GET /entregas, /camiones
# - Preview/Import Excel/CSV -> DB
# - Bootstrap DB opcional

import os, uuid, shutil, logging, hashlib, json, base64, hmac
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import pandas as pd
from io import BytesIO
from reportlab.pdfgen import canvas

import psycopg2
from psycopg2.pool import SimpleConnectionPool

# =============================================================================
# CONFIG
# =============================================================================
APP_NAME = "AguaRuta Backend"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"; DATA_DIR.mkdir(parents=True, exist_ok=True)

EXCEL_FILE = DATA_DIR / "rutas_activas.xlsx"
CSV_FILE   = DATA_DIR / "rutas_activas.csv"
FOTOS_DIR  = BASE_DIR / "fotos" / "evidencias"; FOTOS_DIR.mkdir(parents=True, exist_ok=True)

# DATA_MODE: "db" (prod) | "excel" (fallback local)
DATA_MODE = os.getenv("DATA_MODE", "db").lower().strip()
DB_URL    = os.getenv("DATABASE_URL")

JWT_SECRET  = os.getenv("JWT_SECRET", "aguaruta_super_secreto")
JWT_EXP_MIN = int(os.getenv("JWT_EXP_MIN", "720"))  # 12h

CAMION_COLORS: Dict[str, str] = {
    "A1": "#2563eb", "A2": "#059669", "A3": "#dc2626", "A4": "#f59e0b", "A5": "#7c3aed",
    "M1": "#0ea5e9", "M2": "#22c55e", "M3": "#6b7280"
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(APP_NAME)

# =============================================================================
# DB POOL (solo si DATA_MODE = db y hay URL)
# =============================================================================
pool = SimpleConnectionPool(1, 10, dsn=DB_URL) if (DATA_MODE == "db" and DB_URL) else None

def db_conn():
    if not pool:
        raise RuntimeError("DB no inicializada (DATA_MODE=db y DATABASE_URL requerido)")
    return pool.getconn()

def db_put(conn):
    if pool and conn:
        pool.putconn(conn)

# =============================================================================
# APP + CORS (poner arriba)
# =============================================================================
app = FastAPI(title=APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://aguaruta.netlify.app",  # producción
        "http://localhost:5173",         # dev vite
        "*"                               # fallback
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/fotos", StaticFiles(directory=FOTOS_DIR, check_dir=False), name="fotos")

# =============================================================================
# MODELOS
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

class UsuarioUpdate(BaseModel):
    password: Optional[str] = None
    rol: Optional[str] = None
    active: Optional[bool] = None

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
        if int(datetime.utcnow().timestamp()) > int(payload.get("exp", 0)):
            raise ValueError("Token expirado")
        return payload
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token inválido: {e}")

def require_auth(authorization: str = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Falta token Bearer")
    return jwt_decode(authorization.split(" ", 1)[1])

def require_admin(user=Depends(require_auth)):
    if user.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Requiere rol admin")
    return user

# =============================================================================
# AUDITORÍA
# =============================================================================
def audit_log(user: str, action: str, meta: dict):
    ts = datetime.utcnow().isoformat()
    meta_json = json.dumps(meta, ensure_ascii=False)
    if DATA_MODE == "db" and pool:
        try:
            conn = db_conn(); cur = conn.cursor()
            cur.execute("""
                INSERT INTO auditoria (usuario, accion, metadata, ts_utc)
                VALUES (%s, %s, %s, %s)
            """, (user, action, meta_json, ts))
            conn.commit(); cur.close(); db_put(conn)
        except Exception as e:
            log.warning(f"[AUDIT] Error DB: {e}")
    else:
        log.info(f"[AUDIT] user={user} action={action} meta={meta_json}")

# =============================================================================
# HELPERS SYNC (DB ⇄ Excel/CSV)
# =============================================================================
RUTAS_COLUMNS = ["id", "camion", "nombre", "dia", "litros", "telefono", "latitud", "longitud"]

def read_excel() -> pd.DataFrame:
    if not EXCEL_FILE.exists():
        return pd.DataFrame(columns=RUTAS_COLUMNS)
    df = pd.read_excel(EXCEL_FILE)
    keep = [c for c in RUTAS_COLUMNS if c in df.columns]
    return df[keep]

def write_excel(df: pd.DataFrame):
    df.to_excel(EXCEL_FILE, index=False)

def read_csv() -> pd.DataFrame:
    if not CSV_FILE.exists():
        return pd.DataFrame(columns=RUTAS_COLUMNS)
    df = pd.read_csv(CSV_FILE)
    keep = [c for c in RUTAS_COLUMNS if c in df.columns]
    return df[keep]

def write_csv(df: pd.DataFrame):
    df.to_csv(CSV_FILE, index=False)

def sync_db_to_files() -> pd.DataFrame:
    """Lee DB y actualiza Excel + CSV (para tener backup/preview)."""
    if DATA_MODE != "db":
        return read_excel()
    conn = db_conn(); cur = conn.cursor()
    cur.execute("""
        SELECT id, camion, nombre, dia_asignado AS dia, litros_entrega AS litros,
               telefono, latitud, longitud
        FROM rutas_activas
        ORDER BY id
    """)
    rows = cur.fetchall(); cur.close(); db_put(conn)
    df = pd.DataFrame(rows, columns=RUTAS_COLUMNS)
    write_excel(df); write_csv(df)
    return df

def sync_files_to_db() -> int:
    """Lee Excel (o CSV si no hay Excel) y pisa DB."""
    if EXCEL_FILE.exists():
        df = read_excel()
    elif CSV_FILE.exists():
        df = read_csv()
    else:
        raise HTTPException(404, "No existe rutas_activas.xlsx ni rutas_activas.csv en /data")
    if DATA_MODE != "db":
        write_excel(df); write_csv(df)
        return len(df)
    conn = db_conn(); cur = conn.cursor()
    cur.execute("TRUNCATE TABLE rutas_activas RESTART IDENTITY;")
    for _, r in df.iterrows():
        cur.execute("""
            INSERT INTO rutas_activas (camion, nombre, dia_asignado, litros_entrega,
                                       telefono, latitud, longitud, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())
        """, (
            r.get("camion"), r.get("nombre"), r.get("dia"),
            int(r.get("litros")) if pd.notna(r.get("litros")) else None,
            r.get("telefono"),
            float(r.get("latitud")) if pd.notna(r.get("latitud")) else None,
            float(r.get("longitud")) if pd.notna(r.get("longitud")) else None,
        ))
    conn.commit(); cur.close(); db_put(conn)
    write_excel(df); write_csv(df)
    return len(df)

# =============================================================================
# ENDPOINTS UTILIDADES
# =============================================================================
@app.get("/health", response_class=PlainTextResponse)
def health(): return "ok"

@app.get("/mode", response_class=PlainTextResponse)
def get_mode(): return DATA_MODE

@app.get("/colores-camion")
def colores_camion(): return {"status": "ok", "colors": CAMION_COLORS}

@app.get("/camiones")
def camiones(only_active: bool = False):
    """Compatibilidad frontend: devuelve lista de camiones y color."""
    # Si hay DB, tomamos camiones que existan en rutas_activas; si no, desde Excel.
    try:
        if DATA_MODE == "db" and pool:
            conn = db_conn(); cur = conn.cursor()
            cur.execute("SELECT DISTINCT camion FROM rutas_activas WHERE camion IS NOT NULL ORDER BY camion")
            cams = [r[0] for r in cur.fetchall()]
            cur.close(); db_put(conn)
        else:
            df = read_excel()
            cams = sorted(df["camion"].dropna().astype(str).str.upper().unique().tolist())
    except Exception:
        cams = list(CAMION_COLORS.keys())
    data = [{"camion": c, "color": CAMION_COLORS.get(str(c).upper(), "#1e40af")} for c in cams]
    return {"status": "ok", "data": data}

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
# LOGIN / USUARIOS CRUD
# =============================================================================
@app.post("/login")
def login(creds: Credenciales):
    usuario = creds.usuario.strip()
    pwd = creds.password.strip()
    phash = hashlib.sha256(pwd.encode()).hexdigest()
    if DATA_MODE == "db" and pool:
        conn = db_conn(); cur = conn.cursor()
        cur.execute("SELECT password_hash, rol, active FROM usuarios WHERE usuario=%s", (usuario,))
        row = cur.fetchone(); cur.close(); db_put(conn)
        if not row or row[0] != phash or not row[2]:
            raise HTTPException(401, "Credenciales inválidas o usuario inactivo")
        rol = row[1]
    else:
        if usuario == "admin" and pwd == "admin": rol = "admin"
        else: raise HTTPException(401, "Credenciales inválidas")
    token = jwt_encode({"sub": usuario, "rol": rol})
    audit_log(usuario, "login", {"rol": rol})
    return {"status": "ok", "token": token, "rol": rol}

@app.post("/usuarios")
def crear_usuario(u: UsuarioCreate, user=Depends(require_admin)):
    if DATA_MODE != "db": raise HTTPException(400, "Solo DB soporta usuarios avanzados")
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
        return {"status": "ok", "data": [{"usuario": "admin", "rol": "admin", "active": True}]}
    conn = db_conn(); cur = conn.cursor()
    cur.execute("SELECT usuario, rol, active, created_at FROM usuarios ORDER BY usuario")
    rows = cur.fetchall(); cur.close(); db_put(conn)
    data = [{"usuario": r[0], "rol": r[1], "active": r[2], "created_at": r[3]} for r in rows]
    return {"status": "ok", "data": data}

@app.put("/usuarios/{usuario}")
def actualizar_usuario(usuario: str, u: UsuarioUpdate, user=Depends(require_admin)):
    if DATA_MODE != "db": raise HTTPException(400, "Solo DB")
    sets, vals = [], []
    if u.password is not None:
        sets.append("password_hash=%s"); vals.append(hashlib.sha256(u.password.encode()).hexdigest())
    if u.rol is not None:
        sets.append("rol=%s"); vals.append(u.rol)
    if u.active is not None:
        sets.append("active=%s"); vals.append(u.active)
    if not sets: return {"status": "ok", "updated": 0}
    vals.append(usuario)
    conn = db_conn(); cur = conn.cursor()
    cur.execute(f"UPDATE usuarios SET {', '.join(sets)} WHERE usuario=%s", vals)
    conn.commit(); cur.close(); db_put(conn)
    audit_log(user["sub"], "actualizar_usuario", {"usuario": usuario, "changes": u.dict(exclude_unset=True)})
    return {"status": "ok", "updated": 1}

@app.delete("/usuarios/{usuario}")
def eliminar_usuario(usuario: str, user=Depends(require_admin)):
    if DATA_MODE != "db": raise HTTPException(400, "Solo DB")
    conn = db_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM usuarios WHERE usuario=%s", (usuario,))
    conn.commit(); cur.close(); db_put(conn)
    audit_log(user["sub"], "eliminar_usuario", {"usuario": usuario})
    return {"status": "ok"}

# =============================================================================
# RUTAS ACTIVAS — CRUD + FILTROS + PREVIEW/IMPORT
# =============================================================================
@app.get("/rutas-activas")
def get_rutas_activas(
    camion: Optional[str] = Query(None),
    dia: Optional[str] = Query(None),
    nombre: Optional[str] = Query(None),
    telefono: Optional[str] = Query(None),
    litros: Optional[int] = Query(None),
    q: Optional[str] = Query(None),
    only_geocoded: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=5000)
):
    df = sync_db_to_files() if (DATA_MODE == "db") else read_excel()
    if camion:   df = df[df["camion"].astype(str).str.upper() == camion.upper()]
    if dia:      df = df[df["dia"].astype(str).str.upper() == dia.upper()]
    if nombre:   df = df[df["nombre"].astype(str).str.contains(nombre, case=False, na=False)]
    if telefono: df = df[df["telefono"].astype(str).str.contains(telefono, na=False)]
    if litros is not None: df = df[df["litros"] == litros]
    if q:
        qs = q.lower()
        df = df[df.apply(lambda r: qs in str(r.to_dict()).lower(), axis=1)]
    if only_geocoded: df = df.dropna(subset=["latitud", "longitud"])
    total = len(df)
    df = df.iloc[skip: skip + limit]
    return {"status": "ok", "total": total, "data": df.to_dict(orient="records")}

@app.post("/rutas-activas")
def add_ruta_activa(nuevo: NuevoPunto, user=Depends(require_auth)):
    if DATA_MODE != "db":
        # Modo Excel (fallback)
        df = read_excel()
        new_id = int(df["id"].max() + 1 if not df.empty else 1)
        df.loc[len(df)] = [new_id, nuevo.camion, nuevo.nombre, nuevo.dia, nuevo.litros,
                           nuevo.telefono, nuevo.latitud, nuevo.longitud]
        write_excel(df); write_csv(df)
        audit_log(user["sub"], "add_ruta_excel", nuevo.dict())
        return {"status": "ok", "new_id": new_id}
    # DB
    conn = db_conn(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO rutas_activas (camion, nombre, dia_asignado, litros_entrega,
                                   telefono, latitud, longitud, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,NOW()) RETURNING id
    """, (nuevo.camion, nuevo.nombre, nuevo.dia, nuevo.litros,
          nuevo.telefono, nuevo.latitud, nuevo.longitud))
    new_id = cur.fetchone()[0]; conn.commit(); cur.close(); db_put(conn)
    sync_db_to_files()
    audit_log(user["sub"], "add_ruta_db", {"id": new_id, **nuevo.dict()})
    return {"status": "ok", "new_id": new_id}

@app.put("/rutas-activas/{id}")
def update_ruta_activa(id: int, payload: RutaActivaUpdate, user=Depends(require_auth)):
    if DATA_MODE != "db":
        df = read_excel()
        if df.empty or id not in df["id"].values:
            raise HTTPException(404, "ID no encontrado en Excel")
        for k, v in payload.dict(exclude_unset=True).items():
            df.loc[df["id"] == id, k] = v
        write_excel(df); write_csv(df)
        audit_log(user["sub"], "update_ruta_excel", {"id": id, **payload.dict(exclude_unset=True)})
        return {"status": "ok", "updated_id": id}
    campos, valores = [], []
    for k, v in payload.dict(exclude_unset=True).items():
        if k == "dia": campos.append("dia_asignado=%s"); valores.append(v)
        elif k == "litros": campos.append("litros_entrega=%s"); valores.append(v)
        else: campos.append(f"{k}=%s"); valores.append(v)
    if not campos: return {"status": "ok", "updated_id": id}
    campos.append("updated_at=NOW()"); valores.append(id)
    conn = db_conn(); cur = conn.cursor()
    cur.execute(f"UPDATE rutas_activas SET {', '.join(campos)} WHERE id=%s", valores)
    conn.commit(); cur.close(); db_put(conn)
    sync_db_to_files()
    audit_log(user["sub"], "update_ruta_db", {"id": id, **payload.dict(exclude_unset=True)})
    return {"status": "ok", "updated_id": id}

@app.delete("/rutas-activas/{id}")
def delete_ruta_activa(id: int, user=Depends(require_auth)):
    if DATA_MODE != "db":
        df = read_excel()
        if df.empty or id not in df["id"].values:
            raise HTTPException(404, "ID no encontrado en Excel")
        df = df[df["id"] != id]; write_excel(df); write_csv(df)
        audit_log(user["sub"], "delete_ruta_excel", {"id": id})
        return {"status": "ok", "deleted_id": id}
    conn = db_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM rutas_activas WHERE id=%s", (id,))
    conn.commit(); cur.close(); db_put(conn)
    sync_db_to_files()
    audit_log(user["sub"], "delete_ruta_db", {"id": id})
    return {"status": "ok", "deleted_id": id}

@app.get("/preview-excel")
def preview_excel(rows: int = 20):
    df = read_excel()
    return {"status": "ok", "columns": list(df.columns), "rows": df.head(rows).to_dict(orient="records")}

@app.get("/preview-csv")
def preview_csv(rows: int = 20):
    df = read_csv()
    return {"status": "ok", "columns": list(df.columns), "rows": df.head(rows).to_dict(orient="records")}

@app.post("/importar-excel-a-db")
def importar_excel_a_db(user=Depends(require_admin)):
    rows = sync_files_to_db()
    audit_log(user["sub"], "import_excel_to_db", {"rows": rows})
    return {"status": "ok", "rows_imported": rows}

@app.post("/importar-csv-a-db")
def importar_csv_a_db(user=Depends(require_admin)):
    rows = sync_files_to_db()
    audit_log(user["sub"], "import_csv_to_db", {"rows": rows})
    return {"status": "ok", "rows_imported": rows}

# =============================================================================
# MAPA
# =============================================================================
@app.get("/mapa-puntos")
def mapa_puntos(camion: Optional[str] = None):
    df = sync_db_to_files() if DATA_MODE == "db" else read_excel()
    df = df.dropna(subset=["latitud", "longitud"])
    if camion:
        df = df[df["camion"].astype(str).str.upper() == camion.upper()]
    df = df.copy()
    df["color"] = df["camion"].astype(str).str.upper().apply(lambda c: CAMION_COLORS.get(c, "#1e40af"))
    df["popup"] = df.apply(lambda r: f"{r.get('nombre','')} — {r.get('litros','')} L", axis=1)
    return {"status": "ok", "data": df.to_dict(orient="records")}

# =============================================================================
# ENTREGAS APP (POST + GET de compatibilidad) + NO ENTREGADAS
# =============================================================================
@app.post("/entregas-app")
async def registrar_entrega_app(
    nombre: str = Form(...),
    camion: str = Form(...),
    litros: int = Form(...),
    estado: int = Form(...),      # 1=entregada, 0/2 no entregada (con foto), 3 no ubicado
    fecha: str = Form(...),       # YYYY-MM-DD o ISO
    latitud: Optional[float] = Form(None),
    longitud: Optional[float] = Form(None),
    foto: Optional[UploadFile] = File(None),
    authorization: Optional[str] = Header(None),
):
    foto_path_rel = None
    if foto and foto.filename:
        ext = Path(foto.filename).suffix.lower() or ".jpg"
        fname = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex}{ext}"
        dest = FOTOS_DIR / fname
        with dest.open("wb") as f:
            shutil.copyfileobj(foto.file, f)
        foto_path_rel = f"/fotos/{fname}"

    new_id = None
    if DATA_MODE == "db" and pool:
        try:
            conn = db_conn(); cur = conn.cursor()
            cur.execute("""
                INSERT INTO entregas_app (nombre, camion, litros, estado, fecha, latitud, longitud, foto_path)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
            """, (nombre, camion, litros, estado, fecha, latitud, longitud, foto_path_rel))
            new_id = cur.fetchone()[0]
            conn.commit(); cur.close(); db_put(conn)
        except Exception as e:
            log.error(f"/entregas-app DB error: {e}")

    actor = "invitado"
    if authorization and authorization.startswith("Bearer "):
        try:
            actor = jwt_decode(authorization.split(" ", 1)[1]).get("sub", "invitado")
        except Exception:
            pass
    audit_log(actor, "registrar_entrega", {
        "nombre": nombre, "camion": camion, "litros": litros,
        "estado": estado, "fecha": fecha, "foto": bool(foto_path_rel)
    })

    return {"status": "ok", "id": new_id, "foto": foto_path_rel}

@app.get("/entregas-app")
def listar_entregas_app(
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    camion: Optional[str] = None
):
    """Compatibilidad: algunos front hacen GET /entregas-app."""
    if DATA_MODE != "db":
        return {"status": "ok", "data": []}
    conn = db_conn(); cur = conn.cursor()
    q = """
        SELECT id, nombre, camion, litros, estado, fecha, latitud, longitud, foto_path
        FROM entregas_app WHERE 1=1
    """
    params=[]
    if desde: q += " AND fecha::date >= %s"; params.append(desde)
    if hasta: q += " AND fecha::date <= %s"; params.append(hasta)
    if camion: q += " AND camion = %s"; params.append(camion)
    q += " ORDER BY fecha DESC"
    cur.execute(q, params)
    rows = cur.fetchall(); cur.close(); db_put(conn)
    cols = ["id","nombre","camion","litros","estado","fecha","latitud","longitud","foto"]
    data = [dict(zip(cols, r)) for r in rows]
    return {"status": "ok", "data": data}

@app.get("/entregas-todas")
def entregas_todas(desde: Optional[str] = None, hasta: Optional[str] = None):
    """Compatibilidad: usado por varios componentes legacy."""
    return listar_entregas_app(desde=desde, hasta=hasta)

@app.get("/entregas")
def entregas(desde: str, hasta: str, camion: Optional[str] = None):
    """Compatibilidad: devuelve entregas entre fechas (GET)."""
    return listar_entregas_app(desde=desde, hasta=hasta, camion=camion)

@app.get("/no-entregadas")
def no_entregadas(
    dia: Optional[str] = None,
    camion: Optional[str] = None,
    skip: int = 0,
    limit: int = 500
):
    if DATA_MODE != "db":
        return {"status": "ok", "total": 0, "data": []}
    conn = db_conn(); cur = conn.cursor()
    q = """SELECT id, nombre, camion, litros, estado, fecha, latitud, longitud, foto_path
           FROM entregas_app WHERE estado IN (0,2,3)"""
    params = []
    if dia:
        q += " AND fecha::date = %s"; params.append(dia)
    if camion:
        q += " AND camion = %s"; params.append(camion)
    q += " ORDER BY fecha DESC, camion LIMIT %s OFFSET %s"
    params += [limit, skip]
    cur.execute(q, params)
    rows = cur.fetchall(); cur.close(); db_put(conn)
    cols = ["id","nombre","camion","litros","estado","fecha","latitud","longitud","foto"]
    data = [dict(zip(cols, r)) for r in rows]
    return {"status": "ok", "total": len(data), "data": data}

# =============================================================================
# GRAFICOS / ESTADISTICAS
# =============================================================================
@app.get("/graficos")
def graficos_resumen(camion: Optional[str] = None, dia: Optional[str] = None):
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
def estadisticas_camion(
    camion: Optional[str] = None,
    fecha_desde: Optional[str] = None,
    fecha_hasta: Optional[str] = None
):
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
    data = [dict(zip(cols, r)) for r in rows]
    return {"status": "ok", "data": data}

@app.get("/comparacion-semanal")
def comparacion_semanal(camion: Optional[str] = None, semanas: int = 8):
    if DATA_MODE != "db":
        return {"status": "ok", "data": []}
    conn = db_conn(); cur = conn.cursor()
    q = """
        SELECT camion, DATE_TRUNC('week', fecha::date)::date AS lunes, SUM(litros) AS litros
        FROM entregas_app WHERE 1=1
    """
    params=[]
    if camion: q += " AND camion=%s"; params.append(camion)
    q += " GROUP BY camion, lunes ORDER BY lunes DESC LIMIT %s"
    params.append(semanas)
    cur.execute(q, params)
    rows = cur.fetchall(); cur.close(); db_put(conn)
    cols = ["camion","lunes","litros"]
    data = [dict(zip(cols, r)) for r in rows]
    return {"status": "ok", "data": data}

# =============================================================================
# EXPORTACIONES
# =============================================================================
@app.get("/estadisticas/export")
def export_estadisticas(formato: str = "excel", user=Depends(require_admin)):
    if DATA_MODE == "db":
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
        raise HTTPException(400, "Formato inválido")

# =============================================================================
# AUDITORÍA (filtros + export)
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
    q += " ORDER BY ts_utc DESC LIMIT %s"; params.append(limit)
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
        raise HTTPException(400, "Formato inválido")

# =============================================================================
# ALERTAS
# =============================================================================
@app.get("/alertas")
def alertas(umbral_litros: int = 45000, umbral_no_ent: float = 0.2):
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
# BOOTSTRAP DB (opcional) — crea tablas base + admin
# =============================================================================
def _exec_sql(sql: str, params=None):
    conn = db_conn(); cur = conn.cursor()
    cur.execute(sql, params or [])
    conn.commit(); cur.close(); db_put(conn)

if DATA_MODE == "db" and pool and os.getenv("AGUARUTA_BOOTSTRAP_DB", "0") == "1":
    log.info("Bootstrapping DB…")
    ddl = """
    CREATE EXTENSION IF NOT EXISTS pgcrypto;

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
    DO $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE c.relname='idx_auditoria_meta_gin' AND n.nspname='public'
      ) THEN
        CREATE INDEX idx_auditoria_meta_gin ON auditoria USING GIN (metadata);
      END IF;
    END $$;

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
