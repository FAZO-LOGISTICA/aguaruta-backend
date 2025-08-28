# backend/routers/cloudinary.py
import os, hashlib, time
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/cloudinary", tags=["cloudinary"])

CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
API_KEY = os.getenv("CLOUDINARY_API_KEY")
API_SECRET = os.getenv("CLOUDINARY_API_SECRET")

class SignResp(BaseModel):
    cloud_name: str
    api_key: str
    timestamp: int
    signature: str
    folder: str

@router.get("/sign", response_model=SignResp)
def sign(folder: str = "aguaruta/evidencia"):
    ts = int(time.time())
    to_sign = f"folder={folder}&timestamp={ts}{API_SECRET}"  # orden alfabético
    signature = hashlib.sha1(to_sign.encode("utf-8")).hexdigest()
    return {
        "cloud_name": CLOUD_NAME,
        "api_key": API_KEY,
        "timestamp": ts,
        "signature": signature,
        "folder": folder,
    }
