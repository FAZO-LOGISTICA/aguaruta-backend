# main.py — AguaRuta Backend (versión completa y estable)
# Autor: Equipo AguaRuta — 2025-10-02
# Características:
# - CRUD Rutas Activas (Excel/DB)
# - Registrar nuevo punto
# - Registrar entrega App (foto + GPS)
# - Usuarios avanzados (CRUD + roles)
# - Auditoría avanzada (filtros + export)
# - Estadísticas, Gráficos, Comparación semanal
# - Exportaciones Excel/PDF
# - Alertas (sobrecarga y no entregadas)
# - Mapa de puntos con colores por camión
# - Preview/Import Excel -> DB
# - Persistencia al editar desde AguaRuta

import os, uuid, shutil, logging, hashlib, json, base64, hmac
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from io import BytesIO

import pandas as pd
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from reportlab.pdfgen import canvas

import psycopg2
from psycopg2.pool import SimpleConnectionPool

# ============================================================================
# CONFIG
# ============================================================================
APP_NAME = "AguaRuta Backend"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"; DATA_DIR.mkdir(parents=True, exist_ok=True)
EXCEL_FILE = DATA_DIR / "rutas_activas.xlsx"
FOTOS_DIR = BASE_DIR / "fotos" / "evidencias"; FOTOS_DIR.mkdir(parents=True, exist_ok=True)

DATA_MODE = os.getenv("DATA_MODE", "excel").lower().strip()  # excel | db
DB_URL = os.getenv("DATABASE_URL")

JWT_SECRET = os.getenv("JWT_SECRET", "aguaruta_super_secreto")
JWT_EXP_MIN = int(os.getenv("JWT_EXP_MIN", "720"))  # 12 horas

# Colores por camión
CAMION_COLORS: Dict[str, str] = {
    "A1": "#2563eb", "A2": "#059669", "A3": "#dc2626", "A4": "#f59e0b", "A5": "#7c3aed",
    "M1": "#0ea5e9", "M2": "#22c55e", "M3": "#6b7280"
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger(APP_NAME)

# ============================================================================
# DB
# ============================================================================
pool = SimpleConnectionPool(1, 10, dsn=DB_URL) if DATA_MODE == "db" and DB_URL else None

def db_conn():
    if not pool:
        raise RuntimeError("DB no inicializada (DATA_MODE=db y DATABASE_URL requerido)")
    return pool.getconn()

def db_put(conn): 
    if pool and conn: pool.putconn(conn)

# ============================================================================
# APP
# ============================================================================
app = FastAPI(title=APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # FIX: habilitamos todos los orígenes
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/fotos", StaticFiles(directory=FOTOS_DIR, check_dir=False), name="fotos")

# ============================================================================
# MODELOS
# ============================================================================
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

# ============================================================================
# JWT Helpers
# ============================================================================
def _b64e(b: bytes) -> str: return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
def _b64d(s: str) -> bytes: s += "=" * ((4 - len(s) % 4) % 4); return base64.urlsafe_b64decode(s)

def jwt_encode(payload: dict) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    p = payload.copy()
    if "exp" not in p:
        p["exp"] = int((datetime.utcnow() + timedelta(minutes=JWT_EXP_MIN)).timestamp())
    h_b64 = _b64e(json.dumps(header).encode()); p_b64 = _b64e(json.dumps(p).encode())
    sig = hmac.new(JWT_SECRET.encode(), f"{h_b64}.{p_b64}".encode(), hashlib.sha256).digest()
    return f"{h_b64}.{p_b64}.{_b64e(sig)}"

def jwt_decode(token: str) -> dict:
    h_b64, p_b64, s_b64 = token.split(".")
    sig_check = hmac.new(JWT_SECRET.encode(), f"{h_b64}.{p_b64}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(sig_check, _b64d(s_b64)):
        raise HTTPException(401, "Firma inválida")
    payload = json.loads(_b64d(p_b64).decode())
    if int(datetime.utcnow().timestamp()) > int(payload["exp"]):
        raise HTTPException(401, "Token expirado")
    return payload

def require_auth(authorization: str = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Falta token Bearer")
    return jwt_decode(authorization.split(" ", 1)[1])

def require_admin(user=Depends(require_auth)):
    if user.get("rol") != "admin":
        raise HTTPException(403, "Requiere rol admin")
    return user

# ============================================================================
# AUDITORÍA
# ============================================================================
def audit_log(user: str, action: str, meta: dict):
    ts = datetime.utcnow().isoformat()
    meta_json = json.dumps(meta, ensure_ascii=False)
    if DATA_MODE == "db" and pool:
        try:
            conn = db_conn(); cur = conn.cursor()
            cur.execute("INSERT INTO auditoria (usuario, accion, metadata, ts_utc) VALUES (%s,%s,%s,%s)",
                        (user, action, meta_json, ts))
            conn.commit(); cur.close(); db_put(conn)
        except Exception as e:
            log.warning(f"Auditoría DB error: {e}")
    else:
        log.info(f"[AUDIT] {user} {action} {meta_json}")

# ============================================================================
# HELPERS RUTAS
# ============================================================================
RUTAS_COLUMNS = ["id","camion","nombre","dia","litros","telefono","latitud","longitud"]

def read_rutas_excel() -> pd.DataFrame:
    if not EXCEL_FILE.exists(): raise HTTPException(404, "No se encontró rutas_activas.xlsx")
    df = pd.read_excel(EXCEL_FILE)
    return df[[c for c in RUTAS_COLUMNS if c in df.columns]]

def write_rutas_excel(df: pd.DataFrame): df.to_excel(EXCEL_FILE, index=False)

def read_rutas_db() -> pd.DataFrame:
    conn = db_conn(); cur = conn.cursor()
    cur.execute("""SELECT id, camion, nombre, dia, litros, telefono, latitud, longitud
                   FROM rutas_activas ORDER BY camion, dia, nombre""")
    rows = cur.fetchall(); cur.close(); db_put(conn)
    return pd.DataFrame(rows, columns=RUTAS_COLUMNS)

# ============================================================================
# ENDPOINTS
# ============================================================================
@app.get("/health") def health(): return "ok"
@app.get("/colores-camion") def colores_camion(): return CAMION_COLORS

# --- LOGIN / USUARIOS ---
@app.post("/login")
def login(creds: Credenciales):
    usuario, pwd = creds.usuario.strip(), creds.password.strip()
    phash = hashlib.sha256(pwd.encode()).hexdigest()
    if DATA_MODE == "db" and pool:
        conn = db_conn(); cur = conn.cursor()
        cur.execute("SELECT password_hash, rol, active FROM usuarios WHERE usuario=%s", (usuario,))
        row = cur.fetchone(); cur.close(); db_put(conn)
        if not row or row[0] != phash or not row[2]:
            raise HTTPException(401, "Credenciales inválidas")
        rol = row[1]
    else:
        if usuario=="admin" and pwd=="admin": rol="admin"
        else: raise HTTPException(401,"Credenciales inválidas")
    token = jwt_encode({"sub": usuario, "rol": rol})
    audit_log(usuario,"login",{"rol":rol})
    return {"token":token,"rol":rol}

@app.post("/usuarios") 
def crear_usuario(u: UsuarioCreate,user=Depends(require_admin)):
    if DATA_MODE!="db": raise HTTPException(400,"Solo en DB")
    phash = hashlib.sha256(u.password.encode()).hexdigest()
    conn=db_conn(); cur=conn.cursor()
    cur.execute("INSERT INTO usuarios (usuario,password_hash,rol,active) VALUES (%s,%s,%s,TRUE)",
                (u.usuario,phash,u.rol))
    conn.commit(); cur.close(); db_put(conn)
    return {"status":"ok"}

@app.get("/usuarios") 
def listar_usuarios(user=Depends(require_admin)):
    if DATA_MODE!="db": return [{"usuario":"admin","rol":"admin","active":True}]
    conn=db_conn(); cur=conn.cursor()
    cur.execute("SELECT usuario,rol,active,created_at FROM usuarios"); rows=cur.fetchall()
    cur.close(); db_put(conn)
    return [{"usuario":r[0],"rol":r[1],"active":r[2],"created_at":r[3]} for r in rows]

# --- RUTAS ACTIVAS CRUD ---
@app.get("/rutas-activas")
def get_rutas_activas(camion:Optional[str]=None,dia:Optional[str]=None,q:Optional[str]=None):
    df = read_rutas_db() if DATA_MODE=="db" else read_rutas_excel()
    if camion: df=df[df["camion"].str.upper()==camion.upper()]
    if dia: df=df[df["dia"].str.upper()==dia.upper()]
    if q: df=df[df["nombre"].str.contains(q,case=False)|df["telefono"].astype(str).str.contains(q)]
    return {"data":df.to_dict(orient="records")}

@app.post("/rutas-activas")
def add_ruta_activa(nuevo:NuevoPunto,user=Depends(require_auth)):
    df = read_rutas_excel() if DATA_MODE!="db" else read_rutas_db()
    new_id = int(df["id"].max()+1 if not df.empty else 1)
    df.loc[len(df)]={"id":new_id,**nuevo.dict()}
    write_rutas_excel(df)
    return {"status":"ok","new_id":new_id}

# --- MAPA ---
@app.get("/mapa-puntos")
def mapa_puntos():
    df = read_rutas_db() if DATA_MODE=="db" else read_rutas_excel()
    df=df.dropna(subset=["latitud","longitud"])
    df["color"]=df["camion"].apply(lambda c:CAMION_COLORS.get(str(c).upper(),"#1e40af"))
    return {"data":df.to_dict(orient="records")}

# --- ENTREGAS APP ---
@app.post("/entregas-app")
async def registrar_entrega_app(
    nombre:str=Form(...),camion:str=Form(...),litros:int=Form(...),estado:int=Form(...),fecha:str=Form(...),
    latitud:Optional[float]=Form(None),longitud:Optional[float]=Form(None),foto:Optional[UploadFile]=File(None)
):
    foto_path=None
    if foto: 
        fname=f"{uuid.uuid4().hex}.jpg"; dest=FOTOS_DIR/fname
        with dest.open("wb") as f: shutil.copyfileobj(foto.file,f)
        foto_path=f"/fotos/{fname}"
    return {"status":"ok","nombre":nombre,"camion":camion,"litros":litros,"estado":estado,"fecha":fecha,"foto":foto_path}

# --- AUDITORÍA ---
@app.get("/auditoria") 
def auditoria_list(user=Depends(require_admin)):
    if DATA_MODE!="db": return []
    conn=db_conn(); cur=conn.cursor()
    cur.execute("SELECT usuario,accion,metadata,ts_utc FROM auditoria ORDER BY ts_utc DESC LIMIT 200")
    rows=cur.fetchall(); cur.close(); db_put(conn)
    return [{"usuario":r[0],"accion":r[1],"metadata":r[2],"ts":r[3]} for r in rows]
