from fastapi import APIRouter
import xml.etree.ElementTree as ET
import zipfile
import os

router = APIRouter()

@router.get("/kml/puntos")
def leer_kml():
    ruta_kmz = "GEO.kmz"
    ruta_kml = "temp.kml"

    # Descomprimir el KMZ
    with zipfile.ZipFile(ruta_kmz, 'r') as z:
        for nombre in z.namelist():
            if nombre.endswith(".kml"):
                z.extract(nombre, ".")
                os.rename(nombre, ruta_kml)
                break

    tree = ET.parse(ruta_kml)
    root = tree.getroot()

    ns = {'kml': 'http://www.opengis.net/kml/2.2'}
    puntos = []

    for placemark in root.findall(".//kml:Placemark", ns):
        nombre = placemark.find("kml:name", ns)
        coords = placemark.find(".//kml:coordinates", ns)

        if nombre is not None and coords is not None:
            partes = coords.text.strip().split(",")
            if len(partes) >= 2:
                lng, lat = float(partes[0]), float(partes[1])
                puntos.append({
                    "nombre": nombre.text.strip(),
                    "lat": lat,
                    "lng": lng
                })

    # Limpiar archivo temporal
    if os.path.exists(ruta_kml):
        os.remove(ruta_kml)

    return puntos
