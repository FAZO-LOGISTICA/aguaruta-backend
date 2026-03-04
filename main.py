# main.py — AguaRuta Backend
# Versión: 2.2 FINAL

import os, uuid, shutil, logging, hashlib, json, base64, hmac
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List
from io import BytesIO

import pandas as pd
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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

DATA_MODE = os.getenv("DATA_MODE", "excel").lower().strip()
DB_URL = os.getenv("DATABASE_URL")
JWT_SECRET = os.getenv("JWT_SECRET", "aguaruta_super_secreto")
JWT_EXP_MIN = int(os.getenv("JWT_EXP_MIN", "720"))

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
        raise RuntimeError("DB no inicializada")
    return pool.getconn()

def db_put(conn):
    if pool and conn: pool.putconn(conn)

# ============================================================================
# APP + CORS
# ============================================================================
app = FastAPI(title=APP_NAME, version="2.2 FINAL")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/fotos", StaticFiles(directory=FOTOS_DIR, check_dir=False), name="fotos")

# ============================================================================
# MODELOS
# ============================================================================
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
    rol: str

class NuevaEntrega(BaseModel):
    camion: str
    nombre: str
    litros: int
    estado: int
    fecha: str
    motivo: Optional[str] = None
    telefono: Optional[str] = None
    latitud: Optional[float] = None
    longitud: Optional[float] = None

# ============================================================================
# JWT
# ============================================================================
def _b64e(b: bytes) -> str: return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
def _b64d(s: str) -> bytes: s += "=" * ((4 - len(s) % 4) % 4); return base64.urlsafe_b64decode(s)

def jwt_encode(payload: dict) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    p = payload.copy()
    if "exp" not in p:
        p["exp"] = int((datetime.utcnow() + timedelta(minutes=JWT_EXP_MIN)).timestamp())
    h_b64 = _b64e(json.dumps(header).encode())
    p_b64 = _b64e(json.dumps(p).encode())
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
RUTAS_COLUMNS = ["id", "camion", "nombre", "dia", "litros", "telefono", "latitud", "longitud"]

def read_rutas_excel() -> pd.DataFrame:
    if not EXCEL_FILE.exists():
        return pd.DataFrame(columns=RUTAS_COLUMNS)
    df = pd.read_excel(EXCEL_FILE)
    return df[[c for c in RUTAS_COLUMNS if c in df.columns]]

def write_rutas_excel(df: pd.DataFrame):
    df.to_excel(EXCEL_FILE, index=False)

def read_rutas_db() -> pd.DataFrame:
    conn = db_conn(); cur = conn.cursor()
    cur.execute("""SELECT id, camion, nombre, dia, litros, telefono, latitud, longitud
                   FROM rutas_activas ORDER BY camion, dia, nombre""")
    rows = cur.fetchall(); cur.close(); db_put(conn)
    return pd.DataFrame(rows, columns=RUTAS_COLUMNS)

# ============================================================================
# DATOS MOCK
# ============================================================================
CAMIONES_MOCK = [
    {"id": "A1", "nombre": "Camión A1", "patente": "AA-BB-11", "activo": True,  "color": "#2563eb"},
    {"id": "A2", "nombre": "Camión A2", "patente": "CC-DD-22", "activo": True,  "color": "#059669"},
    {"id": "A3", "nombre": "Camión A3", "patente": "EE-FF-33", "activo": True,  "color": "#dc2626"},
    {"id": "A4", "nombre": "Camión A4", "patente": "GG-HH-44", "activo": False, "color": "#f59e0b"},
    {"id": "A5", "nombre": "Camión A5", "patente": "II-JJ-55", "activo": True,  "color": "#7c3aed"},
    {"id": "M1", "nombre": "Camión M1", "patente": "KK-LL-66", "activo": True,  "color": "#0ea5e9"},
    {"id": "M2", "nombre": "Camión M2", "patente": "MM-NN-77", "activo": True,  "color": "#22c55e"},
    {"id": "M3", "nombre": "Camión M3", "patente": "OO-PP-88", "activo": False, "color": "#6b7280"},
]

def generar_entregas_mock(desde: str = None, hasta: str = None) -> list:
    camiones = ["A1", "A2", "A3", "A4", "A5", "M1", "M2", "M3"]
    nombres = [
        "Rosa Martínez", "Juan Pérez", "María González", "Carlos Rodríguez",
        "Ana Silva", "Pedro Muñoz", "Carmen López", "Luis Fernández",
        "Isabel Castro", "Roberto Díaz", "Patricia Vargas", "Miguel Torres"
    ]

    import random
    random.seed(42)

    if desde and hasta:
        try:
            d_desde = datetime.strptime(desde, "%Y-%m-%d")
            d_hasta = datetime.strptime(hasta, "%Y-%m-%d")
        except:
            d_desde = d_hasta = datetime.now()
    else:
        d_desde = d_hasta = datetime.now()

    delta = (d_hasta - d_desde).days + 1
    fechas = [(d_desde + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(delta)]

    entregas = []
    id_counter = 1
    for fecha in fechas:
        for camion in camiones:
            n_entregas = random.randint(3, 8)
            for _ in range(n_entregas):
                estado = random.choice([1, 1, 1, 2, 3])  # estados 1-3, mayoría entregadas
                entregas.append({
                    "id": id_counter,
                    "camion": camion,
                    "nombre": random.choice(nombres),
                    "litros": random.choice([500, 1000, 1500, 2000]) if estado == 1 else 0,
                    "estado": estado,
                    "fecha": fecha,
                    "motivo": None if estado == 1 else "Sin moradores" if estado == 2 else "Dirección no existe",
                    "telefono": f"+569{random.randint(10000000, 99999999)}",
                    "latitud": -33.05 + random.uniform(-0.05, 0.05),
                    "longitud": -71.62 + random.uniform(-0.05, 0.05),
                    "foto_url": None,
                    "fuente": "manual"
                })
                id_counter += 1
    return entregas

# ============================================================================
# ENDPOINTS BASE
# ============================================================================
@app.get("/health")
def health():
    return {"status": "ok", "version": "2.2 FINAL", "data_mode": DATA_MODE}

@app.get("/cors-test")
def cors_test():
    return {"status": "ok"}

@app.get("/colores-camion")
def colores_camion():
    return CAMION_COLORS

# ============================================================================
# CAMIONES
# ============================================================================
@app.get("/camiones")
def get_camiones(only_active: Optional[bool] = None):
    camiones = CAMIONES_MOCK
    if only_active is not None:
        camiones = [c for c in camiones if c["activo"] == only_active]
    return camiones

# ============================================================================
# ENTREGAS
# ============================================================================
@app.get("/entregas")
def get_entregas(
    desde: Optional[str] = Query(None),
    hasta: Optional[str] = Query(None),
    camion: Optional[str] = Query(None),
    estado: Optional[int] = Query(None)
):
    entregas = generar_entregas_mock(desde, hasta)
    if camion:
        entregas = [e for e in entregas if e["camion"] == camion.upper()]
    if estado is not None:
        entregas = [e for e in entregas if e["estado"] == estado]
    return entregas

@app.get("/entregas-todas")
def get_entregas_todas(
    desde: Optional[str] = Query(None),
    hasta: Optional[str] = Query(None),
    camion: Optional[str] = Query(None)
):
    if not desde:
        desde = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    if not hasta:
        hasta = datetime.now().strftime("%Y-%m-%d")
    entregas = generar_entregas_mock(desde, hasta)
    if camion:
        entregas = [e for e in entregas if e["camion"] == camion.upper()]
    return entregas

# ============================================================================
# REGISTRAR ENTREGAS — endpoint principal usado por el frontend
# Acepta multipart/form-data para recibir foto adjunta
# Estados: 1=entregado | 2=sin moradores (foto) | 3=dir no existe | 4=camino malo (foto)
# ============================================================================
@app.post("/registrar-entregas")
async def registrar_entregas(
    nombre: str = Form(...),
    camion: str = Form(...),
    litros: int = Form(...),
    estado: int = Form(...),
    fecha: str = Form(...),
    motivo: Optional[str] = Form(None),
    latitud: Optional[float] = Form(None),
    longitud: Optional[float] = Form(None),
    foto: Optional[UploadFile] = File(None)
):
    foto_path = None
    if foto and foto.filename:
        fname = f"{uuid.uuid4().hex}.jpg"
        dest = FOTOS_DIR / fname
        with dest.open("wb") as f:
            shutil.copyfileobj(foto.file, f)
        foto_path = f"/fotos/{fname}"
        log.info(f"[FOTO] Guardada: {foto_path}")

    nueva = {
        "id": int(datetime.now().timestamp()),
        "nombre": nombre,
        "camion": camion,
        "litros": litros if estado == 1 else 0,
        "estado": estado,
        "fecha": fecha,
        "motivo": motivo,
        "latitud": latitud,
        "longitud": longitud,
        "foto_url": foto_path,
        "fuente": "web",
        "registrado_en": datetime.utcnow().isoformat()
    }

    log.info(f"[ENTREGA] camion={camion} nombre={nombre} estado={estado} fecha={fecha}")
    audit_log("sistema", "registrar_entrega", {"camion": camion, "nombre": nombre, "estado": estado})

    return {"status": "ok", "entrega": nueva}

# Alias JSON por compatibilidad con otros clientes
@app.post("/entregas")
def registrar_entrega_json(entrega: NuevaEntrega):
    nueva = entrega.dict()
    nueva["id"] = int(datetime.now().timestamp())
    nueva["fuente"] = "manual"
    nueva["foto_url"] = None
    log.info(f"[ENTREGA-JSON] {nueva}")
    return {"status": "ok", "entrega": nueva}

# ============================================================================
# ESTADÍSTICAS CAMIÓN
# ============================================================================
@app.get("/estadisticas-camion")
def estadisticas_camion(
    camion: Optional[str] = Query(None),
    desde: Optional[str] = Query(None),
    hasta: Optional[str] = Query(None)
):
    if not desde:
        desde = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not hasta:
        hasta = datetime.now().strftime("%Y-%m-%d")

    entregas = generar_entregas_mock(desde, hasta)
    if camion:
        entregas = [e for e in entregas if e["camion"] == camion.upper()]

    stats = {}
    for e in entregas:
        c = e["camion"]
        if c not in stats:
            stats[c] = {"camion": c, "total": 0, "entregadas": 0, "no_entregadas": 0, "litros_total": 0}
        stats[c]["total"] += 1
        stats[c]["litros_total"] += e["litros"]
        if e["estado"] == 1:
            stats[c]["entregadas"] += 1
        else:
            stats[c]["no_entregadas"] += 1

    for c in stats:
        t = stats[c]["total"]
        stats[c]["porcentaje_entrega"] = round(stats[c]["entregadas"] / t * 100, 1) if t > 0 else 0

    return list(stats.values())

# ============================================================================
# NO ENTREGADAS
# ============================================================================
@app.get("/no-entregadas")
def get_no_entregadas(
    desde: Optional[str] = Query(None),
    hasta: Optional[str] = Query(None),
    camion: Optional[str] = Query(None)
):
    if not desde:
        desde = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    if not hasta:
        hasta = datetime.now().strftime("%Y-%m-%d")

    entregas = generar_entregas_mock(desde, hasta)
    no_entregadas = [e for e in entregas if e["estado"] != 1]
    if camion:
        no_entregadas = [e for e in no_entregadas if e["camion"] == camion.upper()]
    return no_entregadas

# ============================================================================
# ENTREGAS APP
# ============================================================================
@app.get("/entregas-app")
def get_entregas_app(
    desde: Optional[str] = Query(None),
    hasta: Optional[str] = Query(None)
):
    if not desde:
        desde = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    if not hasta:
        hasta = datetime.now().strftime("%Y-%m-%d")
    entregas = generar_entregas_mock(desde, hasta)
    app_entregas = [e for e in entregas if e["id"] % 3 == 0]
    for e in app_entregas:
        e["fuente"] = "app"
    return app_entregas

@app.post("/entregas-app")
async def registrar_entrega_app(
    nombre: str = Form(...),
    camion: str = Form(...),
    litros: int = Form(...),
    estado: int = Form(...),
    fecha: str = Form(...),
    latitud: Optional[float] = Form(None),
    longitud: Optional[float] = Form(None),
    foto: Optional[UploadFile] = File(None)
):
    foto_path = None
    if foto and foto.filename:
        fname = f"{uuid.uuid4().hex}.jpg"
        dest = FOTOS_DIR / fname
        with dest.open("wb") as f:
            shutil.copyfileobj(foto.file, f)
        foto_path = f"/fotos/{fname}"

    nueva = {
        "id": int(datetime.now().timestamp()),
        "nombre": nombre, "camion": camion, "litros": litros,
        "estado": estado, "fecha": fecha,
        "latitud": latitud, "longitud": longitud,
        "foto_url": foto_path, "fuente": "app"
    }
    log.info(f"[ENTREGA-APP] {nueva}")
    return {"status": "ok", "entrega": nueva}

# ============================================================================
# RUTAS ACTIVAS
# ============================================================================
@app.get("/rutas-activas")
def get_rutas_activas(
    camion: Optional[str] = None,
    dia: Optional[str] = None,
    q: Optional[str] = None
):
    df = read_rutas_db() if DATA_MODE == "db" else read_rutas_excel()
    if camion: df = df[df["camion"].str.upper() == camion.upper()]
    if dia: df = df[df["dia"].str.upper() == dia.upper()]
    if q: df = df[df["nombre"].str.contains(q, case=False) | df["telefono"].astype(str).str.contains(q)]
    df = df.replace([float("inf"), float("-inf")], None).fillna("")
    return df.to_dict(orient="records")

@app.post("/rutas-activas")
def add_ruta_activa(nuevo: NuevoPunto, user=Depends(require_auth)):
    df = read_rutas_excel() if DATA_MODE != "db" else read_rutas_db()
    new_id = int(df["id"].max() + 1 if not df.empty else 1)
    df.loc[len(df)] = {"id": new_id, **nuevo.dict()}
    write_rutas_excel(df)
    return {"status": "ok", "new_id": new_id}

# ============================================================================
# MAPA
# ============================================================================
@app.get("/mapa-puntos")
def mapa_puntos():
    df = read_rutas_db() if DATA_MODE == "db" else read_rutas_excel()
    df = df.dropna(subset=["latitud", "longitud"], how="all")
    df["color"] = df["camion"].apply(lambda c: CAMION_COLORS.get(str(c).upper(), "#1e40af"))
    df = df.replace([float("inf"), float("-inf")], None).fillna("")
    return df.to_dict(orient="records")

# ============================================================================
# LOGIN / USUARIOS
# ============================================================================
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
        if usuario == "admin" and pwd == "admin": rol = "admin"
        else: raise HTTPException(401, "Credenciales inválidas")
    token = jwt_encode({"sub": usuario, "rol": rol})
    audit_log(usuario, "login", {"rol": rol})
    return {"token": token, "rol": rol}

@app.get("/usuarios")
def listar_usuarios(user=Depends(require_admin)):
    if DATA_MODE != "db":
        return [{"usuario": "admin", "rol": "admin", "active": True}]
    conn = db_conn(); cur = conn.cursor()
    cur.execute("SELECT usuario,rol,active,created_at FROM usuarios")
    rows = cur.fetchall(); cur.close(); db_put(conn)
    return [{"usuario": r[0], "rol": r[1], "active": r[2], "created_at": r[3]} for r in rows]

@app.post("/usuarios")
def crear_usuario(u: UsuarioCreate, user=Depends(require_admin)):
    if DATA_MODE != "db":
        raise HTTPException(400, "Solo disponible en modo DB")
    phash = hashlib.sha256(u.password.encode()).hexdigest()
    conn = db_conn(); cur = conn.cursor()
    cur.execute("INSERT INTO usuarios (usuario,password_hash,rol,active) VALUES (%s,%s,%s,TRUE)",
                (u.usuario, phash, u.rol))
    conn.commit(); cur.close(); db_put(conn)
    return {"status": "ok"}

# ============================================================================
# AUDITORÍA
# ============================================================================
@app.get("/auditoria")
def auditoria_list(user=Depends(require_admin)):
    if DATA_MODE != "db":
        return []
    conn = db_conn(); cur = conn.cursor()
    cur.execute("SELECT usuario,accion,metadata,ts_utc FROM auditoria ORDER BY ts_utc DESC LIMIT 200")
    rows = cur.fetchall(); cur.close(); db_put(conn)
    return [{"usuario": r[0], "accion": r[1], "metadata": r[2], "ts": r[3]} for r in rows]

# ============================================================================
# STARTUP
# ============================================================================
@app.on_event("startup")
def startup():
    if EXCEL_FILE.exists():
        log.info(f"🟢 Excel cargado: {EXCEL_FILE}")
    else:
        log.warning(f"🟡 Excel no encontrado — usando datos mock")
    log.info(f"🚀 AguaRuta Backend v2.2 FINAL | DATA_MODE={DATA_MODE}")
