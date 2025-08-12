# routers/entregas.py
from __future__ import annotations

import os
from typing import Optional, Any, Dict, List

import psycopg2
import psycopg2.extras
from psycopg2.pool import SimpleConnectionPool
from fastapi import APIRouter, HTTPException, Query, Path, Body

# ------------------------------------------------------------------
# Conexión a BD (pool)
# ------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DB_URL")
if not DATABASE_URL:
    raise RuntimeError("Falta DATABASE_URL/DB_URL en variables de entorno.")

pool: SimpleConnectionPool = SimpleConnectionPool(
    minconn=1,
    maxconn=8,
    dsn=DATABASE_URL,
)

def _dict_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normaliza tipos que el frontend espera (por ej. Decimal -> float)."""
    for r in rows:
        if "litros" in r and r["litros"] is not None:
            # Algunos drivers devuelven Decimal
            try:
                r["litros"] = float(r["litros"])
            except Exception:
                pass
    return rows

# ------------------------------------------------------------------
# Router
# (en main.py se incluye con prefix="/entregas")
# ------------------------------------------------------------------
router = APIRouter(tags=["Entregas"])

# ------------------------------------------------------------------
# GET /entregas  (lista con filtros)
# ------------------------------------------------------------------
@router.get("", response_model=List[Dict[str, Any]])
def listar_entregas(
    desde: str = Query(..., description="Fecha inicio (YYYY-MM-DD)"),
    hasta: str = Query(..., description="Fecha fin (YYYY-MM-DD)"),
    camion: Optional[str] = Query(None),
    nombre: Optional[str] = Query(None),
    estado: Optional[int] = Query(None),
) -> List[Dict[str, Any]]:
    """
    Devuelve entregas dentro de un rango de fechas con filtros opcionales.
    """
    sql = """
        SELECT
            id, fecha, camion, nombre, litros, estado, motivo, telefono,
            latitud, longitud, foto_url, usuario, creado_en
        FROM entregas
        WHERE fecha BETWEEN %s AND %s
    """
    params: List[Any] = [desde, hasta]

    if camion:
        sql += " AND camion = %s"
        params.append(camion)

    if nombre:
        sql += " AND LOWER(nombre) LIKE LOWER(%s)"
        params.append(f"%{nombre}%")

    if estado is not None:
        sql += " AND estado = %s"
        params.append(estado)

    sql += " ORDER BY fecha DESC, id DESC"

    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() or []
        return _dict_rows(rows)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            pool.putconn(conn)

# ------------------------------------------------------------------
# GET /entregas/detalle/{id}
# ------------------------------------------------------------------
@router.get("/detalle/{id}", response_model=Dict[str, Any])
def detalle_entrega(
    id: int = Path(..., ge=1),
) -> Dict[str, Any]:
    sql = """
        SELECT
            id, fecha, camion, nombre, litros, estado, motivo, telefono,
            latitud, longitud, foto_url, usuario, creado_en
        FROM entregas
        WHERE id = %s
        LIMIT 1
    """
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (id,))
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No se encontró la entrega")
        return _dict_rows([row])[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            pool.putconn(conn)

# ------------------------------------------------------------------
# PUT /entregas/estado/{id}  (actualiza estado/motivo)
# ------------------------------------------------------------------
@router.put("/estado/{id}", response_model=Dict[str, Any])
def actualizar_estado_entrega(
    id: int = Path(..., ge=1),
    estado: int = Body(..., embed=True, description="Nuevo estado (int)"),
    motivo: Optional[str] = Body(None, embed=True),
) -> Dict[str, Any]:
    sql = """
        UPDATE entregas
        SET estado = %s,
            motivo = COALESCE(%s, motivo)
        WHERE id = %s
        RETURNING id, estado, motivo
    """
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (estado, motivo, id))
            row = cur.fetchone()
            conn.commit()
        if not row:
            raise HTTPException(status_code=404, detail="No se encontró la entrega")
        return dict(row)
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            pool.putconn(conn)

# ------------------------------------------------------------------
# DELETE /entregas/{id}
# ------------------------------------------------------------------
@router.delete("/{id}", response_model=Dict[str, Any])
def eliminar_entrega(
    id: int = Path(..., ge=1),
) -> Dict[str, Any]:
    sql = "DELETE FROM entregas WHERE id = %s"
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cur:
            cur.execute(sql, (id,))
            deleted = cur.rowcount
            conn.commit()
        if deleted == 0:
            raise HTTPException(status_code=404, detail="No se encontró la entrega")
        return {"eliminados": deleted}
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            pool.putconn(conn)
