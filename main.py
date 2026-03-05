# main.py — AguaRuta Backend
# Versión: 2.3 — Datos reales embebidos como fallback (Render-safe)

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
# DATOS REALES HARDCODEADOS — Fallback indestructible para Render
# Fuente: rutas_activas.xlsx / RutasMapaFinal_con_telefono.json
# ============================================================================
RUTAS_FALLBACK = [
    {"id":1,"camion":"A4","nombre":"Carolina Bravo","dia":"LUNES","litros":2800,"telefono":"","latitud":-33.1156111111,"longitud":-71.7066111111},
    {"id":2,"camion":"A4","nombre":"MARISOL SALVO","dia":"LUNES","litros":700,"telefono":"991448897","latitud":-33.11505,"longitud":-71.681963},
    {"id":3,"camion":"A4","nombre":"Nancy Gomez","dia":"LUNES","litros":2800,"telefono":"","latitud":-33.1149444444,"longitud":-71.7058888889},
    {"id":4,"camion":"A4","nombre":"Saul Zamorano","dia":"LUNES","litros":2800,"telefono":"937635412","latitud":-33.114769,"longitud":-71.690613},
    {"id":5,"camion":"A4","nombre":"CLAUDIA MOLINA GUTIERREZ","dia":"LUNES","litros":700,"telefono":"993424510","latitud":-33.114254,"longitud":-71.68428},
    {"id":6,"camion":"A4","nombre":"REINLADO NAVARRO BAEZA","dia":"LUNES","litros":2800,"telefono":"95004618","latitud":-33.114254,"longitud":-71.68428},
    {"id":7,"camion":"A4","nombre":"MANUEL CAMILO SOZA ARANDA","dia":"LUNES","litros":700,"telefono":"988037222","latitud":-33.114205,"longitud":-71.681613},
    {"id":8,"camion":"A4","nombre":"INES LLANOS FERNANDEZ","dia":"LUNES","litros":700,"telefono":"964344292","latitud":-33.114205,"longitud":-71.681613},
    {"id":9,"camion":"A4","nombre":"ALEJANDRA MEDINA ARMIJO","dia":"LUNES","litros":1400,"telefono":"97776545","latitud":-33.114143,"longitud":-71.685074},
    {"id":10,"camion":"A4","nombre":"Marietta Gonzalez","dia":"LUNES","litros":3500,"telefono":"","latitud":-33.1141111111,"longitud":-71.6890277778},
    {"id":11,"camion":"A4","nombre":"WALTER BELFORD VILLAVICENCIO PEREZ","dia":"LUNES","litros":700,"telefono":"982259816","latitud":-33.113926,"longitud":-71.684943},
    {"id":12,"camion":"A4","nombre":"Diego Novoa","dia":"LUNES","litros":2800,"telefono":"","latitud":-33.1139166667,"longitud":-71.7243055556},
    {"id":13,"camion":"A4","nombre":"CARLOS ERNESTO ZAMORANO IBARRA","dia":"LUNES","litros":1400,"telefono":"961673360","latitud":-33.113838,"longitud":-71.690639},
    {"id":14,"camion":"A4","nombre":"MARIA DEL PILAR FLORES SOTO","dia":"LUNES","litros":700,"telefono":"988001020","latitud":-33.11368,"longitud":-71.705947},
    {"id":15,"camion":"A4","nombre":"Carolina Huidogro","dia":"LUNES","litros":1400,"telefono":"","latitud":-33.11325,"longitud":-71.7049722222},
    {"id":16,"camion":"A4","nombre":"Francisca Ibacache","dia":"LUNES","litros":2800,"telefono":"963486633","latitud":-33.1130555556,"longitud":-71.7246666667},
    {"id":17,"camion":"A4","nombre":"Luis Concha","dia":"LUNES","litros":700,"telefono":"","latitud":-33.1130555556,"longitud":-71.7115},
    {"id":18,"camion":"A4","nombre":"Nelson Barrera","dia":"LUNES","litros":700,"telefono":"","latitud":-33.1129722222,"longitud":-71.7115277778},
    {"id":19,"camion":"A4","nombre":"Rommy Ramos","dia":"MARTES","litros":700,"telefono":"920310240","latitud":-33.1129444444,"longitud":-71.7110555556},
    {"id":20,"camion":"A4","nombre":"Mitzi Riquelme","dia":"MARTES","litros":700,"telefono":"","latitud":-33.1127777778,"longitud":-71.6921944444},
    {"id":21,"camion":"A4","nombre":"ANA ESPINOZA VALDEBENITO","dia":"MARTES","litros":700,"telefono":"962211785","latitud":-33.112545,"longitud":-71.676914},
    {"id":22,"camion":"A4","nombre":"JEANNETTE HERRERA GUZMAN","dia":"MARTES","litros":2100,"telefono":"971356345","latitud":-33.112232,"longitud":-71.712715},
    {"id":23,"camion":"A4","nombre":"Inger Albapiz","dia":"MARTES","litros":2100,"telefono":"","latitud":-33.1121111111,"longitud":-71.7096111111},
    {"id":24,"camion":"A4","nombre":"MAURICIO ROLANDO CASTRO SOLAR","dia":"MARTES","litros":1400,"telefono":"999313132","latitud":-33.111429,"longitud":-71.676522},
    {"id":25,"camion":"A4","nombre":"ENRIQUE SILVA SANHUEZA","dia":"MARTES","litros":2100,"telefono":"995580164","latitud":-33.111429,"longitud":-71.676522},
    {"id":26,"camion":"A4","nombre":"PLINIO ESCOTORIN ALVAREZ","dia":"MARTES","litros":700,"telefono":"986540700","latitud":-33.111385,"longitud":-71.686646},
    {"id":27,"camion":"A4","nombre":"Jeniffer Gonzalez","dia":"MARTES","litros":3500,"telefono":"","latitud":-33.1110833333,"longitud":-71.7163055556},
    {"id":28,"camion":"A4","nombre":"BERTHA CONTRERAS MORALES","dia":"MARTES","litros":700,"telefono":"974537699","latitud":-33.111073,"longitud":-71.690811},
    {"id":29,"camion":"A4","nombre":"PABLO BENJAMIN CARQUIN PENA","dia":"MARTES","litros":2100,"telefono":"936238567","latitud":-33.111002,"longitud":-71.688537},
    {"id":30,"camion":"A4","nombre":"BERENICE PARRAGUEZ FUENTES","dia":"MARTES","litros":700,"telefono":"966000469","latitud":-33.110198,"longitud":-71.712706},
    {"id":31,"camion":"A4","nombre":"Yonathan Barros","dia":"MARTES","litros":700,"telefono":"","latitud":-33.1101388889,"longitud":-71.7125833333},
    {"id":32,"camion":"A4","nombre":"Ivonn Arevalo","dia":"MARTES","litros":4200,"telefono":"","latitud":-33.1099722222,"longitud":-71.7126944444},
    {"id":33,"camion":"A4","nombre":"ALEJANDRA VERA","dia":"MARTES","litros":1400,"telefono":"958804056","latitud":-33.10977,"longitud":-71.67717},
    {"id":34,"camion":"A4","nombre":"OSCAR ALEJANDRO VALENZUELA MARTINEZ","dia":"MARTES","litros":700,"telefono":"969154645","latitud":-33.109365,"longitud":-71.68486},
    {"id":35,"camion":"A4","nombre":"benedicta Yañez","dia":"MARTES","litros":1400,"telefono":"","latitud":-33.10925,"longitud":-71.7007222222},
    {"id":36,"camion":"A4","nombre":"PAMELA GALLARDO NAVARRETE","dia":"MARTES","litros":700,"telefono":"971948287","latitud":-33.108974,"longitud":-71.678629},
    {"id":37,"camion":"A4","nombre":"YENNIFER CAMPOS PEREIRA","dia":"MIERCOLES","litros":700,"telefono":"978637917","latitud":-33.108962,"longitud":-71.681565},
    {"id":38,"camion":"A4","nombre":"PATRICIO NAZAR VIACAVA","dia":"MIERCOLES","litros":700,"telefono":"982748244","latitud":-33.108962,"longitud":-71.681565},
    {"id":39,"camion":"A4","nombre":"AURORA BRAVO SEGURA","dia":"MIERCOLES","litros":700,"telefono":"992823772","latitud":-33.108886,"longitud":-71.699291},
    {"id":40,"camion":"A4","nombre":"GRACE TORREALBA FERNANDEZ","dia":"MIERCOLES","litros":700,"telefono":"971277099","latitud":-33.108817,"longitud":-71.699353},
    {"id":41,"camion":"A4","nombre":"Luisa Machuca","dia":"MIERCOLES","litros":2800,"telefono":"","latitud":-33.1084722222,"longitud":-71.7159722222},
    {"id":42,"camion":"A4","nombre":"MARIA CECILIA ZAMORANO ORTIZ","dia":"MIERCOLES","litros":1400,"telefono":"995887649","latitud":-33.107991,"longitud":-71.672386},
    {"id":43,"camion":"A4","nombre":"ANTONIO DANIEL BARBOSA RIFAD","dia":"MIERCOLES","litros":1400,"telefono":"996124659","latitud":-33.107969,"longitud":-71.698364},
    {"id":44,"camion":"A4","nombre":"NELSON BAEZ SAAVEDRA","dia":"MIERCOLES","litros":2100,"telefono":"996139494","latitud":-33.107914,"longitud":-71.672737},
    {"id":45,"camion":"A4","nombre":"Maria Conejeros","dia":"MIERCOLES","litros":1400,"telefono":"","latitud":-33.1078611111,"longitud":-71.7146111111},
    {"id":46,"camion":"A4","nombre":"GISELA RIFFO KLUMPP","dia":"MIERCOLES","litros":1400,"telefono":"952275855","latitud":-33.107823,"longitud":-71.671241},
    {"id":47,"camion":"A4","nombre":"Domingo Herrera","dia":"MIERCOLES","litros":700,"telefono":"","latitud":-33.106657,"longitud":-71.710612},
    {"id":48,"camion":"A4","nombre":"MATILDE ESPINOZA GONZALEZ","dia":"MIERCOLES","litros":700,"telefono":"99218324","latitud":-33.106552,"longitud":-71.719681},
    {"id":49,"camion":"A4","nombre":"LAURA MARIA GARRIDO AVENDANO","dia":"MIERCOLES","litros":700,"telefono":"968316880","latitud":-33.105563,"longitud":-71.685051},
    {"id":50,"camion":"A4","nombre":"CARMEN VIDAL","dia":"MIERCOLES","litros":1400,"telefono":"986826405","latitud":-33.105397,"longitud":-71.680495},
    {"id":51,"camion":"A4","nombre":"Victor Acuña","dia":"MIERCOLES","litros":2100,"telefono":"","latitud":-33.1053611111,"longitud":-71.7203611111},
    {"id":52,"camion":"A4","nombre":"Pamela Garcia","dia":"MIERCOLES","litros":1400,"telefono":"","latitud":-33.1051388889,"longitud":-71.7188611111},
    {"id":53,"camion":"A4","nombre":"Lucia Cartagena","dia":"JUEVES","litros":700,"telefono":"","latitud":-33.1048055556,"longitud":-71.7182222222},
    {"id":54,"camion":"A4","nombre":"Reina Argueta","dia":"JUEVES","litros":700,"telefono":"","latitud":-33.1026388889,"longitud":-71.7248611111},
    {"id":55,"camion":"A4","nombre":"JENNIFER SOLAR OVIEDO","dia":"JUEVES","litros":1400,"telefono":"962158870","latitud":-33.100609,"longitud":-71.667515},
    {"id":56,"camion":"A4","nombre":"Hector Campaña","dia":"JUEVES","litros":3500,"telefono":"","latitud":-33.09275,"longitud":-71.729},
    {"id":57,"camion":"A4","nombre":"Daniela Carriel","dia":"JUEVES","litros":4200,"telefono":"","latitud":0.0,"longitud":0.0},
    {"id":58,"camion":"A4","nombre":"Paola Maturana","dia":"JUEVES","litros":700,"telefono":"","latitud":0.0,"longitud":0.0},
    {"id":59,"camion":"A4","nombre":"Marianela Torreblanca","dia":"JUEVES","litros":2100,"telefono":"","latitud":0.0,"longitud":0.0},
    {"id":60,"camion":"A4","nombre":"Patricio Salinas","dia":"JUEVES","litros":3500,"telefono":"","latitud":0.0,"longitud":0.0},
    {"id":61,"camion":"A4","nombre":"Claudia Berrios","dia":"VIERNES","litros":2100,"telefono":"","latitud":0.0,"longitud":0.0},
    {"id":62,"camion":"A4","nombre":"Maria Nuñez","dia":"VIERNES","litros":1400,"telefono":"995060794","latitud":0.0,"longitud":0.0},
    # A1
    {"id":100,"camion":"A1","nombre":"Manuel Varas","dia":"LUNES","litros":700,"telefono":"","latitud":-33.1498888889,"longitud":-71.6563055556},
    {"id":101,"camion":"A1","nombre":"Claudio Mardones","dia":"LUNES","litros":2800,"telefono":"966051923","latitud":-33.1436944444,"longitud":-71.6557222222},
    {"id":102,"camion":"A1","nombre":"Paola Cisternas","dia":"LUNES","litros":2100,"telefono":"","latitud":-33.1429166667,"longitud":-71.6508055556},
    {"id":103,"camion":"A1","nombre":"IVAN TAPIA SALAZAR","dia":"LUNES","litros":2800,"telefono":"974022382","latitud":-33.142654,"longitud":-71.652681},
    {"id":104,"camion":"A1","nombre":"Gumercindo Letelier","dia":"LUNES","litros":700,"telefono":"954934114","latitud":-33.1426388889,"longitud":-71.6545277778},
    {"id":105,"camion":"A1","nombre":"RAUL JIMENEZ","dia":"LUNES","litros":1400,"telefono":"935921913","latitud":-33.1425719,"longitud":-71.6580506},
    {"id":106,"camion":"A1","nombre":"Luis Torres","dia":"LUNES","litros":1400,"telefono":"998516365","latitud":-33.1425,"longitud":-71.6578611111},
    {"id":107,"camion":"A1","nombre":"SERGIO CASTILLO MUÑOZ","dia":"LUNES","litros":1400,"telefono":"989383832","latitud":-33.142356,"longitud":-71.652628},
    {"id":108,"camion":"A1","nombre":"Leo Dan Santibañez","dia":"LUNES","litros":2800,"telefono":"","latitud":-33.1420555556,"longitud":-71.6549722222},
    {"id":109,"camion":"A1","nombre":"Karina Jiles","dia":"LUNES","litros":3500,"telefono":"","latitud":-33.1420277778,"longitud":-71.6499166667},
    {"id":110,"camion":"A1","nombre":"Silvia Paulino","dia":"LUNES","litros":2800,"telefono":"","latitud":-33.1418888889,"longitud":-71.6518055556},
    {"id":111,"camion":"A1","nombre":"Javiera Martinez","dia":"LUNES","litros":2100,"telefono":"","latitud":-33.1416666667,"longitud":-71.6521944444},
    {"id":112,"camion":"A1","nombre":"Marcela Salazar","dia":"LUNES","litros":2100,"telefono":"952286017","latitud":-33.1409444444,"longitud":-71.6480277778},
    {"id":113,"camion":"A1","nombre":"Sandra Jimenez","dia":"MARTES","litros":700,"telefono":"963481259","latitud":-33.1393611111,"longitud":-71.6471111111},
    {"id":114,"camion":"A1","nombre":"Nora Araya","dia":"MARTES","litros":2800,"telefono":"","latitud":-33.1385,"longitud":-71.6594722222},
    {"id":115,"camion":"A1","nombre":"FELICIANO LETELIER","dia":"MARTES","litros":2100,"telefono":"995088679","latitud":-33.137357,"longitud":-71.652458},
    {"id":116,"camion":"A1","nombre":"Evelyn Salina","dia":"MIERCOLES","litros":2800,"telefono":"952584838","latitud":-33.1365833333,"longitud":-71.6468888889},
    {"id":117,"camion":"A1","nombre":"GRACIELA MALLEA JAQUE","dia":"MIERCOLES","litros":700,"telefono":"971382513","latitud":-33.135866,"longitud":-71.657895},
    {"id":118,"camion":"A1","nombre":"Juan Lorca","dia":"MIERCOLES","litros":700,"telefono":"976789463","latitud":-33.13575,"longitud":-71.6575},
    {"id":119,"camion":"A1","nombre":"Paula Galvan","dia":"MIERCOLES","litros":2800,"telefono":"","latitud":-33.1357222222,"longitud":-71.6626388889},
    {"id":120,"camion":"A1","nombre":"JUAN CARLOS PEÑA GALAZ","dia":"JUEVES","litros":2100,"telefono":"971743108","latitud":-33.134873,"longitud":-71.658447},
    {"id":121,"camion":"A1","nombre":"Camila Ruz","dia":"VIERNES","litros":2800,"telefono":"","latitud":-33.1335,"longitud":-71.65825},
    {"id":122,"camion":"A1","nombre":"Sergio Nuñez","dia":"VIERNES","litros":3500,"telefono":"","latitud":-33.1334722222,"longitud":-71.6616111111},
    {"id":123,"camion":"A1","nombre":"Paloma Toloza","dia":"VIERNES","litros":2800,"telefono":"","latitud":-33.1202222222,"longitud":-71.6529444444},
    # A2
    {"id":200,"camion":"A2","nombre":"Manuel Busto","dia":"LUNES","litros":1000,"telefono":"","latitud":-33.1500833333,"longitud":-71.6663333333},
    {"id":201,"camion":"A2","nombre":"Alex Garcia","dia":"LUNES","litros":1000,"telefono":"","latitud":-33.1499722222,"longitud":-71.6680833333},
    {"id":202,"camion":"A2","nombre":"Olga Carrasco","dia":"LUNES","litros":2000,"telefono":"","latitud":-33.1496388889,"longitud":-71.6704722222},
    {"id":203,"camion":"A2","nombre":"Jocelyn Carvajal","dia":"LUNES","litros":2000,"telefono":"","latitud":-33.1493611111,"longitud":-71.6713055556},
    {"id":204,"camion":"A2","nombre":"NANCY SALGADO SOTO","dia":"LUNES","litros":700,"telefono":"942623326","latitud":-33.149202,"longitud":-71.672589},
    {"id":205,"camion":"A2","nombre":"Martin Villancura","dia":"LUNES","litros":2800,"telefono":"","latitud":-33.14325,"longitud":-71.6825833333},
    {"id":206,"camion":"A2","nombre":"YANIRA EWERT MIRANDA","dia":"LUNES","litros":1400,"telefono":"971894188","latitud":-33.140469,"longitud":-71.685028},
    {"id":207,"camion":"A2","nombre":"Aracely Morales","dia":"MARTES","litros":2100,"telefono":"","latitud":-33.1404444444,"longitud":-71.6812222222},
    {"id":208,"camion":"A2","nombre":"JORGE LUIS REYES BUSTAMANTE","dia":"MARTES","litros":2100,"telefono":"991884544","latitud":-33.139718,"longitud":-71.67984},
    {"id":209,"camion":"A2","nombre":"Carlos Cambrias","dia":"MARTES","litros":3500,"telefono":"","latitud":-33.1396666667,"longitud":-71.6833888889},
    {"id":210,"camion":"A2","nombre":"Danitza Serrano","dia":"MIERCOLES","litros":2800,"telefono":"966049146","latitud":-33.1377222222,"longitud":-71.6770277778},
    {"id":211,"camion":"A2","nombre":"ASTRID ALARCON MUÑOZ","dia":"MIERCOLES","litros":2800,"telefono":"995867540","latitud":-33.135743,"longitud":-71.673064},
    {"id":212,"camion":"A2","nombre":"Zulema Manriquez","dia":"JUEVES","litros":3500,"telefono":"959626876","latitud":-33.1352222222,"longitud":-71.67275},
    {"id":213,"camion":"A2","nombre":"Aldo Molina","dia":"JUEVES","litros":4200,"telefono":"","latitud":-33.1339166667,"longitud":-71.6677777778},
    {"id":214,"camion":"A2","nombre":"Cristian Aguirre","dia":"VIERNES","litros":2100,"telefono":"938641807","latitud":-33.1327222222,"longitud":-71.6711111111},
    {"id":215,"camion":"A2","nombre":"Marcelo Aravena","dia":"VIERNES","litros":2800,"telefono":"945131165","latitud":-33.1300833333,"longitud":-71.6678611111},
    {"id":216,"camion":"A2","nombre":"Ana Cagliero","dia":"VIERNES","litros":2800,"telefono":"","latitud":-33.1304722222,"longitud":-71.6701944444},
    # A3
    {"id":300,"camion":"A3","nombre":"Jaime Muñoz","dia":"LUNES","litros":1400,"telefono":"968253023","latitud":-33.1405833333,"longitud":-71.6811111111},
    {"id":301,"camion":"A3","nombre":"JACQUELINE DEL CARMEN GARCIA GARRIDO","dia":"LUNES","litros":2800,"telefono":"964352116","latitud":-33.129335,"longitud":-71.679557},
    {"id":302,"camion":"A3","nombre":"ELBA ORTIZ SANHUEZA","dia":"LUNES","litros":3500,"telefono":"978697867","latitud":-33.129296,"longitud":-71.663751},
    {"id":303,"camion":"A3","nombre":"LUIS QUINTEROS CARVAJAL","dia":"LUNES","litros":2100,"telefono":"988521933","latitud":-33.129299,"longitud":-71.665202},
    {"id":304,"camion":"A3","nombre":"Marcelo Carrasco","dia":"LUNES","litros":2800,"telefono":"","latitud":-33.1293055556,"longitud":-71.6631666667},
    {"id":305,"camion":"A3","nombre":"MARIA ELIANA LLAITUL PAREDES","dia":"MARTES","litros":2800,"telefono":"976019526","latitud":-33.127846,"longitud":-71.668655},
    {"id":306,"camion":"A3","nombre":"Yarerly Reinoso","dia":"MIERCOLES","litros":3500,"telefono":"","latitud":-33.125323,"longitud":-71.66547},
    {"id":307,"camion":"A3","nombre":"Luis Horta","dia":"MIERCOLES","litros":2800,"telefono":"940001975","latitud":-33.1246944444,"longitud":-71.6834722222},
    {"id":308,"camion":"A3","nombre":"NELSON PIZARRO VILLEGAS","dia":"MIERCOLES","litros":2800,"telefono":"996956049","latitud":-33.124345,"longitud":-71.672358},
    {"id":309,"camion":"A3","nombre":"Jennifer Estay","dia":"JUEVES","litros":2800,"telefono":"","latitud":-33.122615,"longitud":-71.676115},
    {"id":310,"camion":"A3","nombre":"Gaston Bizama","dia":"JUEVES","litros":2800,"telefono":"","latitud":-33.1221388889,"longitud":-71.674},
    {"id":311,"camion":"A3","nombre":"VICTOR MODINGER","dia":"VIERNES","litros":3500,"telefono":"949313608","latitud":-33.121179,"longitud":-71.675626},
    {"id":312,"camion":"A3","nombre":"PABLO FIGUEROA DINAMARCA","dia":"VIERNES","litros":2800,"telefono":"966525774","latitud":-33.120034,"longitud":-71.680649},
    {"id":313,"camion":"A3","nombre":"Homero Sepulveda","dia":"VIERNES","litros":2800,"telefono":"","latitud":-33.1146944444,"longitud":-71.6696944444},
    # A5
    {"id":400,"camion":"A5","nombre":"Ingrid Mall","dia":"LUNES","litros":2800,"telefono":"","latitud":-33.1339444444,"longitud":-71.6991944444},
    {"id":401,"camion":"A5","nombre":"PATRICIA VALENZUELA","dia":"LUNES","litros":3500,"telefono":"979577483","latitud":-33.129068,"longitud":-71.695462},
    {"id":402,"camion":"A5","nombre":"Ximena Latapiat","dia":"LUNES","litros":2800,"telefono":"","latitud":-33.1246666667,"longitud":-71.7025555556},
    {"id":403,"camion":"A5","nombre":"FRANCISCA NAVARRO DIAZ","dia":"LUNES","litros":1400,"telefono":"959514435","latitud":-33.124738,"longitud":-71.701935},
    {"id":404,"camion":"A5","nombre":"Raquel Araya","dia":"LUNES","litros":2100,"telefono":"","latitud":-33.1276111111,"longitud":-71.6954722222},
    {"id":405,"camion":"A5","nombre":"Claudia Duran","dia":"MARTES","litros":2800,"telefono":"","latitud":-33.1225277778,"longitud":-71.6885277778},
    {"id":406,"camion":"A5","nombre":"pamela Alegria","dia":"MARTES","litros":2800,"telefono":"936269288","latitud":-33.1218333333,"longitud":-71.7139166667},
    {"id":407,"camion":"A5","nombre":"Valeria Olguin","dia":"MIERCOLES","litros":2800,"telefono":"932522048","latitud":-33.1203888889,"longitud":-71.7075555556},
    {"id":408,"camion":"A5","nombre":"Julio Paz Lobos","dia":"MIERCOLES","litros":4200,"telefono":"","latitud":-33.11975,"longitud":-71.71125},
    {"id":409,"camion":"A5","nombre":"Alia Fares","dia":"MIERCOLES","litros":2100,"telefono":"","latitud":-33.1189444444,"longitud":-71.69775},
    {"id":410,"camion":"A5","nombre":"VERONICA PIZARRO SANTANDER","dia":"JUEVES","litros":3500,"telefono":"936350003","latitud":-33.118608,"longitud":-71.681842},
    {"id":411,"camion":"A5","nombre":"Juan A. Olivares O.","dia":"JUEVES","litros":2800,"telefono":"","latitud":-33.11875,"longitud":-71.6976388889},
    {"id":412,"camion":"A5","nombre":"Veronica Moraga","dia":"VIERNES","litros":3500,"telefono":"","latitud":-33.1174444444,"longitud":-71.6728611111},
    {"id":413,"camion":"A5","nombre":"Camila Bustos","dia":"VIERNES","litros":2800,"telefono":"","latitud":-33.1169444444,"longitud":-71.6965833333},
    {"id":414,"camion":"A5","nombre":"BORIS MARCELO OYARZO LEAL","dia":"VIERNES","litros":2800,"telefono":"951570040","latitud":-33.116821,"longitud":-71.684753},
    {"id":415,"camion":"A5","nombre":"Zuleima manrriquez","dia":"VIERNES","litros":2800,"telefono":"","latitud":-33.1163611111,"longitud":-71.6885833333},
    # M1
    {"id":500,"camion":"M1","nombre":"Raquel Mancilla","dia":"LUNES","litros":2800,"telefono":"","latitud":-33.12775,"longitud":-71.6599722222},
    {"id":501,"camion":"M1","nombre":"ELIZABETH GARCIA REYES","dia":"LUNES","litros":3500,"telefono":"993304861","latitud":-33.126669,"longitud":-71.663535},
    {"id":502,"camion":"M1","nombre":"Hilda Martinez","dia":"LUNES","litros":2100,"telefono":"956361054","latitud":-33.126138,"longitud":-71.662741},
    {"id":503,"camion":"M1","nombre":"ANA ESPINA ESPINA","dia":"LUNES","litros":2800,"telefono":"953286708","latitud":-33.124481,"longitud":-71.661102},
    {"id":504,"camion":"M1","nombre":"CARMEN LEON MAUREIRA","dia":"LUNES","litros":4200,"telefono":"962156821","latitud":-33.112921,"longitud":-71.663423},
    {"id":505,"camion":"M1","nombre":"Marcela Quiroz","dia":"LUNES","litros":3500,"telefono":"","latitud":-33.1146944444,"longitud":-71.6611944444},
    {"id":506,"camion":"M1","nombre":"Carolina Concha","dia":"MIERCOLES","litros":3500,"telefono":"987685290","latitud":-33.12189,"longitud":-71.666323},
    {"id":507,"camion":"M1","nombre":"CELSA JENNY CARDENAS ORTEGA","dia":"MIERCOLES","litros":4200,"telefono":"974839924","latitud":-33.12153,"longitud":-71.66557},
    {"id":508,"camion":"M1","nombre":"ELSA GAETE JEREZ","dia":"JUEVES","litros":2800,"telefono":"972780298","latitud":-33.118334,"longitud":-71.663611},
    {"id":509,"camion":"M1","nombre":"Maria Inostroza","dia":"JUEVES","litros":2800,"telefono":"978120998","latitud":-33.11925,"longitud":-71.6627222222},
    {"id":510,"camion":"M1","nombre":"Laura Espejo","dia":"JUEVES","litros":3500,"telefono":"933487689","latitud":-33.1154722222,"longitud":-71.6618611111},
    {"id":511,"camion":"M1","nombre":"SOLEDAD MYRIAM RODRIGUEZ MANCILLA","dia":"VIERNES","litros":2800,"telefono":"981890934","latitud":-33.112954,"longitud":-71.663846},
    {"id":512,"camion":"M1","nombre":"Joaquin Gonzalez Arevalos","dia":"VIERNES","litros":3500,"telefono":"","latitud":-33.1146944444,"longitud":-71.6610555556},
    # M2
    {"id":600,"camion":"M2","nombre":"Maria Martinez","dia":"LUNES","litros":700,"telefono":"939694772","latitud":-33.1357222222,"longitud":-71.6581944444},
    {"id":601,"camion":"M2","nombre":"ELIAS RIVERA VALDIVIA","dia":"LUNES","litros":3500,"telefono":"956930790","latitud":-33.135565,"longitud":-71.684784},
    {"id":602,"camion":"M2","nombre":"PAULA LOPEZ MARTIN","dia":"LUNES","litros":2800,"telefono":"989428502","latitud":-33.134775,"longitud":-71.682011},
    {"id":603,"camion":"M2","nombre":"Rogelio Canales","dia":"LUNES","litros":4200,"telefono":"","latitud":-33.1347222222,"longitud":-71.6806388889},
    {"id":604,"camion":"M2","nombre":"PATRICIA ALVAREZ MIQUEL","dia":"LUNES","litros":2800,"telefono":"962714265","latitud":-33.134328,"longitud":-71.686365},
    {"id":605,"camion":"M2","nombre":"Rosa Vidal","dia":"LUNES","litros":2800,"telefono":"","latitud":-33.1331388889,"longitud":-71.6800833333},
    {"id":606,"camion":"M2","nombre":"Kamila Pasten","dia":"MARTES","litros":2100,"telefono":"981441852","latitud":-33.13216,"longitud":-71.686218},
    {"id":607,"camion":"M2","nombre":"Carolina Quitral","dia":"MARTES","litros":3500,"telefono":"","latitud":-33.1317777778,"longitud":-71.67575},
    {"id":608,"camion":"M2","nombre":"Juan Diaz Silva","dia":"MARTES","litros":2800,"telefono":"","latitud":-33.1318055556,"longitud":-71.6783611111},
    {"id":609,"camion":"M2","nombre":"ALEJANDRO CORTEZ CONTRERAS","dia":"MIERCOLES","litros":3500,"telefono":"998750720","latitud":-33.129485,"longitud":-71.685001},
    {"id":610,"camion":"M2","nombre":"Isabel Concha","dia":"MIERCOLES","litros":2800,"telefono":"","latitud":-33.1291388889,"longitud":-71.6711944444},
    {"id":611,"camion":"M2","nombre":"German Delgado","dia":"JUEVES","litros":4200,"telefono":"","latitud":-33.128936,"longitud":-71.681667},
    {"id":612,"camion":"M2","nombre":"Miguel Vargas","dia":"JUEVES","litros":2800,"telefono":"","latitud":-33.128435,"longitud":-71.676645},
    {"id":613,"camion":"M2","nombre":"Maricela Perez","dia":"VIERNES","litros":4200,"telefono":"","latitud":-33.126108,"longitud":-71.675645},
    {"id":614,"camion":"M2","nombre":"Marisol Mendoza","dia":"VIERNES","litros":3500,"telefono":"","latitud":-33.124335,"longitud":-71.678157},
    {"id":615,"camion":"M2","nombre":"Escuela El Bosque","dia":"VIERNES","litros":3500,"telefono":"","latitud":-33.1265620932,"longitud":-71.6787135387},
    # M3
    {"id":700,"camion":"M3","nombre":"MOISES SOTO","dia":"LUNES","litros":4900,"telefono":"","latitud":-33.1434444444,"longitud":-71.6523333333},
    {"id":701,"camion":"M3","nombre":"Arnaldo Henriquez","dia":"LUNES","litros":5600,"telefono":"","latitud":-33.1320833333,"longitud":-71.6796666667},
    {"id":702,"camion":"M3","nombre":"JOSE RODRIGUEZ","dia":"LUNES","litros":4900,"telefono":"","latitud":-33.1293888889,"longitud":-71.6653333333},
    {"id":703,"camion":"M3","nombre":"SALOME MONTENEGRO","dia":"LUNES","litros":4900,"telefono":"983051532","latitud":-33.1269166667,"longitud":-71.66625},
    {"id":704,"camion":"M3","nombre":"PEDRO RETAMAL","dia":"LUNES","litros":4900,"telefono":"","latitud":-33.1267777778,"longitud":-71.6814166667},
    {"id":705,"camion":"M3","nombre":"TOMAS CAMPO","dia":"LUNES","litros":4900,"telefono":"","latitud":-33.12525,"longitud":-71.6596944444},
    {"id":706,"camion":"M3","nombre":"BASTIAN ESPINA","dia":"LUNES","litros":4900,"telefono":"","latitud":-33.1225277778,"longitud":-71.6641666667},
    {"id":707,"camion":"M3","nombre":"LUIS ALLENDE","dia":"MARTES","litros":2500,"telefono":"","latitud":-33.1196825963,"longitud":-71.6919259173},
    {"id":708,"camion":"M3","nombre":"ESTEFANI MIRANDA","dia":"MARTES","litros":4900,"telefono":"","latitud":-33.1195555556,"longitud":-71.7069166667},
    {"id":709,"camion":"M3","nombre":"RUBEN TAPIA SOSSA","dia":"MARTES","litros":4900,"telefono":"","latitud":-33.1183611111,"longitud":-71.7024166667},
    {"id":710,"camion":"M3","nombre":"Dominique Zapata","dia":"MARTES","litros":5600,"telefono":"","latitud":-33.104888,"longitud":-71.667635},
    {"id":711,"camion":"M3","nombre":"ESTANQUE TIO EMILIO","dia":"MARTES","litros":10000,"telefono":"","latitud":0.0,"longitud":0.0},
    {"id":712,"camion":"M3","nombre":"ESTANQUE DON ROBERTO","dia":"MARTES","litros":10000,"telefono":"","latitud":0.0,"longitud":0.0},
    {"id":713,"camion":"M3","nombre":"ESTANQUE MEMBRILLAR","dia":"MIERCOLES","litros":30000,"telefono":"","latitud":0.0,"longitud":0.0},
    {"id":714,"camion":"M3","nombre":"ESTANQUE ESCUELA EL BOSQUE","dia":"MIERCOLES","litros":5000,"telefono":"","latitud":0.0,"longitud":0.0},
    {"id":715,"camion":"M3","nombre":"ESTANQUE ESCUELA EL BOSQUE","dia":"JUEVES","litros":5000,"telefono":"","latitud":0.0,"longitud":0.0},
    {"id":716,"camion":"M3","nombre":"ESTANQUE QUINTAY 2","dia":"JUEVES","litros":10000,"telefono":"","latitud":0.0,"longitud":0.0},
    {"id":717,"camion":"M3","nombre":"ESTANQUE LOS BOLDOS","dia":"JUEVES","litros":10000,"telefono":"","latitud":0.0,"longitud":0.0},
    {"id":718,"camion":"M3","nombre":"ESTANQUE LA BALLICA","dia":"JUEVES","litros":10000,"telefono":"","latitud":0.0,"longitud":0.0},
    {"id":719,"camion":"M3","nombre":"ESTANQUE RIO BUENO","dia":"VIERNES","litros":10000,"telefono":"","latitud":0.0,"longitud":0.0},
    {"id":720,"camion":"M3","nombre":"ESTANQUE QUEBRADA HONDA","dia":"VIERNES","litros":15000,"telefono":"","latitud":0.0,"longitud":0.0},
    {"id":721,"camion":"M3","nombre":"ESTANQUE AGUAS CLARAS","dia":"VIERNES","litros":10000,"telefono":"","latitud":0.0,"longitud":0.0},
    {"id":722,"camion":"M3","nombre":"ESTANQUE LOS CIPRECES","dia":"VIERNES","litros":10000,"telefono":"","latitud":0.0,"longitud":0.0},
    {"id":723,"camion":"M3","nombre":"ESTANQUE COLA DE ZORRO","dia":"VIERNES","litros":10000,"telefono":"","latitud":0.0,"longitud":0.0},
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
app = FastAPI(title=APP_NAME, version="2.3")

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
            # normalizar nombre columna dia
            if "dia_asignado" in df.columns and "dia" not in df.columns:
                df = df.rename(columns={"dia_asignado": "dia"})
            cols_presentes = [c for c in RUTAS_COLUMNS if c in df.columns]
            return df[cols_presentes]
        except Exception as e:
            log.warning(f"Error leyendo Excel: {e} — usando fallback")
    # Fallback: datos hardcodeados
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
# ENDPOINTS
# ============================================================================
@app.get("/health")
def health():
    return {"status": "ok", "version": "2.3", "data_mode": DATA_MODE,
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

@app.get("/entregas")
def get_entregas(desde: Optional[str]=Query(None), hasta: Optional[str]=Query(None),
                 camion: Optional[str]=Query(None), estado: Optional[int]=Query(None)):
    e = generar_entregas_mock(desde, hasta)
    if camion: e = [x for x in e if x["camion"] == camion.upper()]
    if estado is not None: e = [x for x in e if x["estado"] == estado]
    return e

@app.get("/entregas-todas")
def get_entregas_todas(desde: Optional[str]=Query(None), hasta: Optional[str]=Query(None),
                       camion: Optional[str]=Query(None)):
    if not desde: desde = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    if not hasta: hasta = datetime.now().strftime("%Y-%m-%d")
    e = generar_entregas_mock(desde, hasta)
    if camion: e = [x for x in e if x["camion"] == camion.upper()]
    return e

@app.post("/registrar-entregas")
async def registrar_entregas(
    nombre: str=Form(...), camion: str=Form(...), litros: int=Form(...),
    estado: int=Form(...), fecha: str=Form(...), motivo: Optional[str]=Form(None),
    latitud: Optional[float]=Form(None), longitud: Optional[float]=Form(None),
    foto: Optional[UploadFile]=File(None)):
    foto_path = None
    if foto and foto.filename:
        fname = f"{uuid.uuid4().hex}.jpg"
        dest = FOTOS_DIR / fname
        with dest.open("wb") as f: shutil.copyfileobj(foto.file, f)
        foto_path = f"/fotos/{fname}"
    nueva = {"id": int(datetime.now().timestamp()), "nombre": nombre, "camion": camion,
             "litros": litros if estado == 1 else 0, "estado": estado, "fecha": fecha,
             "motivo": motivo, "latitud": latitud, "longitud": longitud,
             "foto_url": foto_path, "fuente": "web", "registrado_en": datetime.utcnow().isoformat()}
    log.info(f"[ENTREGA] camion={camion} nombre={nombre} estado={estado}")
    audit_log("sistema", "registrar_entrega", {"camion": camion, "nombre": nombre, "estado": estado})
    return {"status": "ok", "entrega": nueva}

@app.post("/entregas")
def registrar_entrega_json(entrega: NuevaEntrega):
    nueva = entrega.dict()
    nueva["id"] = int(datetime.now().timestamp())
    nueva["fuente"] = "manual"; nueva["foto_url"] = None
    return {"status": "ok", "entrega": nueva}

@app.get("/estadisticas-camion")
def estadisticas_camion(camion: Optional[str]=Query(None),
                        desde: Optional[str]=Query(None), hasta: Optional[str]=Query(None)):
    if not desde: desde = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not hasta: hasta = datetime.now().strftime("%Y-%m-%d")
    e = generar_entregas_mock(desde, hasta)
    if camion: e = [x for x in e if x["camion"] == camion.upper()]
    stats = {}
    for x in e:
        c = x["camion"]
        if c not in stats: stats[c] = {"camion": c, "total": 0, "entregadas": 0, "no_entregadas": 0, "litros_total": 0}
        stats[c]["total"] += 1; stats[c]["litros_total"] += x["litros"]
        if x["estado"] == 1: stats[c]["entregadas"] += 1
        else: stats[c]["no_entregadas"] += 1
    for c in stats:
        t = stats[c]["total"]
        stats[c]["porcentaje_entrega"] = round(stats[c]["entregadas"] / t * 100, 1) if t > 0 else 0
    return list(stats.values())

@app.get("/no-entregadas")
def get_no_entregadas(desde: Optional[str]=Query(None), hasta: Optional[str]=Query(None),
                      camion: Optional[str]=Query(None)):
    if not desde: desde = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    if not hasta: hasta = datetime.now().strftime("%Y-%m-%d")
    e = [x for x in generar_entregas_mock(desde, hasta) if x["estado"] != 1]
    if camion: e = [x for x in e if x["camion"] == camion.upper()]
    return e

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
        # Modo PostgreSQL
        campos_validos = ["camion", "nombre", "dia", "litros", "telefono", "latitud", "longitud"]
        sets = []
        vals = []
        for key, val in cambios.items():
            if key in campos_validos:
                sets.append(f"{key} = %s")
                vals.append(val)
        if not sets:
            raise HTTPException(400, "Sin campos válidos para actualizar")
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
        log.info(f"[PUT DB] rutas-activas id={id} cambios={cambios}")
        return {"status": "ok", "registro": dict(zip(RUTAS_COLUMNS, row))}
    else:
        # Modo Excel
        df = read_rutas_excel()
        if "id" not in df.columns or id not in df["id"].values:
            raise HTTPException(404, f"Registro {id} no encontrado")
        for key, val in cambios.items():
            if key in df.columns and key != "id":
                df.loc[df["id"] == id, key] = val
        write_rutas_excel(df)
        fila = df[df["id"] == id].iloc[0].to_dict()
        log.info(f"[PUT EXCEL] rutas-activas id={id} cambios={cambios}")
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
        log.info(f"[DELETE DB] rutas-activas id={id}")
    else:
        df = read_rutas_excel()
        if "id" not in df.columns or id not in df["id"].values:
            raise HTTPException(404, f"Registro {id} no encontrado")
        df = df[df["id"] != id].reset_index(drop=True)
        write_rutas_excel(df)
        log.info(f"[DELETE EXCEL] rutas-activas id={id}")
    return {"status": "ok", "deleted_id": id}

@app.get("/mapa-puntos")
def mapa_puntos():
    df = read_rutas_db() if DATA_MODE == "db" else read_rutas_excel()
    df = df[(df["latitud"].astype(float) != 0.0) & (df["longitud"].astype(float) != 0.0)]
    df = df.dropna(subset=["latitud", "longitud"])
    df["color"] = df["camion"].apply(lambda c: CAMION_COLORS.get(str(c).upper(), "#1e40af"))
    df = df.replace([float("inf"), float("-inf")], None).fillna("")
    return df.to_dict(orient="records")

@app.post("/login")
def login(creds: Credenciales):
    # 🔓 MODO SIN USUARIOS — acceso libre, cualquier credencial es válida
    usuario = creds.usuario.strip() or "admin"
    rol = "admin"  # todos entran como admin mientras no hay usuarios configurados
    token = jwt_encode({"sub": usuario, "rol": rol})
    audit_log(usuario, "login", {"rol": rol, "modo": "sin_usuarios"})
    return {"token": token, "rol": rol}

@app.get("/usuarios")
def listar_usuarios():
    # Sin autenticación requerida en modo libre
    return []

@app.get("/auditoria")
def auditoria_list():
    return []

@app.on_event("startup")
def startup():
    excel_ok = EXCEL_FILE.exists()
    log.info(f"🚀 AguaRuta Backend v2.5 🔓SIN_USUARIOS | DATA_MODE={DATA_MODE} | Excel={'✅' if excel_ok else '⚠️ FALLBACK'} | Rutas fallback={len(RUTAS_FALLBACK)}")

    if DATA_MODE == "db" and pool:
        _init_db()

def _init_db():
    """Crea tablas si no existen y carga datos iniciales desde RUTAS_FALLBACK si la tabla está vacía."""
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
        log.info("✅ Tablas creadas/verificadas en PostgreSQL")

        # ── Cargar datos iniciales si la tabla está vacía ──
        cur.execute("SELECT COUNT(*) FROM rutas_activas")
        count = cur.fetchone()[0]

        if count == 0:
            log.info(f"📦 Tabla vacía — cargando {len(RUTAS_FALLBACK)} registros iniciales...")
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
            log.info(f"✅ PostgreSQL ya tiene {count} registros en rutas_activas")

        cur.close()
        db_put(conn)

    except Exception as e:
        log.error(f"❌ Error inicializando DB: {e}")
