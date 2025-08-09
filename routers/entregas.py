# backend/routes/entregas.py
import os
from datetime import date
from typing import Optional, List, Any, Dict

import psycopg2
import psycopg2.extras
from psycopg2.pool import SimpleConnectionPool
from fastapi import APIRouter, Query, HTTPException

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DB_URL")
if not DATABASE_URL:
    raise RuntimeError("Falta DATABASE_URL/DB_URL en variables de entorno.")

pool: SimpleConnectionPool = SimpleConnectionPool(
    minconn=1, maxconn=5, dsn=DATABASE_URL
)

router = APIRouter(prefix="", tags=["entregas"])

def get_conn():
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)

@router.get("/entregas")
def listar_entregas(
    desde: str = Query(..., description="YYYY-MM-DD"),
    hasta: str = Query(..., description="YYYY-MM-DD"),
    camion: Optional[str] = None,
    nombre: Optional[str] = None,
    estado: Optional[int] = None,
) -> List[Dict[str, Any]]:
    sql = """
        SELECT id, fecha, camion, nombre, litros, estado, motivo, telefono,
               latitud, longitud, foto_url, usuario, creado_en
        FROM entregas
        WHERE fecha BETWEEN %s AND %s
    """
    params: List[Any] = [desde, hasta]
    if camion:
        sql += " AND camion = %s"; params.append(camion)
    if nombre:
        sql += " AND LOWER(nombre) LIKE LOWER(%s)"; params.append(f"%{nombre}%")
    if estado is not None:
        sql += " AND estado = %s"; params.append(estado)
    sql += " ORDER BY fecha DESC, id DESC"

    try:
        conn = pool.getconn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close(); pool.putconn(conn)
        # normaliza tipos
        for r in rows:
            if r.get("litros") is not None:
                r["litros"] = float(r["litros"])
        return rows
    except Exception as e:
        try:
            pool.putconn(conn)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))
