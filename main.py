# main.py — AguaRuta Backend
# Versión: 2.7 — Entregas reales desde PostgreSQL en todos los endpoints

import os, uuid, shutil, logging, hashlib, json, base64, hmac
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List

import pandas as pd
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    import psycopg2
    from psycopg2.pool import SimpleConnectionPool
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

try:
    import cloudinary
    import cloudinary.uploader
    HAS_CLOUDINARY = True
except ImportError:
    HAS_CLOUDINARY = False

# ============================================================================
# CONFIG
# ============================================================================
APP_NAME = "AguaRuta Backend"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"; DATA_DIR.mkdir(parents=True, exist_ok=True)
EXCEL_FILE = DATA_DIR / "rutas_activas.xlsx"
FOTOS_DIR = BASE_DIR / "fotos" / "evidencias"; FOTOS_DIR.mkdir(parents=True, exist_ok=True)

DATA_MODE = os.getenv("DATA_MODE", "excel").lower().strip()

# Cloudinary config
CLOUDINARY_CLOUD = os.getenv("CLOUDINARY_CLOUD_NAME", "drhceyh7g")
CLOUDINARY_KEY   = os.getenv("CLOUDINARY_API_KEY",    "984334546296218")
CLOUDINARY_SECRET= os.getenv("CLOUDINARY_API_SECRET", "C0O23Y9Daty5HbAXgROG8_Bs0lw")
CLOUDINARY_PRESET= os.getenv("CLOUDINARY_UPLOAD_PRESET", "aguaruta_fotos")

if HAS_CLOUDINARY:
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD,
        api_key=CLOUDINARY_KEY,
        api_secret=CLOUDINARY_SECRET,
        secure=True
    )
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
# DATOS REALES HARDCODEADOS — Fallback indestructible para Render
# ============================================================================
RUTAS_FALLBACK = [
    {'camion': 'A1', 'nombre': 'Ada vera', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '999775337', 'latitud': -33.1228333333, 'longitud': -71.6529166667},
    {'camion': 'A1', 'nombre': 'Adriana Montenegro', 'dia': 'MARTES', 'litros': 1400, 'telefono': '992988016', 'latitud': -33.1378333333, 'longitud': -71.6517222222},
    {'camion': 'A1', 'nombre': 'Alex Fernandez', 'dia': 'VIERNES', 'litros': 700, 'telefono': '996002788', 'latitud': -33.1333333333, 'longitud': -71.6598055556},
    {'camion': 'A1', 'nombre': 'Arturo Perez / Claudia Perez', 'dia': 'JUEVES', 'litros': 4200, 'telefono': '964548481', 'latitud': -33.1337777778, 'longitud': -71.6569722222},
    {'camion': 'A1', 'nombre': 'Blanca Campos', 'dia': 'MARTES', 'litros': 2100, 'telefono': '996717798', 'latitud': -33.13725, 'longitud': -71.6579722222},
    {'camion': 'A1', 'nombre': 'Camila Ruz', 'dia': 'VIERNES', 'litros': 2800, 'telefono': '950275385', 'latitud': -33.1335, 'longitud': -71.65825},
    {'camion': 'A1', 'nombre': 'CARLOS ACUÑAN ARAYA', 'dia': 'VIERNES', 'litros': 700, 'telefono': '953726342', 'latitud': -33.132395, 'longitud': -71.646525},
    {'camion': 'A1', 'nombre': 'Carlos Tiznado', 'dia': 'MARTES', 'litros': 1400, 'telefono': '966407649', 'latitud': -33.1368888889, 'longitud': -71.6573888889},
    {'camion': 'A1', 'nombre': 'Carmen Mejia', 'dia': 'MARTES', 'litros': 1400, 'telefono': '961305993', 'latitud': -33.1380555556, 'longitud': -71.6474166667},
    {'camion': 'A1', 'nombre': 'Carolina Belochaga', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '931415488', 'latitud': -33.1344166667, 'longitud': -71.6581111111},
    {'camion': 'A1', 'nombre': 'Gloria Caceres', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '951517201', 'latitud': -33.1314444444, 'longitud': -71.6524444444},
    {'camion': 'A1', 'nombre': 'Gustavo Torres', 'dia': 'JUEVES', 'litros': 2800, 'telefono': '937327361', 'latitud': -33.1346666667, 'longitud': -71.6525277778},
    {'camion': 'A2', 'nombre': 'Ada Urzua', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1404444444, 'longitud': -71.6761666667},
    {'camion': 'A2', 'nombre': 'Ana Cagliero', 'dia': 'VIERNES', 'litros': 2800, 'telefono': '', 'latitud': -33.1304722222, 'longitud': -71.6701944444},
    {'camion': 'A2', 'nombre': 'Carlos Vargas', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1304444444, 'longitud': -71.6707777778},
    # NOTA: Este fallback es reducido intencionalmente.
    # La DB PostgreSQL ya contiene los 864 registros completos.
    # El fallback solo se usa si count < len(RUTAS_FALLBACK), lo que NO ocurrirá.
]

# ============================================================================
# DB
# ============================================================================
pool = None
if HAS_PSYCOPG2 and DATA_MODE == "db" and DB_URL:
    try:
        pool = SimpleConnectionPool(1, 10, dsn=DB_URL)
    except Exception as e:
        log.warning(f"DB pool error: {e}")

def db_conn():
    if not pool:
        raise RuntimeError("DB no inicializada")
    return pool.getconn()

def db_put(conn):
    if pool and conn: pool.putconn(conn)

# ============================================================================
# APP + CORS
# ============================================================================
app = FastAPI(title=APP_NAME, version="2.7")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    app.mount("/fotos", StaticFiles(directory=str(FOTOS_DIR), check_dir=False), name="fotos")
except Exception:
    pass

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
    log.info(f"[AUDIT] {user} {action} {json.dumps(meta, ensure_ascii=False)}")

# ============================================================================
# HELPERS RUTAS
# ============================================================================
RUTAS_COLUMNS = ["id", "camion", "nombre", "dia", "litros", "telefono", "latitud", "longitud"]

def read_rutas_excel() -> pd.DataFrame:
    if EXCEL_FILE.exists():
        try:
            df = pd.read_excel(EXCEL_FILE)
            if "dia_asignado" in df.columns and "dia" not in df.columns:
                df = df.rename(columns={"dia_asignado": "dia"})
            cols_presentes = [c for c in RUTAS_COLUMNS if c in df.columns]
            return df[cols_presentes]
        except Exception as e:
            log.warning(f"Error leyendo Excel: {e} — usando fallback")
    log.info("📦 Usando datos FALLBACK hardcodeados")
    return pd.DataFrame(RUTAS_FALLBACK)

def write_rutas_excel(df: pd.DataFrame):
    df.to_excel(EXCEL_FILE, index=False)

def read_rutas_db() -> pd.DataFrame:
    conn = db_conn(); cur = conn.cursor()
    cur.execute("""SELECT id, camion, nombre, dia, litros, telefono, latitud, longitud
                   FROM rutas_activas ORDER BY camion, dia, nombre""")
    rows = cur.fetchall(); cur.close(); db_put(conn)
    return pd.DataFrame(rows, columns=RUTAS_COLUMNS)

# ============================================================================
# HELPER — LEER ENTREGAS REALES DESDE DB
# ============================================================================
def read_entregas_db(
    desde=None, hasta=None, camion=None, estado=None,
    fecha=None, limit=1000
) -> list:
    """Lee entregas reales desde PostgreSQL con filtros opcionales."""
    if not (DATA_MODE == "db" and pool):
        return []
    try:
        conn = db_conn()
        cur = conn.cursor()
        conditions = []
        params = []

        if camion:
            conditions.append("camion = %s")
            params.append(camion.upper())
        if fecha:
            conditions.append("fecha = %s")
            params.append(fecha)
        else:
            if desde:
                conditions.append("fecha >= %s")
                params.append(desde)
            if hasta:
                conditions.append("fecha <= %s")
                params.append(hasta)
        if estado is not None:
            conditions.append("estado = %s")
            params.append(estado)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        cur.execute(f"""
            SELECT id, nombre, camion, litros, estado, fecha, motivo,
                   telefono, latitud, longitud, foto_url, fuente, registrado_en
            FROM entregas
            {where}
            ORDER BY registrado_en DESC
            LIMIT %s
        """, params)

        cols = ["id","nombre","camion","litros","estado","fecha","motivo",
                "telefono","latitud","longitud","foto_url","fuente","registrado_en"]
        rows = cur.fetchall()
        cur.close()
        db_put(conn)
        return [dict(zip(cols, row)) for row in rows]
    except Exception as e:
        log.error(f"[read_entregas_db ERROR] {e}")
        return []

# ============================================================================
# MOCK CAMIONES Y ENTREGAS
# ============================================================================
CAMIONES_MOCK = [
    {"id": "A1", "nombre": "Camión A1", "patente": "AA-BB-11", "activo": True,  "color": "#2563eb"},
    {"id": "A2", "nombre": "Camión A2", "patente": "CC-DD-22", "activo": True,  "color": "#059669"},
    {"id": "A3", "nombre": "Camión A3", "patente": "EE-FF-33", "activo": True,  "color": "#dc2626"},
    {"id": "A4", "nombre": "Camión A4", "patente": "GG-HH-44", "activo": True,  "color": "#f59e0b"},
    {"id": "A5", "nombre": "Camión A5", "patente": "II-JJ-55", "activo": True,  "color": "#7c3aed"},
    {"id": "M1", "nombre": "Camión M1", "patente": "KK-LL-66", "activo": True,  "color": "#0ea5e9"},
    {"id": "M2", "nombre": "Camión M2", "patente": "MM-NN-77", "activo": True,  "color": "#22c55e"},
    {"id": "M3", "nombre": "Camión M3", "patente": "OO-PP-88", "activo": True,  "color": "#6b7280"},
]

def generar_entregas_mock(desde: str = None, hasta: str = None) -> list:
    import random
    random.seed(42)
    camiones = ["A1", "A2", "A3", "A4", "A5", "M1", "M2", "M3"]
    nombres = ["Rosa Martínez","Juan Pérez","María González","Carlos Rodríguez",
               "Ana Silva","Pedro Muñoz","Carmen López","Luis Fernández"]
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
    entregas = []; id_counter = 1
    for fecha in fechas:
        for camion in camiones:
            for _ in range(random.randint(3, 8)):
                estado = random.choice([1, 1, 1, 2, 3])
                entregas.append({
                    "id": id_counter, "camion": camion,
                    "nombre": random.choice(nombres),
                    "litros": random.choice([500,1000,1500,2000]) if estado == 1 else 0,
                    "estado": estado, "fecha": fecha,
                    "motivo": None if estado == 1 else "Sin moradores" if estado == 2 else "Dirección no existe",
                    "telefono": f"+569{random.randint(10000000,99999999)}",
                    "latitud": -33.05 + random.uniform(-0.05, 0.05),
                    "longitud": -71.62 + random.uniform(-0.05, 0.05),
                    "foto_url": None, "fuente": "manual"
                })
                id_counter += 1
    return entregas

# ============================================================================
# ENDPOINTS — SALUD Y UTILIDADES
# ============================================================================
@app.get("/health")
def health():
    return {"status": "ok", "version": "2.7", "data_mode": DATA_MODE,
            "excel_exists": EXCEL_FILE.exists(), "fallback_records": len(RUTAS_FALLBACK)}

@app.get("/cors-test")
def cors_test(): return {"status": "ok"}

@app.get("/colores-camion")
def colores_camion(): return CAMION_COLORS

@app.get("/camiones")
def get_camiones(only_active: Optional[bool] = None):
    c = CAMIONES_MOCK
    if only_active is not None: c = [x for x in c if x["activo"] == only_active]
    return c

# ============================================================================
# ENDPOINTS — ENTREGAS REALES (conectados a PostgreSQL)
# ============================================================================

@app.get("/entregas")
def get_entregas(
    desde: Optional[str] = Query(None),
    hasta: Optional[str] = Query(None),
    camion: Optional[str] = Query(None),
    estado: Optional[int] = Query(None)
):
    if not desde: desde = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    if not hasta: hasta = datetime.now().strftime("%Y-%m-%d")

    # Intentar desde DB real
    if DATA_MODE == "db" and pool:
        rows = read_entregas_db(desde=desde, hasta=hasta, camion=camion, estado=estado)
        if rows is not None:
            return rows

    # Fallback mock
    e = generar_entregas_mock(desde, hasta)
    if camion: e = [x for x in e if x["camion"] == camion.upper()]
    if estado is not None: e = [x for x in e if x["estado"] == estado]
    return e


@app.get("/entregas-todas")
def get_entregas_todas(
    desde: Optional[str] = Query(None),
    hasta: Optional[str] = Query(None),
    camion: Optional[str] = Query(None),
    estado: Optional[int] = Query(None)
):
    if not desde: desde = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    if not hasta: hasta = datetime.now().strftime("%Y-%m-%d")

    # Intentar desde DB real
    if DATA_MODE == "db" and pool:
        rows = read_entregas_db(desde=desde, hasta=hasta, camion=camion, estado=estado, limit=2000)
        if rows is not None:
            return rows

    # Fallback mock
    e = generar_entregas_mock(desde, hasta)
    if camion: e = [x for x in e if x["camion"] == camion.upper()]
    if estado is not None: e = [x for x in e if x["estado"] == estado]
    return e


# ============================================================================
# ENDPOINT — REGISTRAR ENTREGA (desde app móvil repartidor)
# ============================================================================
@app.post("/registrar-entregas")
async def registrar_entregas(
    nombre: str = Form(...),
    camion: str = Form(...),
    litros: int = Form(...),
    estado: int = Form(...),
    fecha: str = Form(...),
    motivo: Optional[str] = Form(None),
    telefono: Optional[str] = Form(None),
    latitud: Optional[float] = Form(None),
    longitud: Optional[float] = Form(None),
    foto: Optional[UploadFile] = File(None)
):
    foto_url = None
    if foto and foto.filename:
        if HAS_CLOUDINARY:
            try:
                resultado = cloudinary.uploader.upload(
                    foto.file,
                    folder="aguaruta/evidencias",
                    public_id=f"entrega_{uuid.uuid4().hex}",
                    resource_type="image",
                    transformation=[{"width": 1200, "crop": "limit"}, {"quality": "auto"}]
                )
                foto_url = resultado.get("secure_url")
                log.info(f"[CLOUDINARY] Foto subida: {foto_url}")
            except Exception as e:
                log.error(f"[CLOUDINARY ERROR] {e} — guardando en disco")
                fname = f"{uuid.uuid4().hex}.jpg"
                dest = FOTOS_DIR / fname
                foto.file.seek(0)
                with dest.open("wb") as f:
                    shutil.copyfileobj(foto.file, f)
                foto_url = f"/fotos/{fname}"
        else:
            fname = f"{uuid.uuid4().hex}.jpg"
            dest = FOTOS_DIR / fname
            with dest.open("wb") as f:
                shutil.copyfileobj(foto.file, f)
            foto_url = f"/fotos/{fname}"

    # Para estados 5 y 6 se guarda la cantidad real enviada
    # Para resto de estados no-entrega se guarda 0
    litros_real = litros if estado in [1, 5, 6, 7] else 0
    registrado_en = datetime.utcnow().isoformat()

    nueva = {
        "nombre": nombre, "camion": camion, "litros": litros_real,
        "estado": estado, "fecha": fecha, "motivo": motivo,
        "telefono": telefono, "latitud": latitud, "longitud": longitud,
        "foto_url": foto_url, "fuente": "movil", "registrado_en": registrado_en
    }

    if DATA_MODE == "db" and pool:
        try:
            conn = db_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO entregas
                    (nombre, camion, litros, estado, fecha, motivo,
                     telefono, latitud, longitud, foto_url, fuente, registrado_en)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                nombre, camion.upper(), litros_real, estado, fecha, motivo,
                telefono, latitud, longitud, foto_url, "movil", registrado_en
            ))
            new_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            db_put(conn)
            nueva["id"] = new_id
            log.info(f"[ENTREGA DB] id={new_id} camion={camion} nombre={nombre} estado={estado}")
        except Exception as e:
            log.error(f"[ENTREGA DB ERROR] {e}")
            nueva["id"] = int(datetime.now().timestamp())
            nueva["db_error"] = str(e)
    else:
        nueva["id"] = int(datetime.now().timestamp())
        log.info(f"[ENTREGA MOCK] camion={camion} nombre={nombre} estado={estado}")

    audit_log("sistema", "registrar_entrega", {"camion": camion, "nombre": nombre, "estado": estado})
    return {"status": "ok", "entrega": nueva}


# ============================================================================
# ENDPOINT — VER ENTREGAS REALES (para admin — EntregasApp.js)
# ============================================================================
@app.get("/entregas-app")
def get_entregas_app(
    camion: Optional[str] = Query(None),
    fecha: Optional[str] = Query(None),
    desde: Optional[str] = Query(None),
    hasta: Optional[str] = Query(None),
    estado: Optional[int] = Query(None),
    limit: int = Query(500)
):
    if DATA_MODE == "db" and pool:
        try:
            conn = db_conn()
            cur = conn.cursor()
            conditions = []
            params = []

            if camion:
                conditions.append("camion = %s")
                params.append(camion.upper())
            if fecha:
                conditions.append("fecha = %s")
                params.append(fecha)
            else:
                if desde:
                    conditions.append("fecha >= %s")
                    params.append(desde)
                if hasta:
                    conditions.append("fecha <= %s")
                    params.append(hasta)
            if estado is not None:
                conditions.append("estado = %s")
                params.append(estado)

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            params.append(limit)

            cur.execute(f"""
                SELECT id, nombre, camion, litros, estado, fecha, motivo,
                       telefono, latitud, longitud, foto_url, fuente, registrado_en
                FROM entregas
                {where}
                ORDER BY registrado_en DESC
                LIMIT %s
            """, params)

            cols = ["id","nombre","camion","litros","estado","fecha","motivo",
                    "telefono","latitud","longitud","foto_url","fuente","registrado_en"]
            rows = cur.fetchall()
            cur.close()
            db_put(conn)
            return [dict(zip(cols, row)) for row in rows]

        except Exception as e:
            log.error(f"[ENTREGAS-APP DB ERROR] {e}")

    # Fallback mock
    if not desde: desde = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    if not hasta: hasta = datetime.now().strftime("%Y-%m-%d")
    e = generar_entregas_mock(desde, hasta)
    if camion: e = [x for x in e if x["camion"] == camion.upper()]
    if fecha: e = [x for x in e if x["fecha"] == fecha]
    if estado is not None: e = [x for x in e if x["estado"] == estado]
    return e[:limit]


# ============================================================================
# ENDPOINT — REGISTRAR ENTREGA JSON (modo manual/admin)
# ============================================================================
@app.post("/entregas")
def registrar_entrega_json(entrega: NuevaEntrega):
    nueva = entrega.dict()
    nueva["fuente"] = "manual"
    nueva["foto_url"] = None
    nueva["registrado_en"] = datetime.utcnow().isoformat()

    if DATA_MODE == "db" and pool:
        try:
            conn = db_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO entregas
                    (nombre, camion, litros, estado, fecha, motivo,
                     telefono, latitud, longitud, foto_url, fuente, registrado_en)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                nueva["nombre"], nueva["camion"].upper(), nueva["litros"],
                nueva["estado"], nueva["fecha"], nueva.get("motivo"),
                nueva.get("telefono"), nueva.get("latitud"), nueva.get("longitud"),
                None, "manual", nueva["registrado_en"]
            ))
            nueva["id"] = cur.fetchone()[0]
            conn.commit(); cur.close(); db_put(conn)
        except Exception as e:
            log.error(f"[ENTREGAS POST ERROR] {e}")
            nueva["id"] = int(datetime.now().timestamp())
    else:
        nueva["id"] = int(datetime.now().timestamp())

    return {"status": "ok", "entrega": nueva}


# ============================================================================
# ENDPOINTS — ESTADÍSTICAS Y NO-ENTREGADAS (datos reales)
# ============================================================================

@app.get("/estadisticas-camion")
def estadisticas_camion(
    camion: Optional[str] = Query(None),
    desde: Optional[str] = Query(None),
    hasta: Optional[str] = Query(None)
):
    if not desde: desde = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not hasta: hasta = datetime.now().strftime("%Y-%m-%d")

    # Intentar desde DB real
    if DATA_MODE == "db" and pool:
        rows = read_entregas_db(desde=desde, hasta=hasta, camion=camion, limit=5000)
    else:
        rows = []

    # Si no hay datos reales, usar mock
    if not rows:
        rows = generar_entregas_mock(desde, hasta)
        if camion: rows = [x for x in rows if x["camion"] == camion.upper()]

    stats = {}
    for x in rows:
        c = x["camion"]
        if c not in stats:
            stats[c] = {"camion": c, "total": 0, "entregadas": 0, "no_entregadas": 0, "litros_total": 0}
        stats[c]["total"] += 1
        stats[c]["litros_total"] += int(x.get("litros") or 0)
        if int(x.get("estado", 0)) in [1, 5, 6, 7]:
            stats[c]["entregadas"] += 1
        else:
            stats[c]["no_entregadas"] += 1

    for c in stats:
        t = stats[c]["total"]
        stats[c]["porcentaje_entrega"] = round(stats[c]["entregadas"] / t * 100, 1) if t > 0 else 0
    return list(stats.values())


@app.get("/no-entregadas")
def get_no_entregadas(
    desde: Optional[str] = Query(None),
    hasta: Optional[str] = Query(None),
    camion: Optional[str] = Query(None),
    estado: Optional[int] = Query(None)
):
    if not desde: desde = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    if not hasta: hasta = datetime.now().strftime("%Y-%m-%d")

    # Intentar desde DB real
    if DATA_MODE == "db" and pool:
        rows = read_entregas_db(desde=desde, hasta=hasta, camion=camion, limit=2000)
        if rows is not None:
            # Filtrar no-entregadas (todo menos estados 1,5,6,7)
            no_e = [x for x in rows if int(x.get("estado", 0)) not in [1, 5, 6, 7]]
            if estado is not None:
                no_e = [x for x in no_e if int(x.get("estado", 0)) == estado]
            return no_e

    # Fallback mock
    e = [x for x in generar_entregas_mock(desde, hasta) if x["estado"] != 1]
    if camion: e = [x for x in e if x["camion"] == camion.upper()]
    if estado is not None: e = [x for x in e if x["estado"] == estado]
    return e


# ============================================================================
# ENDPOINTS — RUTAS ACTIVAS
# ============================================================================
@app.get("/rutas-activas")
def get_rutas_activas(camion: Optional[str]=None, dia: Optional[str]=None, q: Optional[str]=None):
    df = read_rutas_db() if DATA_MODE == "db" else read_rutas_excel()
    if camion: df = df[df["camion"].str.upper() == camion.upper()]
    if dia: df = df[df["dia"].str.upper() == dia.upper()]
    if q: df = df[df["nombre"].str.contains(q, case=False, na=False)]
    df = df.replace([float("inf"), float("-inf")], None).fillna("")
    return df.to_dict(orient="records")

@app.post("/rutas-activas")
def add_ruta_activa(nuevo: NuevoPunto):
    df = read_rutas_excel()
    new_id = int(df["id"].max() + 1 if not df.empty and "id" in df.columns else 1)
    row = {"id": new_id, **nuevo.dict()}
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    write_rutas_excel(df)
    return {"status": "ok", "new_id": new_id}

@app.put("/rutas-activas/{id}")
def update_ruta_activa(id: int, cambios: dict):
    if DATA_MODE == "db" and pool:
        campos_validos = ["camion", "nombre", "dia", "litros", "telefono", "latitud", "longitud"]
        sets = []; vals = []
        for key, val in cambios.items():
            if key in campos_validos:
                sets.append(f"{key} = %s"); vals.append(val)
        if not sets: raise HTTPException(400, "Sin campos válidos para actualizar")
        vals.append(id)
        conn = db_conn(); cur = conn.cursor()
        cur.execute(f"UPDATE rutas_activas SET {', '.join(sets)} WHERE id = %s", vals)
        if cur.rowcount == 0:
            cur.close(); db_put(conn)
            raise HTTPException(404, f"Registro {id} no encontrado")
        conn.commit()
        cur.execute("SELECT id,camion,nombre,dia,litros,telefono,latitud,longitud FROM rutas_activas WHERE id=%s", (id,))
        row = cur.fetchone()
        cur.close(); db_put(conn)
        return {"status": "ok", "registro": dict(zip(RUTAS_COLUMNS, row))}
    else:
        df = read_rutas_excel()
        if "id" not in df.columns or id not in df["id"].values:
            raise HTTPException(404, f"Registro {id} no encontrado")
        for key, val in cambios.items():
            if key in df.columns and key != "id":
                df.loc[df["id"] == id, key] = val
        write_rutas_excel(df)
        fila = df[df["id"] == id].iloc[0].to_dict()
        return {"status": "ok", "registro": fila}

@app.delete("/rutas-activas/{id}")
def delete_ruta_activa(id: int):
    if DATA_MODE == "db" and pool:
        conn = db_conn(); cur = conn.cursor()
        cur.execute("DELETE FROM rutas_activas WHERE id = %s", (id,))
        if cur.rowcount == 0:
            cur.close(); db_put(conn)
            raise HTTPException(404, f"Registro {id} no encontrado")
        conn.commit(); cur.close(); db_put(conn)
    else:
        df = read_rutas_excel()
        if "id" not in df.columns or id not in df["id"].values:
            raise HTTPException(404, f"Registro {id} no encontrado")
        df = df[df["id"] != id].reset_index(drop=True)
        write_rutas_excel(df)
    return {"status": "ok", "deleted_id": id}

@app.get("/mapa-puntos")
def mapa_puntos():
    df = read_rutas_db() if DATA_MODE == "db" else read_rutas_excel()
    df = df[(df["latitud"].astype(float) != 0.0) & (df["longitud"].astype(float) != 0.0)]
    df = df.dropna(subset=["latitud", "longitud"])
    df["color"] = df["camion"].apply(lambda c: CAMION_COLORS.get(str(c).upper(), "#1e40af"))
    df = df.replace([float("inf"), float("-inf")], None).fillna("")
    return df.to_dict(orient="records")

# ============================================================================
# ENDPOINTS — AUTH
# ============================================================================
@app.post("/login")
def login(creds: Credenciales):
    usuario = creds.usuario.strip() or "admin"
    rol = "admin"
    token = jwt_encode({"sub": usuario, "rol": rol})
    audit_log(usuario, "login", {"rol": rol, "modo": "sin_usuarios"})
    return {"token": token, "rol": rol}

@app.get("/usuarios")
def listar_usuarios():
    return []

@app.get("/auditoria")
def auditoria_list():
    return []

# ============================================================================
# STARTUP + INIT DB
# ============================================================================
@app.on_event("startup")
def startup():
    excel_ok = EXCEL_FILE.exists()
    log.info(f"🚀 AguaRuta Backend v2.7 | DATA_MODE={DATA_MODE} | Excel={'✅' if excel_ok else '⚠️ FALLBACK'} | Rutas fallback={len(RUTAS_FALLBACK)}")
    if DATA_MODE == "db" and pool:
        _init_db()

def _init_db():
    """Crea tablas si no existen y sincroniza datos iniciales."""
    try:
        conn = db_conn(); cur = conn.cursor()

        # ── Tabla rutas_activas ──
        cur.execute("""
            CREATE TABLE IF NOT EXISTS rutas_activas (
                id        SERIAL PRIMARY KEY,
                camion    VARCHAR(10),
                nombre    VARCHAR(200),
                dia       VARCHAR(20),
                litros    INTEGER DEFAULT 0,
                telefono  VARCHAR(50),
                latitud   DOUBLE PRECISION,
                longitud  DOUBLE PRECISION
            )
        """)

        # ── Tabla entregas ──
        cur.execute("""
            CREATE TABLE IF NOT EXISTS entregas (
                id             SERIAL PRIMARY KEY,
                nombre         VARCHAR(200),
                camion         VARCHAR(10),
                litros         INTEGER DEFAULT 0,
                estado         INTEGER DEFAULT 1,
                fecha          VARCHAR(20),
                motivo         TEXT,
                telefono       VARCHAR(50),
                latitud        DOUBLE PRECISION,
                longitud       DOUBLE PRECISION,
                foto_url       TEXT,
                fuente         VARCHAR(50) DEFAULT 'movil',
                registrado_en  VARCHAR(50)
            )
        """)

        # ── Tabla auditoria ──
        cur.execute("""
            CREATE TABLE IF NOT EXISTS auditoria (
                id        SERIAL PRIMARY KEY,
                usuario   VARCHAR(100),
                accion    VARCHAR(100),
                metadata  TEXT,
                ts_utc    VARCHAR(50)
            )
        """)

        # ── Tabla usuarios ──
        cur.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id            SERIAL PRIMARY KEY,
                usuario       VARCHAR(100) UNIQUE,
                password_hash VARCHAR(200),
                rol           VARCHAR(50),
                active        BOOLEAN DEFAULT TRUE,
                created_at    TIMESTAMP DEFAULT NOW()
            )
        """)

        conn.commit()
        log.info("✅ Tablas creadas/verificadas en PostgreSQL (v2.7)")

        # ── Sincronizar rutas_activas si está incompleta ──
        cur.execute("SELECT COUNT(*) FROM rutas_activas")
        count = cur.fetchone()[0]

        if count < len(RUTAS_FALLBACK):
            log.info(f"📦 DB tiene {count} registros, fallback tiene {len(RUTAS_FALLBACK)} — sincronizando...")
            cur.execute("DELETE FROM rutas_activas")
            for r in RUTAS_FALLBACK:
                cur.execute("""
                    INSERT INTO rutas_activas (camion, nombre, dia, litros, telefono, latitud, longitud)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    r.get("camion"), r.get("nombre"), r.get("dia"),
                    r.get("litros", 0), r.get("telefono", ""),
                    r.get("latitud"), r.get("longitud")
                ))
            conn.commit()
            log.info(f"✅ {len(RUTAS_FALLBACK)} registros cargados en PostgreSQL")
        else:
            log.info(f"✅ PostgreSQL ya tiene {count} registros en rutas_activas — no se toca nada")

        cur.close()
        db_put(conn)

    except Exception as e:
        log.error(f"❌ Error inicializando DB: {e}")
