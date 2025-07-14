from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import Entrega
from schemas import EntregaCreate

router = APIRouter(
    prefix="/api/entregas",
    tags=["entregas"]
)

@router.post("/lote/")
def cargar_lote(entregas: list[EntregaCreate], db: Session = Depends(get_db)):
    objetos = [Entrega(**e.dict()) for e in entregas]
    db.bulk_save_objects(objetos)
    db.commit()
    return {"mensaje": "Entregas cargadas exitosamente", "cantidad": len(objetos)}
