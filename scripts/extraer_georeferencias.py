from fastkml import kml
from zipfile import ZipFile
from io import BytesIO
import os

# Ruta del archivo KMZ
archivo_kmz = "GEO.kmz"

# Extraer contenido del KMZ
with ZipFile(archivo_kmz, 'r') as kmz:
    kml_filename = [name for name in kmz.namelist() if name.endswith('.kml')][0]
    kml_data = kmz.read(kml_filename)

# Parsear el KML
k = kml.KML()
k.from_string(kml_data)

# Función para extraer nombres y coordenadas
def extraer_info(kml_obj):
    puntos = []
    for doc in kml_obj.features:
        for folder in doc.features():
            for placemark in folder.features():
                if hasattr(placemark, 'geometry') and placemark.geometry:
                    nombre = placemark.name
                    coords = placemark.geometry.coords[0]
                    puntos.append({
                        "nombre": nombre,
                        "lat": coords[1],
                        "lon": coords[0]
                    })
    return puntos

# Extraer y mostrar
info = extraer_info(k)
print("Puntos encontrados:")
for punto in info:
    print(f"{punto['nombre']}: lat={punto['lat']}, lon={punto['lon']}")

# Guardar como archivo CSV para revisión si quieres
import csv
with open("puntos_extraidos.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["nombre", "lat", "lon"])
    writer.writeheader()
    writer.writerows(info)

print("Archivo puntos_extraidos.csv creado con éxito.")
