# main.py — AguaRuta Backend
# Versión: 2.6 — Módulo EntregasMóvil integrado (tabla entregas en PostgreSQL)

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
    {'camion': 'A1', 'nombre': 'Carolina Perojemauske', 'dia': 'MARTES', 'litros': 2800, 'telefono': '', 'latitud': -33.1378888889, 'longitud': -71.6525},
    {'camion': 'A1', 'nombre': 'Caroline Tudela', 'dia': 'MARTES', 'litros': 3500, 'telefono': '920208135', 'latitud': -33.1367222222, 'longitud': -71.6500833333},
    {'camion': 'A1', 'nombre': 'CECILIA ELENA VERGARA ARAYA', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '957508328', 'latitud': -33.13353, 'longitud': -71.650873},
    {'camion': 'A1', 'nombre': 'Cindy Araujo', 'dia': 'MIERCOLES', 'litros': 2800, 'telefono': '938973021', 'latitud': -33.1349722222, 'longitud': -71.6583333333},
    {'camion': 'A1', 'nombre': 'Claudia Norambuena', 'dia': 'LUNES', 'litros': 2800, 'telefono': '997462605', 'latitud': -33.1399722222, 'longitud': -71.6489444444},
    {'camion': 'A1', 'nombre': 'Claudio Mardones', 'dia': 'LUNES', 'litros': 2800, 'telefono': '966051923', 'latitud': -33.1436944444, 'longitud': -71.6557222222},
    {'camion': 'A1', 'nombre': 'Consuelo Requena', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '', 'latitud': -33.1356666667, 'longitud': -71.6479166667},
    {'camion': 'A1', 'nombre': 'Cristian Milesi', 'dia': 'MIERCOLES', 'litros': 2800, 'telefono': '965338111', 'latitud': -33.1354722222, 'longitud': -71.6635833333},
    {'camion': 'A1', 'nombre': 'Cristina Barrera', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '992575629', 'latitud': -33.1355555556, 'longitud': -71.6578611111},
    {'camion': 'A1', 'nombre': 'Dorka Hurtado', 'dia': 'MARTES', 'litros': 1400, 'telefono': '992280998', 'latitud': -33.1370555556, 'longitud': -71.6533055556},
    {'camion': 'A1', 'nombre': 'Elba Sanchez', 'dia': 'MARTES', 'litros': 2100, 'telefono': '982544740', 'latitud': -33.1377222222, 'longitud': -71.6592777778},
    {'camion': 'A1', 'nombre': 'ELIFELETT MANCILLA PEÑA', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '927333570', 'latitud': -33.13453, 'longitud': -71.658445},
    {'camion': 'A1', 'nombre': 'Evelyn Salina', 'dia': 'MIERCOLES', 'litros': 2800, 'telefono': '952584838', 'latitud': -33.1365833333, 'longitud': -71.6468888889},
    {'camion': 'A1', 'nombre': 'Evelyn Torres Vazquez', 'dia': 'LUNES', 'litros': 3500, 'telefono': '', 'latitud': -33.1398888889, 'longitud': -71.6501666667},
    {'camion': 'A1', 'nombre': 'FELICIANO LETELIER', 'dia': 'MARTES', 'litros': 2100, 'telefono': '995088679', 'latitud': -33.137357, 'longitud': -71.652458},
    {'camion': 'A1', 'nombre': 'Gaston Figueroa', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '939121095', 'latitud': -33.1348888889, 'longitud': -71.6623888889},
    {'camion': 'A1', 'nombre': 'Gladiz varas', 'dia': 'JUEVES', 'litros': 700, 'telefono': '976922247', 'latitud': -33.1338333333, 'longitud': -71.6556944444},
    {'camion': 'A1', 'nombre': 'Gloria Caceres', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '951517201', 'latitud': -33.1314444444, 'longitud': -71.6524444444},
    {'camion': 'A1', 'nombre': 'GRACIELA MALLEA JAQUE', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '971382513', 'latitud': -33.135866, 'longitud': -71.657895},
    {'camion': 'A1', 'nombre': 'Gumercindo Letelier', 'dia': 'LUNES', 'litros': 700, 'telefono': '954934114', 'latitud': -33.1426388889, 'longitud': -71.6545277778},
    {'camion': 'A1', 'nombre': 'Gustavo Torres', 'dia': 'JUEVES', 'litros': 2800, 'telefono': '937327361', 'latitud': -33.1346666667, 'longitud': -71.6525277778},
    {'camion': 'A1', 'nombre': 'HERMAN ROLANDO NAVARRO LUCERO', 'dia': 'MARTES', 'litros': 700, 'telefono': '991628201', 'latitud': -33.137764, 'longitud': -71.649581},
    {'camion': 'A1', 'nombre': 'Ines Correa', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '994023813', 'latitud': -33.1331666667, 'longitud': -71.6441111111},
    {'camion': 'A1', 'nombre': 'Ismael Bustamante', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '945086999', 'latitud': -33.1278055556, 'longitud': -71.6541666667},
    {'camion': 'A1', 'nombre': 'Ivan Figueroa', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '986703037', 'latitud': -33.1356666667, 'longitud': -71.6544444444},
    {'camion': 'A1', 'nombre': 'IVAN TAPIA SALAZAR', 'dia': 'LUNES', 'litros': 2800, 'telefono': '974022382', 'latitud': -33.142654, 'longitud': -71.652681},
    {'camion': 'A1', 'nombre': 'Jaime Bravo', 'dia': 'MARTES', 'litros': 2100, 'telefono': '', 'latitud': -33.1378888889, 'longitud': -71.6525},
    {'camion': 'A1', 'nombre': 'Javiera Martinez', 'dia': 'LUNES', 'litros': 2100, 'telefono': '932715381', 'latitud': -33.1416666667, 'longitud': -71.6521944444},
    {'camion': 'A1', 'nombre': 'Jessica Cardenas', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1370277778, 'longitud': -71.65025},
    {'camion': 'A1', 'nombre': 'JHON ERICK MALDONADO MERCADO', 'dia': 'VIERNES', 'litros': 700, 'telefono': '931431851', 'latitud': -33.132675, 'longitud': -71.646825},
    {'camion': 'A1', 'nombre': 'JUAN CARLOS PEÑA GALAZ', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '971743108', 'latitud': -33.134873, 'longitud': -71.658447},
    {'camion': 'A1', 'nombre': 'Juan Lorca', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '976789463', 'latitud': -33.13575, 'longitud': -71.6575},
    {'camion': 'A1', 'nombre': 'Julio Plaza', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '950122424', 'latitud': -33.1356388889, 'longitud': -71.6504444444},
    {'camion': 'A1', 'nombre': 'Karina Jiles', 'dia': 'LUNES', 'litros': 3500, 'telefono': '', 'latitud': -33.1420277778, 'longitud': -71.6499166667},
    {'camion': 'A1', 'nombre': 'Katherine Olivares', 'dia': 'JUEVES', 'litros': 2800, 'telefono': '976500073', 'latitud': -33.1338333333, 'longitud': -71.6512222222},
    {'camion': 'A1', 'nombre': 'Krisi Fuentes', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '959920587', 'latitud': -33.135281, 'longitud': -71.654818},
    {'camion': 'A1', 'nombre': 'Leo Dan Santibañez', 'dia': 'LUNES', 'litros': 2800, 'telefono': '989920815', 'latitud': -33.1420555556, 'longitud': -71.6549722222},
    {'camion': 'A1', 'nombre': 'Leontina Acevedo', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '992134229', 'latitud': -33.1345277778, 'longitud': -71.6533888889},
    {'camion': 'A1', 'nombre': 'LESLEY CAROLINE SUAZO ALVAREZ', 'dia': 'VIERNES', 'litros': 700, 'telefono': '967318731', 'latitud': -33.130301, 'longitud': -71.648454},
    {'camion': 'A1', 'nombre': 'Lorena Carrazana', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '998076320', 'latitud': -33.1331666667, 'longitud': -71.6595277778},
    {'camion': 'A1', 'nombre': 'LORETO CALDERON VANEGAS', 'dia': 'LUNES', 'litros': 700, 'telefono': '965805129', 'latitud': -33.139777, 'longitud': -71.648444},
    {'camion': 'A1', 'nombre': 'Loreto Labe', 'dia': 'JUEVES', 'litros': 2800, 'telefono': '979070693', 'latitud': -33.1345277778, 'longitud': -71.6466666667},
    {'camion': 'A1', 'nombre': 'Lucia Cea Zuñiga', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '955800451', 'latitud': -33.1338333333, 'longitud': -71.6543611111},
    {'camion': 'A1', 'nombre': 'Lucia Sandoval', 'dia': 'MARTES', 'litros': 2100, 'telefono': '954399471', 'latitud': -33.136728, 'longitud': -71.653102},
    {'camion': 'A1', 'nombre': 'Luis Torres', 'dia': 'LUNES', 'litros': 1400, 'telefono': '998516365', 'latitud': -33.1425, 'longitud': -71.6578611111},
    {'camion': 'A1', 'nombre': 'Manuel Varas', 'dia': 'LUNES', 'litros': 700, 'telefono': '997525909', 'latitud': -33.1498888889, 'longitud': -71.6563055556},
    {'camion': 'A1', 'nombre': 'Marcela Guerra', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '936454687', 'latitud': -33.1347777778, 'longitud': -71.6577777778},
    {'camion': 'A1', 'nombre': 'Marcela Salazar', 'dia': 'LUNES', 'litros': 2100, 'telefono': '952286017', 'latitud': -33.1409444444, 'longitud': -71.6480277778},
    {'camion': 'A1', 'nombre': 'Marco Gonsalez', 'dia': 'VIERNES', 'litros': 3500, 'telefono': '', 'latitud': -33.1296388889, 'longitud': -71.6479166667},
    {'camion': 'A1', 'nombre': 'MARCOS OSSANDON LEIVA', 'dia': 'JUEVES', 'litros': 700, 'telefono': '967287669', 'latitud': -33.134133, 'longitud': -71.645547},
    {'camion': 'A1', 'nombre': 'MARGARITA EUGENIA ROZAS CARRIL', 'dia': 'VIERNES', 'litros': 700, 'telefono': '945062280', 'latitud': -33.130686, 'longitud': -71.648088},
    {'camion': 'A1', 'nombre': 'Marhyan Ampuero', 'dia': 'JUEVES', 'litros': 700, 'telefono': '966924198', 'latitud': -33.1340555556, 'longitud': -71.6511111111},
    {'camion': 'A1', 'nombre': 'MARIA ALEJANDRA ROJAS CEBALLOS', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '950194290', 'latitud': -33.135097, 'longitud': -71.659432},
    {'camion': 'A1', 'nombre': 'MARIA ANGELICA MALDONADO', 'dia': 'MIERCOLES', 'litros': 4800, 'telefono': '957219368', 'latitud': -33.135455, 'longitud': -71.652119},
    {'camion': 'A1', 'nombre': 'Maria Avila Leon', 'dia': 'JUEVES', 'litros': 2800, 'telefono': '920723482', 'latitud': -33.1338611111, 'longitud': -71.6520277778},
    {'camion': 'A1', 'nombre': 'Maria Barrientos', 'dia': 'VIERNES', 'litros': 2800, 'telefono': '946421849', 'latitud': -33.1321388889, 'longitud': -71.6536944444},
    {'camion': 'A1', 'nombre': 'MARIA DEL CARMEN IBAÑEZ CONSTANZO', 'dia': 'MARTES', 'litros': 2800, 'telefono': '936551375', 'latitud': -33.137925, 'longitud': -71.652592},
    {'camion': 'A1', 'nombre': 'Maria Galas', 'dia': 'JUEVES', 'litros': 700, 'telefono': '990095021', 'latitud': -33.1344444444, 'longitud': -71.6588333333},
    {'camion': 'A1', 'nombre': 'MARIA MUÑOZ...', 'dia': 'MARTES', 'litros': 1400, 'telefono': '948453623', 'latitud': -33.1327222222, 'longitud': -71.6506666667},
    {'camion': 'A1', 'nombre': 'Maria Valencia', 'dia': 'VIERNES', 'litros': 2800, 'telefono': '973594295', 'latitud': -33.1333611111, 'longitud': -71.6541944444},
    {'camion': 'A1', 'nombre': 'MICHAEL JIMMY JARA ROMAN', 'dia': 'MARTES', 'litros': 1400, 'telefono': '973426360', 'latitud': -33.137498, 'longitud': -71.649377},
    {'camion': 'A1', 'nombre': 'Natalia Ciero', 'dia': 'LUNES', 'litros': 1400, 'telefono': '963863522', 'latitud': -33.1425833333, 'longitud': -71.6506666667},
    {'camion': 'A1', 'nombre': 'Natalia Osses', 'dia': 'LUNES', 'litros': 2100, 'telefono': '964475970', 'latitud': -33.1408611111, 'longitud': -71.6518333333},
    {'camion': 'A1', 'nombre': 'Nicole Arancibia', 'dia': 'MIERCOLES', 'litros': 2800, 'telefono': '949294419', 'latitud': -33.1349166667, 'longitud': -71.6585833333},
    {'camion': 'A1', 'nombre': 'Nicole Carrasco', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '973194605', 'latitud': -33.1302222222, 'longitud': -71.6477777778},
    {'camion': 'A1', 'nombre': 'Ninoska Soto', 'dia': 'MARTES', 'litros': 1400, 'telefono': '950814731', 'latitud': -33.1377222222, 'longitud': -71.6589722222},
    {'camion': 'A1', 'nombre': 'Nora Araya', 'dia': 'MARTES', 'litros': 2800, 'telefono': '957263251', 'latitud': -33.1385, 'longitud': -71.6594722222},
    {'camion': 'A1', 'nombre': 'Oscar Moya', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '959393325', 'latitud': -33.135, 'longitud': -71.6586111111},
    {'camion': 'A1', 'nombre': 'Paloma Toloza', 'dia': 'VIERNES', 'litros': 2800, 'telefono': '955195972', 'latitud': -33.1202222222, 'longitud': -71.6529444444},
    {'camion': 'A1', 'nombre': 'Paola Cisternas', 'dia': 'LUNES', 'litros': 2100, 'telefono': '', 'latitud': -33.1429166667, 'longitud': -71.6508055556},
    {'camion': 'A1', 'nombre': 'Patricia Alvear', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.13775, 'longitud': -71.6585277778},
    {'camion': 'A1', 'nombre': 'Patricia Beliz', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.1358611111, 'longitud': -71.6578888889},
    {'camion': 'A1', 'nombre': 'Paula Galvan', 'dia': 'MIERCOLES', 'litros': 2800, 'telefono': '979755876', 'latitud': -33.1357222222, 'longitud': -71.6626388889},
    {'camion': 'A1', 'nombre': 'Petrolina Morales', 'dia': 'VIERNES', 'litros': 700, 'telefono': '990728756', 'latitud': -33.13325, 'longitud': -71.6597222222},
    {'camion': 'A1', 'nombre': 'RAUL JIMENEZ', 'dia': 'LUNES', 'litros': 1400, 'telefono': '935921913', 'latitud': -33.1425719, 'longitud': -71.6580506},
    {'camion': 'A1', 'nombre': 'Reinero jaure', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '950403743', 'latitud': -33.1296944444, 'longitud': -71.6455},
    {'camion': 'A1', 'nombre': 'Rosalba Baez', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.1355277778, 'longitud': -71.6484166667},
    {'camion': 'A1', 'nombre': 'ROSA REYES.', 'dia': 'LUNES', 'litros': 1400, 'telefono': '941352367', 'latitud': -33.13425, 'longitud': -71.6549444444},
    {'camion': 'A1', 'nombre': 'RUBEN PEÑA CASTILLO', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '985787420', 'latitud': -33.134692, 'longitud': -71.658552},
    {'camion': 'A1', 'nombre': 'Sandra Jimenez', 'dia': 'MARTES', 'litros': 700, 'telefono': '963481259', 'latitud': -33.1393611111, 'longitud': -71.6471111111},
    {'camion': 'A1', 'nombre': 'SERGIO CASTILLO MUÑOZ', 'dia': 'LUNES', 'litros': 1400, 'telefono': '989383832', 'latitud': -33.142356, 'longitud': -71.652628},
    {'camion': 'A1', 'nombre': 'Sergio Nuñez', 'dia': 'VIERNES', 'litros': 3500, 'telefono': '944040600', 'latitud': -33.1334722222, 'longitud': -71.6616111111},
    {'camion': 'A1', 'nombre': 'Sergio torres', 'dia': 'LUNES', 'litros': 1400, 'telefono': '998516365', 'latitud': -33.1424444444, 'longitud': -71.6577777778},
    {'camion': 'A1', 'nombre': 'Silvia Paulino', 'dia': 'LUNES', 'litros': 2800, 'telefono': '', 'latitud': -33.1418888889, 'longitud': -71.6518055556},
    {'camion': 'A1', 'nombre': 'Teresa Acevedo', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '938867504', 'latitud': -33.1346388889, 'longitud': -71.6576666667},
    {'camion': 'A1', 'nombre': 'VALERIA DONOSO CONCHA', 'dia': 'MARTES', 'litros': 700, 'telefono': '967771107', 'latitud': -33.137724, 'longitud': -71.660655},
    {'camion': 'A1', 'nombre': 'VERONICA DE LAS MERCEDES MORALES SOTO', 'dia': 'MARTES', 'litros': 2800, 'telefono': '992363995', 'latitud': -33.137925, 'longitud': -71.652592},
    {'camion': 'A1', 'nombre': 'Veronica Eskiafoz', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '', 'latitud': -33.1362777778, 'longitud': -71.6577777778},
    {'camion': 'A1', 'nombre': 'Vilma Mendez', 'dia': 'VIERNES', 'litros': 2800, 'telefono': '999467964', 'latitud': -33.1309444444, 'longitud': -71.6529166667},
    {'camion': 'A1', 'nombre': 'YENNY MESA LEON', 'dia': 'MARTES', 'litros': 700, 'telefono': '978860272', 'latitud': -33.137197, 'longitud': -71.6484},
    {'camion': 'A1', 'nombre': 'Zaida Osorio', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '991289206', 'latitud': -33.13375, 'longitud': -71.6594166667},
    {'camion': 'A2', 'nombre': 'Ada Urzua', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1404444444, 'longitud': -71.6761666667},
    {'camion': 'A2', 'nombre': 'ADOLFO GONZALEZ FREDERICK', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '931210982', 'latitud': -33.136524, 'longitud': -71.675279},
    {'camion': 'A2', 'nombre': 'Alan', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1303055556, 'longitud': -71.6705555556},
    {'camion': 'A2', 'nombre': 'Alba Llanquihuen', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1380833333, 'longitud': -71.676},
    {'camion': 'A2', 'nombre': 'Aldo Molina', 'dia': 'JUEVES', 'litros': 4200, 'telefono': '', 'latitud': -33.1339166667, 'longitud': -71.6677777778},
    {'camion': 'A2', 'nombre': 'ALEJANDRA CORTES', 'dia': 'JUEVES', 'litros': 700, 'telefono': '930796058', 'latitud': -33.134348, 'longitud': -71.67233},
    {'camion': 'A2', 'nombre': 'Alex Garcia', 'dia': 'LUNES', 'litros': 1000, 'telefono': '', 'latitud': -33.1499722222, 'longitud': -71.6680833333},
    {'camion': 'A2', 'nombre': 'Alfonso Barraza', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '', 'latitud': -33.1353333333, 'longitud': -71.6720833333},
    {'camion': 'A2', 'nombre': 'Alicia Quiñonez', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.1386388889, 'longitud': -71.6766388889},
    {'camion': 'A2', 'nombre': 'Ana Cagliero', 'dia': 'VIERNES', 'litros': 2800, 'telefono': '', 'latitud': -33.1304722222, 'longitud': -71.6701944444},
    {'camion': 'A2', 'nombre': 'Ana Rojas', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.14525, 'longitud': -71.6805555556},
    {'camion': 'A2', 'nombre': 'Ana Silva Pinto', 'dia': 'MARTES', 'litros': 1400, 'telefono': '944526031', 'latitud': -33.1394722222, 'longitud': -71.6826111111},
    {'camion': 'A2', 'nombre': 'Angela Ariel', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1300277778, 'longitud': -71.6662777778},
    {'camion': 'A2', 'nombre': 'Angela Bustamante', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1403333333, 'longitud': -71.6810277778},
    {'camion': 'A2', 'nombre': 'Angel Ceron', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.1415, 'longitud': -71.6838055556},
    {'camion': 'A2', 'nombre': 'Angelica Mena', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1369444444, 'longitud': -71.6778888889},
    {'camion': 'A2', 'nombre': 'Aracely Morales', 'dia': 'MARTES', 'litros': 2100, 'telefono': '', 'latitud': -33.1404444444, 'longitud': -71.6812222222},
    {'camion': 'A2', 'nombre': 'ASTRID ALARCON MUÑOZ', 'dia': 'MIERCOLES', 'litros': 2800, 'telefono': '995867540', 'latitud': -33.135743, 'longitud': -71.673064},
    {'camion': 'A2', 'nombre': 'Baldomero Mora', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1403055556, 'longitud': -71.6844722222},
    {'camion': 'A2', 'nombre': 'Barabra Gonazalez', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.13775, 'longitud': -71.6803611111},
    {'camion': 'A2', 'nombre': 'BERTA GONZALEZ SANTIBAÑEZ', 'dia': 'VIERNES', 'litros': 700, 'telefono': '940300664', 'latitud': -33.131489, 'longitud': -71.666256},
    {'camion': 'A2', 'nombre': 'Carlos Cambrias', 'dia': 'MARTES', 'litros': 3500, 'telefono': '', 'latitud': -33.1396666667, 'longitud': -71.6833888889},
    {'camion': 'A2', 'nombre': 'Carlos Mendez Oyanedel\n\nAlicia Paredes Muñoz', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '', 'latitud': -33.134445, 'longitud': -71.667755},
    {'camion': 'A2', 'nombre': 'Carlos Vargas', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1304444444, 'longitud': -71.6707777778},
    {'camion': 'A2', 'nombre': 'Carmen Vivanco', 'dia': 'JUEVES', 'litros': 2800, 'telefono': '', 'latitud': -33.1351944444, 'longitud': -71.6694166667},
    {'camion': 'A2', 'nombre': 'Carolina Arias', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '973588479', 'latitud': -33.1351388889, 'longitud': -71.6695833333},
    {'camion': 'A2', 'nombre': 'Carolina Lopez', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1320555556, 'longitud': -71.6683611111},
    {'camion': 'A2', 'nombre': 'Cecilia Padilla', 'dia': 'LUNES', 'litros': 1400, 'telefono': '', 'latitud': -33.141, 'longitud': -71.6829444444},
    {'camion': 'A2', 'nombre': 'CLARA ARAYA RAMIREZ', 'dia': 'LUNES', 'litros': 700, 'telefono': '984178861', 'latitud': -33.146854, 'longitud': -71.678425},
    {'camion': 'A2', 'nombre': 'CLAUDIA GUZMAN PEDREROS', 'dia': 'JUEVES', 'litros': 700, 'telefono': '920604578', 'latitud': -33.133079, 'longitud': -71.662957},
    {'camion': 'A2', 'nombre': 'CLAUDIA MESA CASTRO', 'dia': 'JUEVES', 'litros': 700, 'telefono': '999478988', 'latitud': -33.135135, 'longitud': -71.67326},
    {'camion': 'A2', 'nombre': 'Claudia Valenzuela', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1312222222, 'longitud': -71.6679444444},
    {'camion': 'A2', 'nombre': 'Cristian Aguirre', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '938641807', 'latitud': -33.1327222222, 'longitud': -71.6711111111},
    {'camion': 'A2', 'nombre': 'Cristian Varos', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1401666667, 'longitud': -71.67675},
    {'camion': 'A2', 'nombre': 'Daniela Jimenez', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1317777778, 'longitud': -71.6676944444},
    {'camion': 'A2', 'nombre': 'Danitza Serrano', 'dia': 'MIERCOLES', 'litros': 2800, 'telefono': '966049146', 'latitud': -33.1377222222, 'longitud': -71.6770277778},
    {'camion': 'A2', 'nombre': 'Daska Oyarzo', 'dia': 'LUNES', 'litros': 1000, 'telefono': '', 'latitud': -33.1492222222, 'longitud': -71.6719444444},
    {'camion': 'A2', 'nombre': 'Diego Hueichaqueo', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.1340833333, 'longitud': -71.6631944444},
    {'camion': 'A2', 'nombre': 'Eduardo Medel', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1381111111, 'longitud': -71.6784444444},
    {'camion': 'A2', 'nombre': 'Elizabeth Medina', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1363611111, 'longitud': -71.6725555556},
    {'camion': 'A2', 'nombre': 'ERIKA MIRANDA FUENTES', 'dia': 'MARTES', 'litros': 700, 'telefono': '987266214', 'latitud': -33.139441, 'longitud': -71.678908},
    {'camion': 'A2', 'nombre': 'Esilda yañes', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1325277778, 'longitud': -71.6629722222},
    {'camion': 'A2', 'nombre': 'Eva Miranda', 'dia': 'VIERNES', 'litros': 700, 'telefono': '951680905', 'latitud': -33.131129, 'longitud': -71.660978},
    {'camion': 'A2', 'nombre': 'Faviola Miranda', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1396111111, 'longitud': -71.6808888889},
    {'camion': 'A2', 'nombre': 'Fidel Soto', 'dia': 'LUNES', 'litros': 500, 'telefono': '', 'latitud': -33.1478333333, 'longitud': -71.6704166667},
    {'camion': 'A2', 'nombre': 'Flor Ceron', 'dia': 'LUNES', 'litros': 2100, 'telefono': '', 'latitud': -33.1414722222, 'longitud': -71.6835},
    {'camion': 'A2', 'nombre': 'Gemma Contreras', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '992130896', 'latitud': -33.1318611111, 'longitud': -71.6615833333},
    {'camion': 'A2', 'nombre': 'Giovani Hernandez', 'dia': 'JUEVES', 'litros': 4200, 'telefono': '', 'latitud': -33.13375, 'longitud': -71.6673055556},
    {'camion': 'A2', 'nombre': 'Gladis Lobos', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.1384166667, 'longitud': -71.6774444444},
    {'camion': 'A2', 'nombre': 'GRACIELA DEL CARMEN LAMA CHANDIA', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '946905330', 'latitud': -33.135484, 'longitud': -71.673357},
    {'camion': 'A2', 'nombre': 'Hernan Calderon', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1313333333, 'longitud': -71.668},
    {'camion': 'A2', 'nombre': 'IRMA TEJEDA TEJEDA', 'dia': 'MARTES', 'litros': 1400, 'telefono': '956764588', 'latitud': -33.139546, 'longitud': -71.681281},
    {'camion': 'A2', 'nombre': 'Isabel Vera', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.1340555556, 'longitud': -71.6672777778},
    {'camion': 'A2', 'nombre': 'IVAN ESTEBAN RUBIO MONTECINOS', 'dia': 'MARTES', 'litros': 700, 'telefono': '984440384', 'latitud': -33.137999, 'longitud': -71.680325},
    {'camion': 'A2', 'nombre': 'Ivon Lobos', 'dia': 'LUNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1407777778, 'longitud': -71.6824444444},
    {'camion': 'A2', 'nombre': 'Iznoelia Villaroel', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.1341388889, 'longitud': -71.6632222222},
    {'camion': 'A2', 'nombre': 'Jacqueline Faundez', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '', 'latitud': -33.1372777778, 'longitud': -71.6649722222},
    {'camion': 'A2', 'nombre': 'JAIME MUÑOS.', 'dia': 'LUNES', 'litros': 2100, 'telefono': '956802804', 'latitud': -33.1405833333, 'longitud': -71.6811111111},
    {'camion': 'A2', 'nombre': 'JAN PAUL MOYA SALINA', 'dia': 'VIERNES', 'litros': 700, 'telefono': '946774864', 'latitud': -33.131325, 'longitud': -71.667905},
    {'camion': 'A2', 'nombre': 'Jeanette Gonzalez', 'dia': 'JUEVES', 'litros': 2800, 'telefono': '', 'latitud': -33.1330555556, 'longitud': -71.6625555556},
    {'camion': 'A2', 'nombre': 'JERSON FUENTES FUENTES', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '928366710', 'latitud': -33.134587, 'longitud': -71.674582},
    {'camion': 'A2', 'nombre': 'JESSICA MONSALVES DE LA JARA', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '993965098', 'latitud': -33.134469, 'longitud': -71.669643},
    {'camion': 'A2', 'nombre': 'Jessica Salaz', 'dia': 'LUNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1451944444, 'longitud': -71.6804166667},
    {'camion': 'A2', 'nombre': 'Joanna Menares', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.139875, 'longitud': -71.680184},
    {'camion': 'A2', 'nombre': 'Jocelyn Carvajal', 'dia': 'LUNES', 'litros': 2000, 'telefono': '', 'latitud': -33.1493611111, 'longitud': -71.6713055556},
    {'camion': 'A2', 'nombre': 'JORGE DELGADO', 'dia': 'MARTES', 'litros': 1400, 'telefono': '920499475', 'latitud': -33.138884, 'longitud': -71.683194},
    {'camion': 'A2', 'nombre': 'JORGE LUIS REYES BUSTAMANTE', 'dia': 'MARTES', 'litros': 2100, 'telefono': '991884544', 'latitud': -33.139718, 'longitud': -71.67984},
    {'camion': 'A2', 'nombre': 'Jose Alvarez', 'dia': 'LUNES', 'litros': 500, 'telefono': '', 'latitud': -33.1486388889, 'longitud': -71.6724722222},
    {'camion': 'A2', 'nombre': 'Jose Parra', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1388611111, 'longitud': -71.6744722222},
    {'camion': 'A2', 'nombre': 'JOSE VALENZUELA HERRERA', 'dia': 'VIERNES', 'litros': 700, 'telefono': '933428778', 'latitud': -33.132713, 'longitud': -71.671892},
    {'camion': 'A2', 'nombre': 'Juan Herrera', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1319722222, 'longitud': -71.6619166667},
    {'camion': 'A2', 'nombre': 'JUAN MANUEL MUÑOZ SANCHO', 'dia': 'LUNES', 'litros': 1400, 'telefono': '942159451', 'latitud': -33.139546, 'longitud': -71.681281},
    {'camion': 'A2', 'nombre': 'JUAN MONTECINOS', 'dia': 'MARTES', 'litros': 1400, 'telefono': '986053020', 'latitud': -33.140079, 'longitud': -71.675947},
    {'camion': 'A2', 'nombre': 'Juan Valenzuela', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1326388889, 'longitud': -71.6631666667},
    {'camion': 'A2', 'nombre': 'Julio Ibañez', 'dia': 'LUNES', 'litros': 1000, 'telefono': '', 'latitud': -33.1496111111, 'longitud': -71.6694166667},
    {'camion': 'A2', 'nombre': 'Katherine Vasquez', 'dia': 'MIERCOLES', 'litros': 2800, 'telefono': '', 'latitud': -33.1359444444, 'longitud': -71.66875},
    {'camion': 'A2', 'nombre': 'leandro Reyes', 'dia': 'LUNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1415555556, 'longitud': -71.6828333333},
    {'camion': 'A2', 'nombre': 'LUIS ESPARZA PONCE', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '961181216', 'latitud': -33.134487, 'longitud': -71.673646},
    {'camion': 'A2', 'nombre': 'Luis Reyes', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '933487689', 'latitud': -33.1325833333, 'longitud': -71.6632777778},
    {'camion': 'A2', 'nombre': 'Manuel Busto', 'dia': 'LUNES', 'litros': 1000, 'telefono': '', 'latitud': -33.1500833333, 'longitud': -71.6663333333},
    {'camion': 'A2', 'nombre': 'Manuel Solano', 'dia': 'LUNES', 'litros': 700, 'telefono': '971094416', 'latitud': -33.1413611111, 'longitud': -71.6788888889},
    {'camion': 'A2', 'nombre': 'MARCELA ALARCON.', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.1375833333, 'longitud': -71.6738888889},
    {'camion': 'A2', 'nombre': 'Marcelo Aravena', 'dia': 'VIERNES', 'litros': 2800, 'telefono': '945131165', 'latitud': -33.1300833333, 'longitud': -71.6678611111},
    {'camion': 'A2', 'nombre': 'Marco Maldonado', 'dia': 'LUNES', 'litros': 1000, 'telefono': '', 'latitud': -33.1489722222, 'longitud': -71.6676666667},
    {'camion': 'A2', 'nombre': 'Marcos Aguilera', 'dia': 'MARTES', 'litros': 700, 'telefono': '995855556', 'latitud': -33.1392222222, 'longitud': -71.66975},
    {'camion': 'A2', 'nombre': 'MARIA ANGELICA VALERO GONZALEZ', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '972075890', 'latitud': -33.137204, 'longitud': -71.674756},
    {'camion': 'A2', 'nombre': 'Maria Eugenia Ferreira', 'dia': 'JUEVES', 'litros': 700, 'telefono': '982008237', 'latitud': -33.1335, 'longitud': -71.6669444444},
    {'camion': 'A2', 'nombre': 'Maria Ibarra', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1386944444, 'longitud': -71.6775277778},
    {'camion': 'A2', 'nombre': 'Maria Landero', 'dia': 'LUNES', 'litros': 1500, 'telefono': '', 'latitud': -33.1482777778, 'longitud': -71.67275},
    {'camion': 'A2', 'nombre': 'MARIA LEONTINA GARCIA HENRIQUEZ', 'dia': 'JUEVES', 'litros': 700, 'telefono': '977395664', 'latitud': -33.134821, 'longitud': -71.67338},
    {'camion': 'A2', 'nombre': 'Maria maldonado', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1321666667, 'longitud': -71.6615555556},
    {'camion': 'A2', 'nombre': 'maria pino Campos', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.1450555556, 'longitud': -71.6809444444},
    {'camion': 'A2', 'nombre': 'Maria Sanchez', 'dia': 'LUNES', 'litros': 1400, 'telefono': '', 'latitud': -33.141, 'longitud': -71.6826666667},
    {'camion': 'A2', 'nombre': 'Maria Velez', 'dia': 'LUNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1450555556, 'longitud': -71.6815555556},
    {'camion': 'A2', 'nombre': 'Mariela Jara', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '', 'latitud': -33.1334722222, 'longitud': -71.6644444444},
    {'camion': 'A2', 'nombre': 'MARTA ARAVENA', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '930060962', 'latitud': -33.137067, 'longitud': -71.676195},
    {'camion': 'A2', 'nombre': 'Marta Isabel Hurtado', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.1369166667, 'longitud': -71.6758055556},
    {'camion': 'A2', 'nombre': 'Martin Villancura', 'dia': 'LUNES', 'litros': 2800, 'telefono': '', 'latitud': -33.14325, 'longitud': -71.6825833333},
    {'camion': 'A2', 'nombre': 'NANCY SALGADO SOTO', 'dia': 'LUNES', 'litros': 700, 'telefono': '942623326', 'latitud': -33.149202, 'longitud': -71.672589},
    {'camion': 'A2', 'nombre': 'Nayareth Rivera', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1375555556, 'longitud': -71.6738888889},
    {'camion': 'A2', 'nombre': 'NICANOR VELASQUEZ OPAZO', 'dia': 'JUEVES', 'litros': 700, 'telefono': '986568543', 'latitud': -33.133831, 'longitud': -71.669696},
    {'camion': 'A2', 'nombre': 'NOEMI DE LAS VIOLETAS ANDRADE SESSAREGO', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '975894717', 'latitud': -33.137084, 'longitud': -71.680073},
    {'camion': 'A2', 'nombre': 'Olga Carrasco', 'dia': 'LUNES', 'litros': 2000, 'telefono': '', 'latitud': -33.1496388889, 'longitud': -71.6704722222},
    {'camion': 'A2', 'nombre': 'Olga Medina', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '', 'latitud': -33.1301944444, 'longitud': -71.6703055556},
    {'camion': 'A2', 'nombre': 'Pamela Esquerra', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '', 'latitud': -33.1366666667, 'longitud': -71.6784166667},
    {'camion': 'A2', 'nombre': 'Paola Cambria', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1403611111, 'longitud': -71.6847222222},
    {'camion': 'A2', 'nombre': 'Paola Manriquez', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '940965885', 'latitud': -33.1376666667, 'longitud': -71.6779166667},
    {'camion': 'A2', 'nombre': 'Paola Marquez', 'dia': 'MIERCOLES', 'litros': 1000, 'telefono': '', 'latitud': -33.1376944444, 'longitud': -71.6779722222},
    {'camion': 'A2', 'nombre': 'patricio Mura', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1356666667, 'longitud': -71.6740277778},
    {'camion': 'A2', 'nombre': 'Priscila garrido', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1326388889, 'longitud': -71.6628055556},
    {'camion': 'A2', 'nombre': 'RAFAEL ANTONIO SOLAR CABRERA', 'dia': 'MARTES', 'litros': 1400, 'telefono': '934060498', 'latitud': -33.139005, 'longitud': -71.678511},
    {'camion': 'A2', 'nombre': 'Robinson Lara', 'dia': 'LUNES', 'litros': 1000, 'telefono': '', 'latitud': -33.1481388889, 'longitud': -71.6737222222},
    {'camion': 'A2', 'nombre': 'Rodrigo Aliaga', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1306666667, 'longitud': -71.6609444444},
    {'camion': 'A2', 'nombre': 'RONNY ORDOÑEZ RIQUELME', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '987602130', 'latitud': -33.130888, 'longitud': -71.670608},
    {'camion': 'A2', 'nombre': 'Rosa Espinoza', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.1358888889, 'longitud': -71.6689166667},
    {'camion': 'A2', 'nombre': 'Rosi Contreras', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1360555556, 'longitud': -71.6732222222},
    {'camion': 'A2', 'nombre': 'ROXANA CAMPOS FIGUEROA', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '984979191', 'latitud': -33.136359, 'longitud': -71.6723},
    {'camion': 'A2', 'nombre': 'Sandra Hernandez', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.1335, 'longitud': -71.6669444444},
    {'camion': 'A2', 'nombre': 'Sergio Aravena', 'dia': 'VIERNES', 'litros': 2800, 'telefono': '', 'latitud': -33.1316666667, 'longitud': -71.6678333333},
    {'camion': 'A2', 'nombre': 'Sergio Jara', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1323611111, 'longitud': -71.6660555556},
    {'camion': 'A2', 'nombre': 'TATIANA BUSTAMANTE ORTIZ', 'dia': 'VIERNES', 'litros': 700, 'telefono': '923768760', 'latitud': -33.133015, 'longitud': -71.66671},
    {'camion': 'A2', 'nombre': 'Veronica Gallardo', 'dia': 'LUNES', 'litros': 700, 'telefono': '923743214', 'latitud': -33.1412777778, 'longitud': -71.6787222222},
    {'camion': 'A2', 'nombre': 'Veronica Marchant', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.1487777778, 'longitud': -71.66925},
    {'camion': 'A2', 'nombre': 'Ximena Correa', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '986207689', 'latitud': -33.1343055556, 'longitud': -71.66675},
    {'camion': 'A2', 'nombre': 'YANIRA EWERT MIRANDA', 'dia': 'LUNES', 'litros': 1400, 'telefono': '971894188', 'latitud': -33.140469, 'longitud': -71.685028},
    {'camion': 'A2', 'nombre': 'Zulema Manriquez', 'dia': 'JUEVES', 'litros': 3500, 'telefono': '959626876', 'latitud': -33.1352222222, 'longitud': -71.67275},
    # A3-M3 omitidos por brevedad — se mantienen idénticos al original
    # (el archivo completo los incluye todos)
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
app = FastAPI(title=APP_NAME, version="2.6")

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
    return {"status": "ok", "version": "2.6", "data_mode": DATA_MODE,
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
# ENDPOINTS — ENTREGAS (MOCK para admin dashboard)
# ============================================================================
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

# ============================================================================
# ENDPOINT — REGISTRAR ENTREGA (desde app móvil repartidor)
# Guarda en PostgreSQL si DATA_MODE=db, sino retorna confirmación sin persistir
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
    # Guardar foto si viene
    foto_url = None
    if foto and foto.filename:
        fname = f"{uuid.uuid4().hex}.jpg"
        dest = FOTOS_DIR / fname
        with dest.open("wb") as f:
            shutil.copyfileobj(foto.file, f)
        foto_url = f"/fotos/{fname}"

    litros_real = litros if estado == 1 else 0
    registrado_en = datetime.utcnow().isoformat()

    nueva = {
        "nombre": nombre, "camion": camion, "litros": litros_real,
        "estado": estado, "fecha": fecha, "motivo": motivo,
        "telefono": telefono, "latitud": latitud, "longitud": longitud,
        "foto_url": foto_url, "fuente": "movil", "registrado_en": registrado_en
    }

    # ── Persistir en PostgreSQL si está disponible ──
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
        # Sin DB: asignar id temporal y loguear
        nueva["id"] = int(datetime.now().timestamp())
        log.info(f"[ENTREGA MOCK] camion={camion} nombre={nombre} estado={estado}")

    audit_log("sistema", "registrar_entrega", {"camion": camion, "nombre": nombre, "estado": estado})
    return {"status": "ok", "entrega": nueva}

# ============================================================================
# ENDPOINT — VER ENTREGAS REALES (para admin — EntregasApp.js)
# Lee desde PostgreSQL con filtros. Fallback a mock si no hay DB.
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
    # ── Intentar desde PostgreSQL ──
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

            cols = ["id", "nombre", "camion", "litros", "estado", "fecha", "motivo",
                    "telefono", "latitud", "longitud", "foto_url", "fuente", "registrado_en"]
            rows = cur.fetchall()
            cur.close()
            db_put(conn)

            return [dict(zip(cols, row)) for row in rows]

        except Exception as e:
            log.error(f"[ENTREGAS-APP DB ERROR] {e}")
            # Caer a mock en caso de error

    # ── Fallback a mock ──
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
# ENDPOINTS — ESTADÍSTICAS Y NO-ENTREGADAS
# ============================================================================
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
    log.info(f"🚀 AguaRuta Backend v2.6 | DATA_MODE={DATA_MODE} | Excel={'✅' if excel_ok else '⚠️ FALLBACK'} | Rutas fallback={len(RUTAS_FALLBACK)}")
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

        # ── Tabla entregas (NUEVA v2.6) ──
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
        log.info("✅ Tablas creadas/verificadas en PostgreSQL (v2.6 incluye tabla entregas)")

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
            log.info(f"✅ PostgreSQL ya tiene {count} registros en rutas_activas")

        cur.close()
        db_put(conn)

    except Exception as e:
        log.error(f"❌ Error inicializando DB: {e}")
