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
    {'camion': 'A3', 'nombre': 'ABEL ZENOBIO BRITO ARENAS', 'dia': 'MARTES', 'litros': 1400, 'telefono': '989709281', 'latitud': -33.126158, 'longitud': -71.668743},
    {'camion': 'A3', 'nombre': 'Alejandra Pizarro', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.124298, 'longitud': -71.672369},
    {'camion': 'A3', 'nombre': 'Ana Cifuentes', 'dia': 'LUNES', 'litros': 700, 'telefono': '941759252', 'latitud': -33.1287222222, 'longitud': -71.6651944444},
    {'camion': 'A3', 'nombre': 'Ana Leiva', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1265833333, 'longitud': -71.6881944444},
    {'camion': 'A3', 'nombre': 'Ana Rosales', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.1233611111, 'longitud': -71.6850833333},
    {'camion': 'A3', 'nombre': 'Angelica Salazar', 'dia': 'MARTES', 'litros': 2100, 'telefono': '', 'latitud': -33.127875, 'longitud': -71.663818},
    {'camion': 'A3', 'nombre': 'ANTONIA NICOLE FLORES PEREZ', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '988863061', 'latitud': -33.1209533, 'longitud': -71.6704005},
    {'camion': 'A3', 'nombre': 'Betsi Rodriguez', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '', 'latitud': -33.1215277778, 'longitud': -71.678},
    {'camion': 'A3', 'nombre': 'CARLOS MUÑOZ RIOSECO', 'dia': 'MARTES', 'litros': 1400, 'telefono': '967882559', 'latitud': -33.126669, 'longitud': -71.663535},
    {'camion': 'A3', 'nombre': 'Carlos Torres', 'dia': 'LUNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1286111111, 'longitud': -71.6684444444},
    {'camion': 'A3', 'nombre': 'Carlos Vivar', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '996001457', 'latitud': -33.1212777778, 'longitud': -71.6823888889},
    {'camion': 'A3', 'nombre': 'CLARISA DEL CARMEN SANDOVAL', 'dia': 'MARTES', 'litros': 700, 'telefono': '972997621', 'latitud': -33.128336, 'longitud': -71.689032},
    {'camion': 'A3', 'nombre': 'Claudia Berrios', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '', 'latitud': -33.121079, 'longitud': -71.669883},
    {'camion': 'A3', 'nombre': 'Claudia Garrido', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1204166667, 'longitud': -71.6688055556},
    {'camion': 'A3', 'nombre': 'CLAUDIA SEPULVEDA SEPULVEDA', 'dia': 'LUNES', 'litros': 700, 'telefono': '962734895', 'latitud': -33.129958, 'longitud': -71.662984},
    {'camion': 'A3', 'nombre': 'Claudio Bravo', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '951272863', 'latitud': -33.1234166667, 'longitud': -71.68475},
    {'camion': 'A3', 'nombre': 'CLAUDIO PATRICIO BRICEÑO MORALES', 'dia': 'LUNES', 'litros': 1400, 'telefono': '931366073', 'latitud': -33.12933, 'longitud': -71.664248},
    {'camion': 'A3', 'nombre': 'CRISTINA ROJOS PIFFAUR', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '988429829', 'latitud': -33.122139, 'longitud': -71.684073},
    {'camion': 'A3', 'nombre': 'Dixie Gonzalez', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1233888889, 'longitud': -71.6828888889},
    {'camion': 'A3', 'nombre': 'Doris Silva', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1149722222, 'longitud': -71.6686388889},
    {'camion': 'A3', 'nombre': 'Eduardo Alarcon', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '', 'latitud': -33.1228055556, 'longitud': -71.6801944444},
    {'camion': 'A3', 'nombre': 'ELBA ORTIZ SANHUEZA', 'dia': 'LUNES', 'litros': 3500, 'telefono': '978697867', 'latitud': -33.129296, 'longitud': -71.663751},
    {'camion': 'A3', 'nombre': 'ELIANA SILVIA VARGAS VARGAS', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '984627365', 'latitud': -33.1244501, 'longitud': -71.6741214},
    {'camion': 'A3', 'nombre': 'ELIAS GAZALI', 'dia': 'VIERNES', 'litros': 700, 'telefono': '971023389', 'latitud': -33.112908, 'longitud': -71.668374},
    {'camion': 'A3', 'nombre': 'EUGENIE ALEGRIA', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '950982112', 'latitud': -33.121907, 'longitud': -71.669074},
    {'camion': 'A3', 'nombre': 'Felix Castillo', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1150555556, 'longitud': -71.6683333333},
    {'camion': 'A3', 'nombre': 'Gaston Bizama', 'dia': 'JUEVES', 'litros': 2800, 'telefono': '', 'latitud': -33.1221388889, 'longitud': -71.674},
    {'camion': 'A3', 'nombre': 'Gerson Diaz', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.127785, 'longitud': -71.663956},
    {'camion': 'A3', 'nombre': 'Gloria Castillo', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1214444444, 'longitud': -71.6802222222},
    {'camion': 'A3', 'nombre': 'Homero Sepulveda', 'dia': 'VIERNES', 'litros': 2800, 'telefono': '', 'latitud': -33.1146944444, 'longitud': -71.6696944444},
    {'camion': 'A3', 'nombre': 'Hugo Morales', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '', 'latitud': -33.1231666667, 'longitud': -71.6826388889},
    {'camion': 'A3', 'nombre': 'Idelia Maldonado', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1245277778, 'longitud': -71.6856944444},
    {'camion': 'A3', 'nombre': 'Jaime Muñoz', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '968253023', 'latitud': -33.1212777778, 'longitud': -71.6823055556},
    {'camion': 'A3', 'nombre': 'Jeni Salinaz', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.1218055556, 'longitud': -71.6773611111},
    {'camion': 'A3', 'nombre': 'Jennifer Cofre', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.12845, 'longitud': -71.661688},
    {'camion': 'A3', 'nombre': 'Jennifer Estay', 'dia': 'JUEVES', 'litros': 2800, 'telefono': '', 'latitud': -33.122615, 'longitud': -71.676115},
    {'camion': 'A3', 'nombre': 'Jennifer Gonzalez', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '984238827', 'latitud': -33.124697, 'longitud': -71.671787},
    {'camion': 'A3', 'nombre': 'Jimena Leiva', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.128685, 'longitud': -71.660961},
    {'camion': 'A3', 'nombre': 'Jonathan Becerra', 'dia': 'MIERCOLES', 'litros': 3000, 'telefono': '', 'latitud': -33.1256388889, 'longitud': -71.6656388889},
    {'camion': 'A3', 'nombre': 'Joselyn Esquivel', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.1284166667, 'longitud': -71.6647222222},
    {'camion': 'A3', 'nombre': 'JUAN ALEJANDRO ACUÑA MORALES', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '941162838', 'latitud': -33.12121, 'longitud': -71.669845},
    {'camion': 'A3', 'nombre': 'Juana Treimun', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.128914, 'longitud': -71.661013},
    {'camion': 'A3', 'nombre': 'JUAN FRANCISCO NAVEA VASQUEZ', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '999470998', 'latitud': -33.123479, 'longitud': -71.680627},
    {'camion': 'A3', 'nombre': 'Julio Cartagena', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.1298333333, 'longitud': -71.6632222222},
    {'camion': 'A3', 'nombre': 'Julio Recabarren', 'dia': 'MIERCOLES', 'litros': 4200, 'telefono': '', 'latitud': -33.1233888889, 'longitud': -71.67225},
    {'camion': 'A3', 'nombre': 'Karin Rios', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.124236, 'longitud': -71.682819},
    {'camion': 'A3', 'nombre': 'Karin Semmler', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '', 'latitud': -33.1246111111, 'longitud': -71.6863611111},
    {'camion': 'A3', 'nombre': 'Lilibet jara', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1157222222, 'longitud': -71.6670555556},
    {'camion': 'A3', 'nombre': 'Lorena Alvarez', 'dia': 'MARTES', 'litros': 2100, 'telefono': '', 'latitud': -33.127049, 'longitud': -71.663476},
    {'camion': 'A3', 'nombre': 'Luis Horta', 'dia': 'MIERCOLES', 'litros': 2800, 'telefono': '940001975', 'latitud': -33.1246944444, 'longitud': -71.6834722222},
    {'camion': 'A3', 'nombre': 'LUIS QUINTEROS CARVAJAL', 'dia': 'LUNES', 'litros': 2100, 'telefono': '988521933', 'latitud': -33.129299, 'longitud': -71.665202},
    {'camion': 'A3', 'nombre': 'Mai Hirane', 'dia': 'MIERCOLES', 'litros': 3500, 'telefono': '', 'latitud': -33.1249722222, 'longitud': -71.6857222222},
    {'camion': 'A3', 'nombre': 'Marcela Alarcon', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.1231388889, 'longitud': -71.6701388889},
    {'camion': 'A3', 'nombre': 'Marcelo Carrasco', 'dia': 'LUNES', 'litros': 2800, 'telefono': '', 'latitud': -33.1293055556, 'longitud': -71.6631666667},
    {'camion': 'A3', 'nombre': 'MARCO MELLA MORALES', 'dia': 'MARTES', 'litros': 1400, 'telefono': '955248301', 'latitud': -33.128314, 'longitud': -71.668014},
    {'camion': 'A3', 'nombre': 'MARIA ALICIA DIAZ VILLEGAS', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '972644540', 'latitud': -33.120682, 'longitud': -71.677281},
    {'camion': 'A3', 'nombre': 'MARIA ANGELICA PASTEN ORTIZ', 'dia': 'MARTES', 'litros': 1400, 'telefono': '930352545', 'latitud': -33.126605, 'longitud': -71.668424},
    {'camion': 'A3', 'nombre': 'MARIA CRISTINA MUÑOZ RODRIGUEZ', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '983797143', 'latitud': -33.120136, 'longitud': -71.679516},
    {'camion': 'A3', 'nombre': 'MARIA ELIANA LLAITUL PAREDES', 'dia': 'MARTES', 'litros': 2800, 'telefono': '976019526', 'latitud': -33.127846, 'longitud': -71.668655},
    {'camion': 'A3', 'nombre': 'Maria Gloria', 'dia': 'MARTES', 'litros': 2000, 'telefono': '', 'latitud': -33.1279444444, 'longitud': -71.6699166667},
    {'camion': 'A3', 'nombre': 'Maria Milos', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.1283055556, 'longitud': -71.6663055556},
    {'camion': 'A3', 'nombre': 'Maria Ortiz', 'dia': 'MARTES', 'litros': 2100, 'telefono': '', 'latitud': -33.1261388889, 'longitud': -71.6877777778},
    {'camion': 'A3', 'nombre': 'Maria Parra', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '', 'latitud': -33.1215, 'longitud': -71.6834722222},
    {'camion': 'A3', 'nombre': 'Maria Sturiza', 'dia': 'LUNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1288055556, 'longitud': -71.6668333333},
    {'camion': 'A3', 'nombre': 'Mario Almarza', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.127822, 'longitud': -71.664935},
    {'camion': 'A3', 'nombre': 'Mario Rivas', 'dia': 'LUNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1301388889, 'longitud': -71.68975},
    {'camion': 'A3', 'nombre': 'Marisol Flores', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.1228611111, 'longitud': -71.6835},
    {'camion': 'A3', 'nombre': 'MARJORIE MIRANDA VERGARA', 'dia': 'VIERNES', 'litros': 700, 'telefono': '977661295', 'latitud': -33.120472, 'longitud': -71.680992},
    {'camion': 'A3', 'nombre': 'Marta Hernandez', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '', 'latitud': -33.1217222222, 'longitud': -71.6776388889},
    {'camion': 'A3', 'nombre': 'Mauro Malinarich', 'dia': 'MIERCOLES', 'litros': 3500, 'telefono': '', 'latitud': -33.125, 'longitud': -71.6862222222},
    {'camion': 'A3', 'nombre': 'MELISSA PRADO DIAZ', 'dia': 'MARTES', 'litros': 1400, 'telefono': '991080636', 'latitud': -33.128113, 'longitud': -71.664286},
    {'camion': 'A3', 'nombre': 'MICHAEL CARDENAS', 'dia': 'MARTES', 'litros': 700, 'telefono': '942008499', 'latitud': -33.126126, 'longitud': -71.663959},
    {'camion': 'A3', 'nombre': 'Mila Schlodlerberg', 'dia': 'MIERCOLES', 'litros': 3500, 'telefono': '', 'latitud': -33.1245555556, 'longitud': -71.6861944444},
    {'camion': 'A3', 'nombre': 'MONICA ALMIRAIS PEREZ', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '923823685', 'latitud': -33.122763, 'longitud': -71.668838},
    {'camion': 'A3', 'nombre': 'Monica Ibaceta', 'dia': 'JUEVES', 'litros': 700, 'telefono': '950913072', 'latitud': -33.1224722222, 'longitud': -71.6821388889},
    {'camion': 'A3', 'nombre': 'NANCY CARDENAS', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '977944467', 'latitud': -33.122726, 'longitud': -71.668826},
    {'camion': 'A3', 'nombre': 'NAUR RIOS MARTINEZ', 'dia': 'LUNES', 'litros': 700, 'telefono': '972997621', 'latitud': -33.130766, 'longitud': -71.690806},
    {'camion': 'A3', 'nombre': 'NELSON PIZARRO VILLEGAS', 'dia': 'MIERCOLES', 'litros': 2800, 'telefono': '996956049', 'latitud': -33.124345, 'longitud': -71.672358},
    {'camion': 'A3', 'nombre': 'Nilda Vargas', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1248888889, 'longitud': -71.6871111111},
    {'camion': 'A3', 'nombre': 'Noelia Leal', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.1288055556, 'longitud': -71.6694166667},
    {'camion': 'A3', 'nombre': 'Orieta Araya', 'dia': 'JUEVES', 'litros': 700, 'telefono': '962606729', 'latitud': -33.1218055556, 'longitud': -71.6794722222},
    {'camion': 'A3', 'nombre': 'PaBLA Medina', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1209166667, 'longitud': -71.6783611111},
    {'camion': 'A3', 'nombre': 'PABLO FIGUEROA DINAMARCA', 'dia': 'VIERNES', 'litros': 2800, 'telefono': '966525774', 'latitud': -33.120034, 'longitud': -71.680649},
    {'camion': 'A3', 'nombre': 'Paola Escudero', 'dia': 'VIERNES', 'litros': 700, 'telefono': '996557577', 'latitud': -33.1154444444, 'longitud': -71.6673888889},
    {'camion': 'A3', 'nombre': 'Paola Faundez', 'dia': 'MARTES', 'litros': 2100, 'telefono': '', 'latitud': -33.126834, 'longitud': -71.665167},
    {'camion': 'A3', 'nombre': 'PAOLA LOPEZ ENCINA', 'dia': 'VIERNES', 'litros': 700, 'telefono': '996550380', 'latitud': -33.115146, 'longitud': -71.668029},
    {'camion': 'A3', 'nombre': 'PAOLA SALAMANCA', 'dia': 'MARTES', 'litros': 700, 'telefono': '976168115', 'latitud': -33.125849, 'longitud': -71.665915},
    {'camion': 'A3', 'nombre': 'Patricia', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '', 'latitud': -33.1229722222, 'longitud': -71.6700833333},
    {'camion': 'A3', 'nombre': 'PATRICIA DEL CARMN DURAN DURAN', 'dia': 'JUEVES', 'litros': 700, 'telefono': '944484612', 'latitud': -33.121955, 'longitud': -71.670481},
    {'camion': 'A3', 'nombre': 'Patricio Barrera', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '', 'latitud': -33.1245, 'longitud': -71.6702777778},
    {'camion': 'A3', 'nombre': 'Petronila', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.1215277778, 'longitud': -71.66875},
    {'camion': 'A3', 'nombre': 'Priscila Hernandez', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1253055556, 'longitud': -71.6865},
    {'camion': 'A3', 'nombre': 'Priscilla Parra', 'dia': 'MARTES', 'litros': 2800, 'telefono': '', 'latitud': -33.12723, 'longitud': -71.66337},
    {'camion': 'A3', 'nombre': 'REMIGIO ESPINOZA', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '974394799', 'latitud': -33.121313, 'longitud': -71.677237},
    {'camion': 'A3', 'nombre': 'Ricardo Vargas', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.1285, 'longitud': -71.6657777778},
    {'camion': 'A3', 'nombre': 'Roberto Picon', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '', 'latitud': -33.1233611111, 'longitud': -71.6846666667},
    {'camion': 'A3', 'nombre': 'Robinson Pineda', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '', 'latitud': -33.1229166667, 'longitud': -71.6801944444},
    {'camion': 'A3', 'nombre': 'Ronald Tombe', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1239166667, 'longitud': -71.6699444444},
    {'camion': 'A3', 'nombre': 'Rosa Reyes', 'dia': 'MARTES', 'litros': 1400, 'telefono': '941352367', 'latitud': -33.1273888889, 'longitud': -71.6893611111},
    {'camion': 'A3', 'nombre': 'Rosario Ulloa', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1124166667, 'longitud': -71.66775},
    {'camion': 'A3', 'nombre': 'Ruben Dasa', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '', 'latitud': -33.1223888889, 'longitud': -71.6821666667},
    {'camion': 'A3', 'nombre': 'Ruth Araos', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '', 'latitud': -33.1224166667, 'longitud': -71.6803888889},
    {'camion': 'A3', 'nombre': 'Sandi Sandoval', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '987704509', 'latitud': -33.1212222222, 'longitud': -71.6823055556},
    {'camion': 'A3', 'nombre': 'Sandra Muñoz', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '', 'latitud': -33.12275, 'longitud': -71.6704166667},
    {'camion': 'A3', 'nombre': 'Sara Oporto', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '', 'latitud': -33.1247222222, 'longitud': -71.6861944444},
    {'camion': 'A3', 'nombre': 'Sebastian Araneda', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '977237315', 'latitud': -33.1216666667, 'longitud': -71.68225},
    {'camion': 'A3', 'nombre': 'Sergio Gutierres', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.1298611111, 'longitud': -71.6639166667},
    {'camion': 'A3', 'nombre': 'SERGIO RODRIGUEZ SALINAS', 'dia': 'MARTES', 'litros': 700, 'telefono': '998128075', 'latitud': -33.127537, 'longitud': -71.662408},
    {'camion': 'A3', 'nombre': 'Silvia Bahamondez', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '', 'latitud': -33.123943, 'longitud': -71.673297},
    {'camion': 'A3', 'nombre': 'Silvia Morales', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.12355, 'longitud': -71.673833},
    {'camion': 'A3', 'nombre': 'Solan Castellano', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1265, 'longitud': -71.6692222222},
    {'camion': 'A3', 'nombre': 'Solange Peña', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.12975, 'longitud': -71.6641666667},
    {'camion': 'A3', 'nombre': 'Valeska Villa', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.1232777778, 'longitud': -71.6838888889},
    {'camion': 'A3', 'nombre': 'VERONICA PINO FIGUEROA', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '981626680', 'latitud': -33.123938, 'longitud': -71.673252},
    {'camion': 'A3', 'nombre': 'VERONICA QUIMEN MARINAO', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '965528206', 'latitud': -33.123971, 'longitud': -71.673247},
    {'camion': 'A3', 'nombre': 'Veronica Valdes', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.1228333333, 'longitud': -71.6724166667},
    {'camion': 'A3', 'nombre': 'Victoria Aravena', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.126672, 'longitud': -71.667005},
    {'camion': 'A3', 'nombre': 'VICTOR MODINGER', 'dia': 'VIERNES', 'litros': 3500, 'telefono': '949313608', 'latitud': -33.121179, 'longitud': -71.675626},
    {'camion': 'A3', 'nombre': 'Winnie Rojas', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.122615, 'longitud': -71.676115},
    {'camion': 'A3', 'nombre': 'YANARA MATELUNA', 'dia': 'LUNES', 'litros': 700, 'telefono': '993837235', 'latitud': -33.129147, 'longitud': -71.664818},
    {'camion': 'A3', 'nombre': 'Yarerly Reinoso', 'dia': 'MIERCOLES', 'litros': 3500, 'telefono': '', 'latitud': -33.125323, 'longitud': -71.66547},
    {'camion': 'A3', 'nombre': 'Yazna Albornos', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.1246666667, 'longitud': -71.6853333333},
    {'camion': 'A4', 'nombre': 'ABEL RUBILAR', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '940534316', 'latitud': -33.1063655323, 'longitud': -71.6843494577},
    {'camion': 'A4', 'nombre': 'ADELA GALLEGOS', 'dia': 'MARTES', 'litros': 2100, 'telefono': '', 'latitud': -33.1139598285, 'longitud': -71.6748026238},
    {'camion': 'A4', 'nombre': 'Adriana Cabrera\n\nAntonio Sonorza', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '', 'latitud': -33.733, 'longitud': -71.41152},
    {'camion': 'A4', 'nombre': 'AIDA JORQUERA', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.114148541, 'longitud': -71.6747167931},
    {'camion': 'A4', 'nombre': 'ALEJANDRA MEDINA ARMIJO', 'dia': 'LUNES', 'litros': 1400, 'telefono': '97776545', 'latitud': -33.114143, 'longitud': -71.685074},
    {'camion': 'A4', 'nombre': 'ALEJANDRA VERA', 'dia': 'MARTES', 'litros': 1400, 'telefono': '958804056', 'latitud': -33.10977, 'longitud': -71.67717},
    {'camion': 'A4', 'nombre': 'ALEXIA MICHEA', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.1056330457, 'longitud': -71.6803660495},
    {'camion': 'A4', 'nombre': 'AMMY VALDES', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.1091841433, 'longitud': -71.6815672805},
    {'camion': 'A4', 'nombre': 'Ana Aravena (Aracena)', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': 0.0, 'longitud': 0.0},
    {'camion': 'A4', 'nombre': 'ANA ESPINOZA VALDEBENITO', 'dia': 'MARTES', 'litros': 700, 'telefono': '962211785', 'latitud': -33.112545, 'longitud': -71.676914},
    {'camion': 'A4', 'nombre': 'ANA MARIA KRAUSEN', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1060464546, 'longitud': -71.680923949},
    {'camion': 'A4', 'nombre': 'ANA PEREZ', 'dia': 'LUNES', 'litros': 2100, 'telefono': '', 'latitud': -33.113255927, 'longitud': -71.6813850167},
    {'camion': 'A4', 'nombre': 'ANDREA VERDUGO', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.1074042467, 'longitud': -71.6794652495},
    {'camion': 'A4', 'nombre': 'ANTONIO DANIEL BARBOSA RIFAD', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '996124659', 'latitud': -33.107969, 'longitud': -71.698364},
    {'camion': 'A4', 'nombre': 'AURORA BRAVO SEGURA', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '992823772', 'latitud': -33.108886, 'longitud': -71.699291},
    {'camion': 'A4', 'nombre': 'BELINDA MEDINA', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.1085620543, 'longitud': -71.6851783625},
    {'camion': 'A4', 'nombre': 'benedicta Yañez', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.10925, 'longitud': -71.7007222222},
    {'camion': 'A4', 'nombre': 'BERENICE PARRAGUEZ FUENTES', 'dia': 'MARTES', 'litros': 700, 'telefono': '966000469', 'latitud': -33.110198, 'longitud': -71.712706},
    {'camion': 'A4', 'nombre': 'BERTHA CONTRERAS MORALES', 'dia': 'MARTES', 'litros': 700, 'telefono': '974537699', 'latitud': -33.111073, 'longitud': -71.690811},
    {'camion': 'A4', 'nombre': 'CARLOS ERNESTO ZAMORANO IBARRA', 'dia': 'LUNES', 'litros': 1400, 'telefono': '961673360', 'latitud': -33.113838, 'longitud': -71.690639},
    {'camion': 'A4', 'nombre': 'CARMEN PANTOJA', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1094976654, 'longitud': -71.6823855595},
    {'camion': 'A4', 'nombre': 'CARMEN VIDAL', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '986826405', 'latitud': -33.105397, 'longitud': -71.680495},
    {'camion': 'A4', 'nombre': 'CAROLE COLAS', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '', 'latitud': -33.1062075451, 'longitud': -71.679715},
    {'camion': 'A4', 'nombre': 'CAROLINA ARANEDA', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.1096635115, 'longitud': -71.6777426504},
    {'camion': 'A4', 'nombre': 'Carolina Bravo', 'dia': 'LUNES', 'litros': 2800, 'telefono': '', 'latitud': -33.1156111111, 'longitud': -71.7066111111},
    {'camion': 'A4', 'nombre': 'Carolina Huidogro', 'dia': 'LUNES', 'litros': 1400, 'telefono': '', 'latitud': -33.11325, 'longitud': -71.7049722222},
    {'camion': 'A4', 'nombre': 'CECILIA ALVARADO', 'dia': 'MARTES', 'litros': 1400, 'telefono': '965417001', 'latitud': -33.114676, 'longitud': -71.674483},
    {'camion': 'A4', 'nombre': 'CECILIA RUZ', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.1156125721, 'longitud': -71.6802747107},
    {'camion': 'A4', 'nombre': 'CESAR CANO', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.108655173, 'longitud': -71.6803600822},
    {'camion': 'A4', 'nombre': 'CHRISTIAN PAVES', 'dia': 'MARTES', 'litros': 2800, 'telefono': '', 'latitud': -33.112192, 'longitud': -71.674687},
    {'camion': 'A4', 'nombre': 'Clara Chang', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '944925876', 'latitud': 0.0, 'longitud': 0.0},
    {'camion': 'A4', 'nombre': 'CLAUDIA MOLINA GUTIERREZ', 'dia': 'LUNES', 'litros': 700, 'telefono': '993424510', 'latitud': -33.114254, 'longitud': -71.68428},
    {'camion': 'A4', 'nombre': 'CLAUDIA PARDO', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '982026900', 'latitud': -33.108209, 'longitud': -71.672112},
    {'camion': 'A4', 'nombre': 'CLAUDIA SOLZA', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1091192385, 'longitud': -71.6856718889},
    {'camion': 'A4', 'nombre': 'CRISTIAN BARRERA', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.1128447163, 'longitud': -71.6777426822},
    {'camion': 'A4', 'nombre': 'CRISTIAN ZARAVIA', 'dia': 'LUNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1148936463, 'longitud': -71.682291717},
    {'camion': 'A4', 'nombre': 'Cynthia Cruz', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '', 'latitud': 0.0, 'longitud': 0.0},
    {'camion': 'A4', 'nombre': 'DAISY MEDINA', 'dia': 'MIERCOLES', 'litros': 2800, 'telefono': '', 'latitud': -33.1067369899, 'longitud': -71.6798113557},
    {'camion': 'A4', 'nombre': 'DAMARIS RODRIGUEZ', 'dia': 'LUNES', 'litros': 2800, 'telefono': '923914388', 'latitud': -33.1150825207, 'longitud': -71.6808671865},
    {'camion': 'A4', 'nombre': 'DANIE FUENZALIDA', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '994337666', 'latitud': -33.1071514546, 'longitud': -71.6798072712},
    {'camion': 'A4', 'nombre': 'Daniela Carriel', 'dia': 'JUEVES', 'litros': 4200, 'telefono': '', 'latitud': 0.0, 'longitud': 0.0},
    {'camion': 'A4', 'nombre': 'DELIA YAÑEZ', 'dia': 'MARTES', 'litros': 701, 'telefono': '958092634', 'latitud': -33.115752, 'longitud': -71.675725},
    {'camion': 'A4', 'nombre': 'Diego Novoa', 'dia': 'LUNES', 'litros': 2800, 'telefono': '', 'latitud': -33.1139166667, 'longitud': -71.7243055556},
    {'camion': 'A4', 'nombre': 'Domingo Herrera', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.106657, 'longitud': -71.710612},
    {'camion': 'A4', 'nombre': 'ELENA HERRERA', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.1139598285, 'longitud': -71.6749957429},
    {'camion': 'A4', 'nombre': 'EMILIA PEREZ', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.1129166858, 'longitud': -71.680060134},
    {'camion': 'A4', 'nombre': 'ENRIQUE SILVA SANHUEZA', 'dia': 'MARTES', 'litros': 2100, 'telefono': '995580164', 'latitud': -33.111429, 'longitud': -71.676522},
    {'camion': 'A4', 'nombre': 'ESPERANZA CARREÑO', 'dia': 'MIERCOLES', 'litros': 2800, 'telefono': '', 'latitud': -33.107694, 'longitud': -71.672583},
    {'camion': 'A4', 'nombre': 'FABIO LAZCANO', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.110421, 'longitud': -71.675256},
    {'camion': 'A4', 'nombre': 'Fadua Fares Nicolas', 'dia': 'MARTES', 'litros': 1400, 'telefono': '942538525', 'latitud': -33.113847, 'longitud': -71.67504},
    {'camion': 'A4', 'nombre': 'Francesca Aguilera', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': 0.0, 'longitud': 0.0},
    {'camion': 'A4', 'nombre': 'Francisca Ibacache', 'dia': 'LUNES', 'litros': 2800, 'telefono': '963486633', 'latitud': -33.1130555556, 'longitud': -71.7246666667},
    {'camion': 'A4', 'nombre': 'FRANCISCO URBINA', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.10872045, 'longitud': -71.68030427},
    {'camion': 'A4', 'nombre': 'GASTON CAMPOS', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1107541782, 'longitud': -71.6909231729},
    {'camion': 'A4', 'nombre': 'GISELA RIFFO KLUMPP', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '952275855', 'latitud': -33.107823, 'longitud': -71.671241},
    {'camion': 'A4', 'nombre': 'Gloria Elberg', 'dia': 'JUEVES', 'litros': 700, 'telefono': '994607358', 'latitud': 0.0, 'longitud': 0.0},
    {'camion': 'A4', 'nombre': 'GLORIA MOLINA', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.114933787, 'longitud': -71.6847337148},
    {'camion': 'A4', 'nombre': 'GRACE TORREALBA FERNANDEZ', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '971277099', 'latitud': -33.108817, 'longitud': -71.699353},
    {'camion': 'A4', 'nombre': 'HECTOR ABARZUA', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.1126489694, 'longitud': -71.6874232227},
    {'camion': 'A4', 'nombre': 'Hector Campaña', 'dia': 'JUEVES', 'litros': 3500, 'telefono': '', 'latitud': -33.09275, 'longitud': -71.729},
    {'camion': 'A4', 'nombre': 'HUGO ARAVENA', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1049743218, 'longitud': -71.6826436921},
    {'camion': 'A4', 'nombre': 'INES LLANOS FERNANDEZ', 'dia': 'LUNES', 'litros': 700, 'telefono': '964344292', 'latitud': -33.114205, 'longitud': -71.681613},
    {'camion': 'A4', 'nombre': 'Inger Albapiz', 'dia': 'MARTES', 'litros': 2100, 'telefono': '', 'latitud': -33.1121111111, 'longitud': -71.7096111111},
    {'camion': 'A4', 'nombre': 'ISIDORA ACEVEDO', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '', 'latitud': -33.10955173, 'longitud': -71.6947531978},
    {'camion': 'A4', 'nombre': 'Ivonn Arevalo', 'dia': 'MARTES', 'litros': 4200, 'telefono': '', 'latitud': -33.1099722222, 'longitud': -71.7126944444},
    {'camion': 'A4', 'nombre': 'Jacqueline Bermudez\n\nraquel burgos', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '', 'latitud': 0.0, 'longitud': 0.0},
    {'camion': 'A4', 'nombre': 'JEANNETTE HERRERA GUZMAN', 'dia': 'MARTES', 'litros': 2100, 'telefono': '971356345', 'latitud': -33.112232, 'longitud': -71.712715},
    {'camion': 'A4', 'nombre': 'Jeniffer Gonzalez', 'dia': 'MARTES', 'litros': 3500, 'telefono': '', 'latitud': -33.1110833333, 'longitud': -71.7163055556},
    {'camion': 'A4', 'nombre': 'JENNIFER SOLAR OVIEDO', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '962158870', 'latitud': -33.100609, 'longitud': -71.667515},
    {'camion': 'A4', 'nombre': 'JOSE ARANCIBIA', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.1042695609, 'longitud': -71.6711502167},
    {'camion': 'A4', 'nombre': 'JUAN ARAYA', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.1093140164, 'longitud': -71.6801077831},
    {'camion': 'A4', 'nombre': 'JUAN TORRES', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.10543267, 'longitud': -71.6823325558},
    {'camion': 'A4', 'nombre': 'JULIA RANCUSI', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '944719518', 'latitud': -33.1068236, 'longitud': -71.67990573},
    {'camion': 'A4', 'nombre': 'KARINA PEREZ', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1121816726, 'longitud': -71.6876377995},
    {'camion': 'A4', 'nombre': 'LAURA CARVAJAL', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.10581912, 'longitud': -71.6819999619},
    {'camion': 'A4', 'nombre': 'LAURA MARIA GARRIDO AVENDAÑO', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '968316880', 'latitud': -33.105563, 'longitud': -71.685051},
    {'camion': 'A4', 'nombre': 'LORENA LOBOS', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '', 'latitud': -33.1088709431, 'longitud': -71.672781},
    {'camion': 'A4', 'nombre': 'Lucia Cartagena', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.1048055556, 'longitud': -71.7182222222},
    {'camion': 'A4', 'nombre': 'LUCIANA DI CIONE', 'dia': 'LUNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1154328489, 'longitud': -71.6809184408},
    {'camion': 'A4', 'nombre': 'Luisa Machuca', 'dia': 'MIERCOLES', 'litros': 2800, 'telefono': '', 'latitud': -33.1084722222, 'longitud': -71.7159722222},
    {'camion': 'A4', 'nombre': 'LUIS BRAVO', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.1092648681, 'longitud': -71.6803892495},
    {'camion': 'A4', 'nombre': 'LUIS BRAVO CHORCHO', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.10913905, 'longitud': -71.68039461},
    {'camion': 'A4', 'nombre': 'Luis Concha', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.1130555556, 'longitud': -71.7115},
    {'camion': 'A4', 'nombre': 'LUIS HUGARTE', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.1095196858, 'longitud': -71.682441954},
    {'camion': 'A4', 'nombre': 'MANUEL CAMILO SOZA ARANDA', 'dia': 'LUNES', 'litros': 700, 'telefono': '988037222', 'latitud': -33.114205, 'longitud': -71.681613},
    {'camion': 'A4', 'nombre': 'Marco Olmeño', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': 0.0, 'longitud': 0.0},
    {'camion': 'A4', 'nombre': 'Maria Berndat Araya', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': 0.0, 'longitud': 0.0},
    {'camion': 'A4', 'nombre': 'MARIA BOZO', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.10917949, 'longitud': -71.68022295},
    {'camion': 'A4', 'nombre': 'MARIA BRIONES', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.11458555, 'longitud': -71.67329604},
    {'camion': 'A4', 'nombre': 'MARIA CABEZON', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1077790047, 'longitud': -71.6865132857},
    {'camion': 'A4', 'nombre': 'MARIA CECILIA ZAMORANO ORTIZ', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '995887649', 'latitud': -33.107991, 'longitud': -71.672386},
    {'camion': 'A4', 'nombre': 'Maria Conejeros', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.1078611111, 'longitud': -71.7146111111},
    {'camion': 'A4', 'nombre': 'MARIA DEL PILAR FLORES SOTO', 'dia': 'LUNES', 'litros': 700, 'telefono': '988001020', 'latitud': -33.11368, 'longitud': -71.705947},
    {'camion': 'A4', 'nombre': 'MARIA GABRIELA ESTRELLA', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.114482, 'longitud': -71.673355},
    {'camion': 'A4', 'nombre': 'Maria Morales', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': 0.0, 'longitud': 0.0},
    {'camion': 'A4', 'nombre': 'MARIANELA RIQUELME', 'dia': 'LUNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1118208, 'longitud': -71.68443381},
    {'camion': 'A4', 'nombre': 'Marianela Torreblanca', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '', 'latitud': 0.0, 'longitud': 0.0},
    {'camion': 'A4', 'nombre': 'MARIA SANDOVAL', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '952177256', 'latitud': -33.10701448, 'longitud': -71.6799727288},
    {'camion': 'A4', 'nombre': 'MARIA SILVA ZORRILLA', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1087597652, 'longitud': -71.6855002275},
    {'camion': 'A4', 'nombre': 'Marietta Gonzalez', 'dia': 'LUNES', 'litros': 3500, 'telefono': '', 'latitud': -33.1141111111, 'longitud': -71.6890277778},
    {'camion': 'A4', 'nombre': 'MARISOL SALVO', 'dia': 'LUNES', 'litros': 700, 'telefono': '991448897', 'latitud': -33.11505, 'longitud': -71.681963},
    {'camion': 'A4', 'nombre': 'MARITZA CUEVAS', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1062764807, 'longitud': -71.6796182712},
    {'camion': 'A4', 'nombre': 'MATILDE ESPINOZA GONZALEZ', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '99218324', 'latitud': -33.106552, 'longitud': -71.719681},
    {'camion': 'A4', 'nombre': 'MAURICIO ROLANDO CASTRO SOLAR', 'dia': 'MARTES', 'litros': 1400, 'telefono': '999313132', 'latitud': -33.111429, 'longitud': -71.676522},
    {'camion': 'A4', 'nombre': 'Mitzi Riquelme', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.1127777778, 'longitud': -71.6921944444},
    {'camion': 'A4', 'nombre': 'Nancy Gomez', 'dia': 'LUNES', 'litros': 2800, 'telefono': '', 'latitud': -33.1149444444, 'longitud': -71.7058888889},
    {'camion': 'A4', 'nombre': 'NELSON BAEZ SAAVEDRA', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '996139494', 'latitud': -33.107914, 'longitud': -71.672737},
    {'camion': 'A4', 'nombre': 'Nelson Barrera', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.1129722222, 'longitud': -71.7115277778},
    {'camion': 'A4', 'nombre': 'OLGA ELGUETA', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.10600949, 'longitud': -71.68419},
    {'camion': 'A4', 'nombre': 'OSCAR ALEJANDRO VALENZUELA MARTINEZ', 'dia': 'MARTES', 'litros': 700, 'telefono': '969154645', 'latitud': -33.109365, 'longitud': -71.68486},
    {'camion': 'A4', 'nombre': 'Oscar Meza\n\nOmaire Poblete', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': 0.0, 'longitud': 0.0},
    {'camion': 'A4', 'nombre': 'PABLO BENJAMIN CARQUIN PEÑA', 'dia': 'MARTES', 'litros': 2100, 'telefono': '936238567', 'latitud': -33.111002, 'longitud': -71.688537},
    {'camion': 'A4', 'nombre': 'Pablo Cheuquean', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': 0.0, 'longitud': 0.0},
    {'camion': 'A4', 'nombre': 'PAMELA GALLARDO NAVARRETE', 'dia': 'MARTES', 'litros': 700, 'telefono': '971948287', 'latitud': -33.108974, 'longitud': -71.678629},
    {'camion': 'A4', 'nombre': 'Pamela Garcia', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.1051388889, 'longitud': -71.7188611111},
    {'camion': 'A4', 'nombre': 'PAMELA ORELLANA', 'dia': 'MARTES', 'litros': 2100, 'telefono': '', 'latitud': -33.10984152, 'longitud': -71.67544175},
    {'camion': 'A4', 'nombre': 'Paola Maturana', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': 0.0, 'longitud': 0.0},
    {'camion': 'A4', 'nombre': 'PATRICIA MUÑOZ', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.109902, 'longitud': -71.673851},
    {'camion': 'A4', 'nombre': 'PATRICIO NAZAR VIACAVA', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '982748244', 'latitud': -33.108962, 'longitud': -71.681565},
    {'camion': 'A4', 'nombre': 'Patricio Salinas', 'dia': 'JUEVES', 'litros': 3500, 'telefono': '', 'latitud': 0.0, 'longitud': 0.0},
    {'camion': 'A4', 'nombre': 'PLINIO ESCOTORIN ALVAREZ', 'dia': 'MARTES', 'litros': 700, 'telefono': '986540700', 'latitud': -33.111385, 'longitud': -71.686646},
    {'camion': 'A4', 'nombre': 'Reina Argueta', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.1026388889, 'longitud': -71.7248611111},
    {'camion': 'A4', 'nombre': 'REINLADO NAVARRO BAEZA', 'dia': 'LUNES', 'litros': 2800, 'telefono': '95004618', 'latitud': -33.114254, 'longitud': -71.68428},
    {'camion': 'A4', 'nombre': 'RENATO ESPINOZA', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1112824039, 'longitud': -71.6900758821},
    {'camion': 'A4', 'nombre': 'RODRIGO FAJARDO', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.1105836337, 'longitud': -71.6851966921},
    {'camion': 'A4', 'nombre': 'ROMINA TRONCOSO', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.11145804, 'longitud': -71.6749322},
    {'camion': 'A4', 'nombre': 'Rommy Ramos', 'dia': 'MARTES', 'litros': 700, 'telefono': '920310240', 'latitud': -33.1129444444, 'longitud': -71.7110555556},
    {'camion': 'A4', 'nombre': 'ROSA BENAVIDES', 'dia': 'MIERCOLES', 'litros': 2800, 'telefono': '', 'latitud': -33.1054622893, 'longitud': -71.6808488471},
    {'camion': 'A4', 'nombre': 'ROSALINA BIGLIA', 'dia': 'MARTES', 'litros': 1400, 'telefono': '933022626', 'latitud': -33.11233047, 'longitud': -71.68800973},
    {'camion': 'A4', 'nombre': 'ROSA MEDINA', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.11091574, 'longitud': -71.6905080687},
    {'camion': 'A4', 'nombre': 'ROSA ROA', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.11091574, 'longitud': -71.6905080687},
    {'camion': 'A4', 'nombre': 'SALOME ALFARO', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '984720312', 'latitud': -33.1056422628, 'longitud': -71.6806514577},
    {'camion': 'A4', 'nombre': 'Saul Zamorano', 'dia': 'LUNES', 'litros': 2800, 'telefono': '937635412', 'latitud': -33.114769, 'longitud': -71.690613},
    {'camion': 'A4', 'nombre': 'SEBASTIAN GUERRERO', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.1090716518, 'longitud': -71.6802497747},
    {'camion': 'A4', 'nombre': 'SONIA PRADO', 'dia': 'MARTES', 'litros': 2100, 'telefono': '', 'latitud': -33.104942, 'longitud': -71.668332},
    {'camion': 'A4', 'nombre': 'SYLVIA VALDES', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1110283293, 'longitud': -71.6864301127},
    {'camion': 'A4', 'nombre': 'TEOLINDA CISTERNA', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.1049390823, 'longitud': -71.6866849471},
    {'camion': 'A4', 'nombre': 'Valery Matamala', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '', 'latitud': 0.0, 'longitud': 0.0},
    {'camion': 'A4', 'nombre': 'VERONICA SOTO', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.104642, 'longitud': -71.66811},
    {'camion': 'A4', 'nombre': 'VERONICA VASQUEZ', 'dia': 'MARTES', 'litros': 2800, 'telefono': '', 'latitud': -33.113392, 'longitud': -71.672726},
    {'camion': 'A4', 'nombre': 'VICENTE VALENCIA', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.1075098735, 'longitud': -71.6806911202},
    {'camion': 'A4', 'nombre': 'Victor Acuña', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '', 'latitud': -33.1053611111, 'longitud': -71.7203611111},
    {'camion': 'A4', 'nombre': 'VICTOR CHAVES', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1075008865, 'longitud': -71.6807018491},
    {'camion': 'A4', 'nombre': 'VIVIANA SOLIS', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '996794368', 'latitud': -33.10627647, 'longitud': -71.68795719},
    {'camion': 'A4', 'nombre': 'WALTER BELFORD VILLAVICENCIO PEREZ', 'dia': 'LUNES', 'litros': 700, 'telefono': '982259816', 'latitud': -33.113926, 'longitud': -71.684943},
    {'camion': 'A4', 'nombre': 'YENNIFER CAMPOS PEREIRA', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '978637917', 'latitud': -33.108962, 'longitud': -71.681565},
    {'camion': 'A4', 'nombre': 'Yonathan Barros', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.1101388889, 'longitud': -71.7125833333},
    {'camion': 'A5', 'nombre': 'Adriana Fernandez', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '', 'latitud': -33.1175, 'longitud': -71.68275},
    {'camion': 'A5', 'nombre': 'Adriana Fernandez', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '', 'latitud': -33.1181111111, 'longitud': -71.6831111111},
    {'camion': 'A5', 'nombre': 'Alia Fares', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '', 'latitud': -33.1189444444, 'longitud': -71.69775},
    {'camion': 'A5', 'nombre': 'ANA MARIA TORO ORELLANA', 'dia': 'JUEVES', 'litros': 700, 'telefono': '941416582', 'latitud': -33.118142, 'longitud': -71.679364},
    {'camion': 'A5', 'nombre': 'ANA ZAMORA CUMIAN', 'dia': 'LUNES', 'litros': 700, 'telefono': '979642615', 'latitud': -33.128756, 'longitud': -71.695965},
    {'camion': 'A5', 'nombre': 'Anuzka Santillana', 'dia': 'VIERNES', 'litros': 2800, 'telefono': '', 'latitud': -33.1169444444, 'longitud': -71.6727777778},
    {'camion': 'A5', 'nombre': 'Arturo vergara', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '', 'latitud': -33.1206666667, 'longitud': -71.6931666667},
    {'camion': 'A5', 'nombre': 'Benjamin Molina', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.118, 'longitud': -71.69825},
    {'camion': 'A5', 'nombre': 'BLANCA GORMAZ', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '', 'latitud': -33.1191898262, 'longitud': -71.6751927604},
    {'camion': 'A5', 'nombre': 'BORIS MARCELO OYARZO LEAL', 'dia': 'VIERNES', 'litros': 2800, 'telefono': '951570040', 'latitud': -33.116821, 'longitud': -71.684753},
    {'camion': 'A5', 'nombre': 'Camila Bustos', 'dia': 'VIERNES', 'litros': 2800, 'telefono': '', 'latitud': -33.1169444444, 'longitud': -71.6965833333},
    {'camion': 'A5', 'nombre': 'CARLA VALENZUELA GARRIDO', 'dia': 'VIERNES', 'litros': 700, 'telefono': '982748244', 'latitud': -33.117679, 'longitud': -71.676533},
    {'camion': 'A5', 'nombre': 'Carlos Aravena', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.1208611111, 'longitud': -71.6840833333},
    {'camion': 'A5', 'nombre': 'CARLOS RUIZ VILCHEZ', 'dia': 'LUNES', 'litros': 700, 'telefono': '931094853', 'latitud': -33.12953, 'longitud': -71.694108},
    {'camion': 'A5', 'nombre': 'Carlos Tapia', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '', 'latitud': -33.1187777778, 'longitud': -71.6977222222},
    {'camion': 'A5', 'nombre': 'Carolina Carreño', 'dia': 'MARTES', 'litros': 1400, 'telefono': '986391671', 'latitud': -33.1228055556, 'longitud': -71.7072222222},
    {'camion': 'A5', 'nombre': 'Carolina Sisternas', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1166111111, 'longitud': -71.6875},
    {'camion': 'A5', 'nombre': 'Carolina Valenzuela', 'dia': 'LUNES', 'litros': 2100, 'telefono': '', 'latitud': -33.1294722222, 'longitud': -71.6970833333},
    {'camion': 'A5', 'nombre': 'Catherine Diaz.', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '977540376', 'latitud': -33.1224722222, 'longitud': -71.6911944444},
    {'camion': 'A5', 'nombre': 'CLARA VENEGAS FIGUEROA', 'dia': 'MARTES', 'litros': 700, 'telefono': '993110694', 'latitud': -33.123838, 'longitud': -71.689173},
    {'camion': 'A5', 'nombre': 'Claudia Duran', 'dia': 'MARTES', 'litros': 2800, 'telefono': '', 'latitud': -33.1225277778, 'longitud': -71.6885277778},
    {'camion': 'A5', 'nombre': 'Claudio Catalan', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.1213611111, 'longitud': -71.691},
    {'camion': 'A5', 'nombre': 'DAVID GUTIERRES', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1168346491, 'longitud': -71.6820771403},
    {'camion': 'A5', 'nombre': 'Dircia Rojas', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1196111111, 'longitud': -71.6891111111},
    {'camion': 'A5', 'nombre': 'Dixie Herrera', 'dia': 'MARTES', 'litros': 1400, 'telefono': '952218720', 'latitud': -33.1213888889, 'longitud': -71.6730833333},
    {'camion': 'A5', 'nombre': 'ELIANA DEFATIMA', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.117697326, 'longitud': -71.6784936857},
    {'camion': 'A5', 'nombre': 'Emilio Cathalinat', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '', 'latitud': -33.1193333333, 'longitud': -71.6726388889},
    {'camion': 'A5', 'nombre': 'EMILIO PABLO CATHALINA MERINO', 'dia': 'LUNES', 'litros': 700, 'telefono': '971278739', 'latitud': -33.124684, 'longitud': -71.718136},
    {'camion': 'A5', 'nombre': 'Enrique Segura', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '977540376', 'latitud': -33.119879, 'longitud': -71.678374},
    {'camion': 'A5', 'nombre': 'Erica Escalona', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.1219166667, 'longitud': -71.6911111111},
    {'camion': 'A5', 'nombre': 'ESTEFANIA DIAZ BARRERA', 'dia': 'LUNES', 'litros': 700, 'telefono': '931862189', 'latitud': -33.124195, 'longitud': -71.693242},
    {'camion': 'A5', 'nombre': 'Evelyn Valdez', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1173055556, 'longitud': -71.6728888889},
    {'camion': 'A5', 'nombre': 'Fabiola Gonzalez', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.1193611111, 'longitud': -71.6868333333},
    {'camion': 'A5', 'nombre': 'Francisca Flores', 'dia': 'LUNES', 'litros': 2100, 'telefono': '', 'latitud': -33.1256944444, 'longitud': -71.6921666667},
    {'camion': 'A5', 'nombre': 'FRANCISCA NAVARRO DIAZ', 'dia': 'LUNES', 'litros': 1400, 'telefono': '959514435', 'latitud': -33.124738, 'longitud': -71.701935},
    {'camion': 'A5', 'nombre': 'Gonzalo Molina', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1178888889, 'longitud': -71.6842777778},
    {'camion': 'A5', 'nombre': 'Guillerbert Barriga', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1221666667, 'longitud': -71.7075555556},
    {'camion': 'A5', 'nombre': 'GUILLERMO BASCUÑAN', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '966189188', 'latitud': -33.11682, 'longitud': -71.674112},
    {'camion': 'A5', 'nombre': 'Hector Pardo', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.1255833333, 'longitud': -71.69275},
    {'camion': 'A5', 'nombre': 'HECTOR RUIZ CARRASCO', 'dia': 'JUEVES', 'litros': 2800, 'telefono': '956523109', 'latitud': -33.118527, 'longitud': -71.674535},
    {'camion': 'A5', 'nombre': 'HILDA TORRES', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.1181331276, 'longitud': -71.6753251329},
    {'camion': 'A5', 'nombre': 'Ingrid Mall', 'dia': 'LUNES', 'litros': 2800, 'telefono': '', 'latitud': -33.1339444444, 'longitud': -71.6991944444},
    {'camion': 'A5', 'nombre': 'IVONNE SEPULVEDA', 'dia': 'LUNES', 'litros': 700, 'telefono': '990395172', 'latitud': -33.1289273842, 'longitud': -71.695363164},
    {'camion': 'A5', 'nombre': 'JAIME CANIO', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1199575805, 'longitud': -71.6768078968},
    {'camion': 'A5', 'nombre': 'Javiera Espinoza', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '', 'latitud': -33.1165833333, 'longitud': -71.6883888889},
    {'camion': 'A5', 'nombre': 'Javiera Garrido', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1211944444, 'longitud': -71.6902222222},
    {'camion': 'A5', 'nombre': 'JOAN INTA ANCAN OLIVARES BRIONES', 'dia': 'MARTES', 'litros': 1400, 'telefono': '940084464', 'latitud': -33.12295, 'longitud': -71.68956},
    {'camion': 'A5', 'nombre': 'Jonathan Hidalgo', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1236666667, 'longitud': -71.6898888889},
    {'camion': 'A5', 'nombre': 'JOSE VILLAGRA', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '', 'latitud': -33.1188124225, 'longitud': -71.6755146255},
    {'camion': 'A5', 'nombre': 'Jp Lazo', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1166666667, 'longitud': -71.6968333333},
    {'camion': 'A5', 'nombre': 'Juan A. Olivares O.', 'dia': 'JUEVES', 'litros': 2800, 'telefono': '', 'latitud': -33.11875, 'longitud': -71.6976388889},
    {'camion': 'A5', 'nombre': 'JUAN DONOSOS', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.117575337, 'longitud': -71.6826906308},
    {'camion': 'A5', 'nombre': 'Juan Olivares', 'dia': 'JUEVES', 'litros': 2800, 'telefono': '', 'latitud': -33.1185277778, 'longitud': -71.6975555556},
    {'camion': 'A5', 'nombre': 'JUAN VERGARA CARDENAS', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.115606, 'longitud': -71.685729},
    {'camion': 'A5', 'nombre': 'JULIA ROMO', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.118129659, 'longitud': -71.6795237847},
    {'camion': 'A5', 'nombre': 'Julio Bahamondez', 'dia': 'MARTES', 'litros': 1400, 'telefono': '988854319', 'latitud': -33.1229166667, 'longitud': -71.6900277778},
    {'camion': 'A5', 'nombre': 'Julio Paz Lobos', 'dia': 'MIERCOLES', 'litros': 4200, 'telefono': '', 'latitud': -33.11975, 'longitud': -71.71125},
    {'camion': 'A5', 'nombre': 'Karen Gutierrez', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.1217777778, 'longitud': -71.6720277778},
    {'camion': 'A5', 'nombre': 'KATHERINE SALGADO', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '997111033', 'latitud': -33.1157534653, 'longitud': -71.6849537288},
    {'camion': 'A5', 'nombre': 'Lisete Erazo', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '', 'latitud': -33.1203055556, 'longitud': -71.69},
    {'camion': 'A5', 'nombre': 'Lucila Escobar', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1206666667, 'longitud': -71.6890555556},
    {'camion': 'A5', 'nombre': 'Luis Gutierres isoldo', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.1238611111, 'longitud': -71.6898888889},
    {'camion': 'A5', 'nombre': 'macarena Salazar', 'dia': 'JUEVES', 'litros': 2800, 'telefono': '', 'latitud': -33.11825, 'longitud': -71.6846944444},
    {'camion': 'A5', 'nombre': 'Manuel Ilufin', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1221388889, 'longitud': -71.6909722222},
    {'camion': 'A5', 'nombre': 'MARGARITA GONZALEZ', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '995975599', 'latitud': -33.118868, 'longitud': -71.707403},
    {'camion': 'A5', 'nombre': 'Maria Allemand', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.121039, 'longitud': -71.685979},
    {'camion': 'A5', 'nombre': 'Mariana Constancio', 'dia': 'MARTES', 'litros': 700, 'telefono': '992120865', 'latitud': -33.1231944444, 'longitud': -71.7037777778},
    {'camion': 'A5', 'nombre': 'Mariana Gonzalez', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1211111111, 'longitud': -71.6902222222},
    {'camion': 'A5', 'nombre': 'Maria Nuñez', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '995060794', 'latitud': -33.121793, 'longitud': -71.67127},
    {'camion': 'A5', 'nombre': 'Maribel Castillos', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '', 'latitud': -33.1185277778, 'longitud': -71.6746388889},
    {'camion': 'A5', 'nombre': 'Matilde Heldres', 'dia': 'MARTES', 'litros': 2100, 'telefono': '', 'latitud': -33.1213888889, 'longitud': -71.6921666667},
    {'camion': 'A5', 'nombre': 'Mauro Cornejo', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.122188, 'longitud': -71.690225},
    {'camion': 'A5', 'nombre': 'MIRTHA VEGA ASTUDILLO', 'dia': 'JUEVES', 'litros': 700, 'telefono': '985591058', 'latitud': -33.118527, 'longitud': -71.674535},
    {'camion': 'A5', 'nombre': 'Nancy Tapia', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '', 'latitud': -33.1181111111, 'longitud': -71.6831111111},
    {'camion': 'A5', 'nombre': 'Nelson Soto', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.123, 'longitud': -71.7075833333},
    {'camion': 'A5', 'nombre': 'pamela Alegria', 'dia': 'MARTES', 'litros': 2800, 'telefono': '936269288', 'latitud': -33.1218333333, 'longitud': -71.7139166667},
    {'camion': 'A5', 'nombre': 'PAOLA OSORIO', 'dia': 'VIERNES', 'litros': 2800, 'telefono': '', 'latitud': -33.1171698686, 'longitud': -71.6744390027},
    {'camion': 'A5', 'nombre': 'Paola Salazar', 'dia': 'LUNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1295833333, 'longitud': -71.6950277778},
    {'camion': 'A5', 'nombre': 'PAOLA SILVA VERGARA', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '949447930', 'latitud': -33.118345, 'longitud': -71.704715},
    {'camion': 'A5', 'nombre': 'Patricia Gonzalez', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.1217222222, 'longitud': -71.7077222222},
    {'camion': 'A5', 'nombre': 'PATRICIA LAZCANO', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '', 'latitud': -33.11658304, 'longitud': -71.68100426},
    {'camion': 'A5', 'nombre': 'patricia Orrego', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '', 'latitud': -33.1151666667, 'longitud': -71.6951666667},
    {'camion': 'A5', 'nombre': 'PATRICIA VALENZUELA', 'dia': 'LUNES', 'litros': 3500, 'telefono': '979577483', 'latitud': -33.129068, 'longitud': -71.695462},
    {'camion': 'A5', 'nombre': 'Paula Mancilla', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.1224722222, 'longitud': -71.7121111111},
    {'camion': 'A5', 'nombre': 'Paula Martinez', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '', 'latitud': -33.1182222222, 'longitud': -71.6886666667},
    {'camion': 'A5', 'nombre': 'PAULA SAAVEDRA', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1154909308, 'longitud': -71.6854847333},
    {'camion': 'A5', 'nombre': 'PEDRO URRUTIA', 'dia': 'JUEVES', 'litros': 2800, 'telefono': '', 'latitud': -33.1188663374, 'longitud': -71.6753644218},
    {'camion': 'A5', 'nombre': 'Raquel Araya', 'dia': 'LUNES', 'litros': 2100, 'telefono': '', 'latitud': -33.1276111111, 'longitud': -71.6954722222},
    {'camion': 'A5', 'nombre': 'ricardo Cordero', 'dia': 'JUEVES', 'litros': 2800, 'telefono': '', 'latitud': -33.118, 'longitud': -71.7098611111},
    {'camion': 'A5', 'nombre': 'Rodrigo Aguilar', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '972606430', 'latitud': -33.1184444444, 'longitud': -71.6871666667},
    {'camion': 'A5', 'nombre': 'RODRIGO MONJE', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.1183171585, 'longitud': -71.6757228183},
    {'camion': 'A5', 'nombre': 'RONALD FIERRO ARROYO', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '975427249', 'latitud': -33.119426, 'longitud': -71.676504},
    {'camion': 'A5', 'nombre': 'Rosa Espinoza G', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1169166667, 'longitud': -71.6974166667},
    {'camion': 'A5', 'nombre': 'Roxana Rodriguez', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '', 'latitud': -33.1179166667, 'longitud': -71.6980833333},
    {'camion': 'A5', 'nombre': 'SAMUEL MATAMALA', 'dia': 'MARTES', 'litros': 2100, 'telefono': '926360449', 'latitud': -33.119224, 'longitud': -71.702191},
    {'camion': 'A5', 'nombre': 'SONIA CARVACHO', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.11487987, 'longitud': -71.685828056},
    {'camion': 'A5', 'nombre': 'Sylvia Lacunza', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1168055556, 'longitud': -71.6969444444},
    {'camion': 'A5', 'nombre': 'TATIANA PUENTES WENGRYN', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '999455036', 'latitud': -33.119833, 'longitud': -71.689805},
    {'camion': 'A5', 'nombre': 'TATIANA PUENTES WENGRYN', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '999455036', 'latitud': -33.119833, 'longitud': -71.689805},
    {'camion': 'A5', 'nombre': 'teresa Osega', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '', 'latitud': -33.1184166667, 'longitud': -71.6848611111},
    {'camion': 'A5', 'nombre': 'Valeria Olguin', 'dia': 'MIERCOLES', 'litros': 2800, 'telefono': '932522048', 'latitud': -33.1203888889, 'longitud': -71.7075555556},
    {'camion': 'A5', 'nombre': 'Veronica Moraga', 'dia': 'VIERNES', 'litros': 3500, 'telefono': '', 'latitud': -33.1174444444, 'longitud': -71.6728611111},
    {'camion': 'A5', 'nombre': 'VERONICA PIZARRO SANTANDER', 'dia': 'JUEVES', 'litros': 3500, 'telefono': '936350003', 'latitud': -33.118608, 'longitud': -71.681842},
    {'camion': 'A5', 'nombre': 'VICTOR GREGORIO JOFRE CASTILLO', 'dia': 'VIERNES', 'litros': 700, 'telefono': '966910628', 'latitud': -33.116796, 'longitud': -71.683522},
    {'camion': 'A5', 'nombre': 'Vilma Salinas', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.1230277778, 'longitud': -71.7079444444},
    {'camion': 'A5', 'nombre': 'Waldo Flores', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1156111111, 'longitud': -71.7066111111},
    {'camion': 'A5', 'nombre': 'Ximena Latapiat', 'dia': 'LUNES', 'litros': 2800, 'telefono': '', 'latitud': -33.1246666667, 'longitud': -71.7025555556},
    {'camion': 'A5', 'nombre': 'Ximena Rojas', 'dia': 'MARTES', 'litros': 1400, 'telefono': '956710676', 'latitud': -33.1224722222, 'longitud': -71.6911944444},
    {'camion': 'A5', 'nombre': 'Ximena Vergara', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1194166667, 'longitud': -71.6893611111},
    {'camion': 'A5', 'nombre': 'Yasmin Barrientos', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1191111111, 'longitud': -71.7064722222},
    {'camion': 'A5', 'nombre': 'Zuleima manrriquez', 'dia': 'VIERNES', 'litros': 2800, 'telefono': '', 'latitud': -33.1163611111, 'longitud': -71.6885833333},
    {'camion': 'M1', 'nombre': 'Adolfo Zarate', 'dia': 'VIERNES', 'litros': 700, 'telefono': '995589995', 'latitud': -33.114589, 'longitud': -71.664668},
    {'camion': 'M1', 'nombre': 'AGUSTINA MARQUEZ MUÑOZ', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '940625972', 'latitud': -33.121223, 'longitud': -71.665641},
    {'camion': 'M1', 'nombre': 'Alain Compte', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.119908, 'longitud': -71.658075},
    {'camion': 'M1', 'nombre': 'Alejandro Cataldo', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.119724, 'longitud': -71.662527},
    {'camion': 'M1', 'nombre': 'Alfredo Guzman', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.112134, 'longitud': -71.664919},
    {'camion': 'M1', 'nombre': 'Amanda Cabello', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '', 'latitud': -33.121689, 'longitud': -71.666669},
    {'camion': 'M1', 'nombre': 'America Saavedra', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1144722222, 'longitud': -71.6641666667},
    {'camion': 'M1', 'nombre': 'Ana Cerda G', 'dia': 'VIERNES', 'litros': 2800, 'telefono': '954250730', 'latitud': -33.114426, 'longitud': -71.664539},
    {'camion': 'M1', 'nombre': 'ANA ESPINA ESPINA', 'dia': 'LUNES', 'litros': 2800, 'telefono': '953286708', 'latitud': -33.124481, 'longitud': -71.661102},
    {'camion': 'M1', 'nombre': 'Ana Muñoz', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.122494, 'longitud': -71.665652},
    {'camion': 'M1', 'nombre': 'ANGELICA MARIA SEPULVEDA ARANGUIZ', 'dia': 'MARTES', 'litros': 1400, 'telefono': '955213096', 'latitud': -33.123833, 'longitud': -71.666717},
    {'camion': 'M1', 'nombre': 'Angel Retamal', 'dia': 'MARTES', 'litros': 2100, 'telefono': '', 'latitud': -33.122806, 'longitud': -71.663895},
    {'camion': 'M1', 'nombre': 'ANITA KATERIN MACHUCA ROJAS', 'dia': 'MARTES', 'litros': 1400, 'telefono': '920807175', 'latitud': -33.123744, 'longitud': -71.667292},
    {'camion': 'M1', 'nombre': 'Astris Ribba Araya\n(+56 9---)', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.114339, 'longitud': -71.66068},
    {'camion': 'M1', 'nombre': 'BENJAMIN GALLEGUILLOS CORDOVA', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '940886082', 'latitud': -33.11282, 'longitud': -71.662456},
    {'camion': 'M1', 'nombre': 'Bernarda Diaz', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1223611111, 'longitud': -71.6676388889},
    {'camion': 'M1', 'nombre': 'BERTA VILLANUEVA RIVERA', 'dia': 'LUNES', 'litros': 1400, 'telefono': '984082487', 'latitud': -33.125398, 'longitud': -71.663547},
    {'camion': 'M1', 'nombre': 'Betsabe Castro', 'dia': 'MARTES', 'litros': 1000, 'telefono': '', 'latitud': -33.12775, 'longitud': -71.6599722222},
    {'camion': 'M1', 'nombre': 'CAMILA ZAGARRA', 'dia': 'LUNES', 'litros': 700, 'telefono': '927728079', 'latitud': -33.123955, 'longitud': -71.663392},
    {'camion': 'M1', 'nombre': 'Camilo Pizarro', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '935834666', 'latitud': -33.120912, 'longitud': -71.665358},
    {'camion': 'M1', 'nombre': 'CARMEN LEON MAUREIRA', 'dia': 'LUNES', 'litros': 4200, 'telefono': '962156821', 'latitud': -33.112921, 'longitud': -71.663423},
    {'camion': 'M1', 'nombre': 'Carolina Concha', 'dia': 'MIERCOLES', 'litros': 3500, 'telefono': '987685290', 'latitud': -33.12189, 'longitud': -71.666323},
    {'camion': 'M1', 'nombre': 'Carol Lea Castro', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.1160555556, 'longitud': -71.66525},
    {'camion': 'M1', 'nombre': 'Cecilia Ossa Oliva', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.1157777778, 'longitud': -71.66425},
    {'camion': 'M1', 'nombre': 'Cecilia Rojas', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.122991, 'longitud': -71.667443},
    {'camion': 'M1', 'nombre': 'CELSA JENNY CARDENAS ORTEGA', 'dia': 'MIERCOLES', 'litros': 4200, 'telefono': '974839924', 'latitud': -33.12153, 'longitud': -71.66557},
    {'camion': 'M1', 'nombre': 'Claudia Araneda', 'dia': 'JUEVES', 'litros': 2800, 'telefono': '', 'latitud': -33.1154166667, 'longitud': -71.6546944444},
    {'camion': 'M1', 'nombre': 'Claudio Delgado\n(+56 9---)', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.115016, 'longitud': -71.664655},
    {'camion': 'M1', 'nombre': 'CLEMENTINA LUCIA SARA GONZALEZ ARAYA', 'dia': 'LUNES', 'litros': 2100, 'telefono': '962478319', 'latitud': -33.124415, 'longitud': -71.666041},
    {'camion': 'M1', 'nombre': 'Consuelo Vergara\n(+56 9---)', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '', 'latitud': -33.11632, 'longitud': -71.662954},
    {'camion': 'M1', 'nombre': 'CRISTIAN VENEGAS', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '935036313', 'latitud': -33.12236, 'longitud': -71.665741},
    {'camion': 'M1', 'nombre': 'Daniela Aguilera G\n(+56 9---)', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.114381, 'longitud': -71.661953},
    {'camion': 'M1', 'nombre': 'DANIELA MARILUZ MILLAS HERNANDEZ', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '981704809', 'latitud': -33.121988, 'longitud': -71.661187},
    {'camion': 'M1', 'nombre': 'Daniel Salinas', 'dia': 'MARTES', 'litros': 2100, 'telefono': '', 'latitud': -33.1238055556, 'longitud': -71.6642777778},
    {'camion': 'M1', 'nombre': 'DANILO ANDRES GONZALEZ MAULEN', 'dia': 'JUEVES', 'litros': 700, 'telefono': '956402489', 'latitud': -33.118146, 'longitud': -71.664766},
    {'camion': 'M1', 'nombre': 'Daysi Villalobos', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '', 'latitud': -33.1178333333, 'longitud': -71.6647222222},
    {'camion': 'M1', 'nombre': 'Dominik Arevalo C.', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.114594, 'longitud': -71.661172},
    {'camion': 'M1', 'nombre': 'Elisabeth Navarro', 'dia': 'VIERNES', 'litros': 700, 'telefono': '974876624', 'latitud': -33.114428, 'longitud': -71.661655},
    {'camion': 'M1', 'nombre': 'Elizabeth Canto', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.123927, 'longitud': -71.665465},
    {'camion': 'M1', 'nombre': 'ELIZABETH GARCÍA REYES', 'dia': 'LUNES', 'litros': 3500, 'telefono': '993304861', 'latitud': -33.126669, 'longitud': -71.663535},
    {'camion': 'M1', 'nombre': 'ELSA GAETE JEREZ', 'dia': 'JUEVES', 'litros': 2800, 'telefono': '972780298', 'latitud': -33.118334, 'longitud': -71.663611},
    {'camion': 'M1', 'nombre': 'EMA LUISA REYES SALAZAR', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '930383598', 'latitud': -33.120661, 'longitud': -71.666642},
    {'camion': 'M1', 'nombre': 'Ernesto Carvajal', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1143055556, 'longitud': -71.6613055556},
    {'camion': 'M1', 'nombre': 'Eugenia Nuñez', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '', 'latitud': -33.121202, 'longitud': -71.667117},
    {'camion': 'M1', 'nombre': 'Francisca Avila', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '', 'latitud': -33.117865, 'longitud': -71.666232},
    {'camion': 'M1', 'nombre': 'Francisca Catro', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '', 'latitud': -33.1148055556, 'longitud': -71.6622777778},
    {'camion': 'M1', 'nombre': 'Fransy Lopez', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.121379, 'longitud': -71.666728},
    {'camion': 'M1', 'nombre': 'Freddy Fuentevilla', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.122704, 'longitud': -71.666791},
    {'camion': 'M1', 'nombre': 'Genaro Ceballos', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '', 'latitud': -33.1152777778, 'longitud': -71.6622222222},
    {'camion': 'M1', 'nombre': 'Genesis Roldan', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.124566, 'longitud': -71.66478},
    {'camion': 'M1', 'nombre': 'Gerardo Torres', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1130555556, 'longitud': -71.6618611111},
    {'camion': 'M1', 'nombre': 'GERMAN RAMON CORTEZ SAZO', 'dia': 'MARTES', 'litros': 1400, 'telefono': '982240240', 'latitud': -33.123337, 'longitud': -71.66529},
    {'camion': 'M1', 'nombre': 'Ginette Cid', 'dia': 'MARTES', 'litros': 2100, 'telefono': '', 'latitud': -33.1225, 'longitud': -71.6625277778},
    {'camion': 'M1', 'nombre': 'Guillermo Burgos', 'dia': 'VIERNES', 'litros': 700, 'telefono': '964187588', 'latitud': -33.117124, 'longitud': -71.665486},
    {'camion': 'M1', 'nombre': 'Hector Muñoz', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.123588, 'longitud': -71.665682},
    {'camion': 'M1', 'nombre': 'Hilda Martinez', 'dia': 'LUNES', 'litros': 2100, 'telefono': '956361054', 'latitud': -33.126138, 'longitud': -71.662741},
    {'camion': 'M1', 'nombre': 'HUGO ARAYA DIAZ', 'dia': 'MARTES', 'litros': 700, 'telefono': '936142897', 'latitud': -33.122382, 'longitud': -71.667338},
    {'camion': 'M1', 'nombre': 'ILIA ALEJANDRO MUÑOZ KUSMIN', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '945794567', 'latitud': -33.115597, 'longitud': -71.66452},
    {'camion': 'M1', 'nombre': 'Ingrid Contreras', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.123694, 'longitud': -71.661226},
    {'camion': 'M1', 'nombre': 'Jaime Gomez', 'dia': 'LUNES', 'litros': 2100, 'telefono': '', 'latitud': -33.125459, 'longitud': -71.663081},
    {'camion': 'M1', 'nombre': 'JANINA FLAMM', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '930289749', 'latitud': -33.121243, 'longitud': -71.660588},
    {'camion': 'M1', 'nombre': 'Jennifer Garrido', 'dia': 'VIERNES', 'litros': 2800, 'telefono': '', 'latitud': -33.1145555556, 'longitud': -71.6617777778},
    {'camion': 'M1', 'nombre': 'Jennifer Ortubia', 'dia': 'VIERNES', 'litros': 700, 'telefono': '944544508', 'latitud': -33.116877, 'longitud': -71.665288},
    {'camion': 'M1', 'nombre': 'Jessica Alvarez', 'dia': 'MARTES', 'litros': 1400, 'telefono': '956190457', 'latitud': -33.123483, 'longitud': -71.66736},
    {'camion': 'M1', 'nombre': 'Joaquin Gonzalez Arevalos', 'dia': 'VIERNES', 'litros': 3500, 'telefono': '', 'latitud': -33.1146944444, 'longitud': -71.6610555556},
    {'camion': 'M1', 'nombre': 'Jorge Garrido', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1140277778, 'longitud': -71.6641666667},
    {'camion': 'M1', 'nombre': 'Juana Veas', 'dia': 'VIERNES', 'litros': 2800, 'telefono': '', 'latitud': -33.1126944444, 'longitud': -71.6632222222},
    {'camion': 'M1', 'nombre': 'Juan Fuentes', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.11416, 'longitud': -71.660894},
    {'camion': 'M1', 'nombre': 'Juan Ortubia Araujo', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '944544508', 'latitud': -33.116877, 'longitud': -71.665288},
    {'camion': 'M1', 'nombre': 'Juan Villalobos\n(+56 9---)', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.116412, 'longitud': -71.665539},
    {'camion': 'M1', 'nombre': 'Judith Nuñez O\n(+56 9---)', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.112802, 'longitud': -71.663908},
    {'camion': 'M1', 'nombre': 'KUSMIN SHONGOF VERA', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '982832570', 'latitud': -33.115597, 'longitud': -71.66452},
    {'camion': 'M1', 'nombre': 'Laura Espejo', 'dia': 'JUEVES', 'litros': 3500, 'telefono': '933487689', 'latitud': -33.1154722222, 'longitud': -71.6618611111},
    {'camion': 'M1', 'nombre': 'Liberlinda Figueroa', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '', 'latitud': -33.1149166667, 'longitud': -71.6635833333},
    {'camion': 'M1', 'nombre': 'LILIANA FERNANDEZ ABARCA', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '966093987', 'latitud': -33.119399, 'longitud': -71.662919},
    {'camion': 'M1', 'nombre': 'Lucia Intriago', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '', 'latitud': -33.1155, 'longitud': -71.6549722222},
    {'camion': 'M1', 'nombre': 'LUCILA OLIVERA GALAZ', 'dia': 'MARTES', 'litros': 2100, 'telefono': '953425289', 'latitud': -33.123396, 'longitud': -71.661629},
    {'camion': 'M1', 'nombre': 'Luis Vargas', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.1238333333, 'longitud': -71.6636388889},
    {'camion': 'M1', 'nombre': 'Luz Rojas', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.122435, 'longitud': -71.664092},
    {'camion': 'M1', 'nombre': 'Macarena Cardenas', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.124808, 'longitud': -71.665222},
    {'camion': 'M1', 'nombre': 'Manuel Alvarez', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '937025673', 'latitud': -33.118203, 'longitud': -71.664402},
    {'camion': 'M1', 'nombre': 'Marcela Quiroz', 'dia': 'LUNES', 'litros': 3500, 'telefono': '', 'latitud': -33.1146944444, 'longitud': -71.6611944444},
    {'camion': 'M1', 'nombre': 'Margarita Lopez', 'dia': 'LUNES', 'litros': 2100, 'telefono': '', 'latitud': -33.126392, 'longitud': -71.659741},
    {'camion': 'M1', 'nombre': 'Maria Correa', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1137222222, 'longitud': -71.6645},
    {'camion': 'M1', 'nombre': 'Maria Cortes', 'dia': 'LUNES', 'litros': 2100, 'telefono': '', 'latitud': -33.125273, 'longitud': -71.659067},
    {'camion': 'M1', 'nombre': 'Maria Cristina Lobos', 'dia': 'LUNES', 'litros': 2100, 'telefono': '', 'latitud': -33.1247222222, 'longitud': -71.6644166667},
    {'camion': 'M1', 'nombre': 'Maria Del Pino R', 'dia': 'VIERNES', 'litros': 700, 'telefono': '947916747', 'latitud': -33.111755, 'longitud': -71.665257},
    {'camion': 'M1', 'nombre': 'Maria Eugenia Valdes', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1224444444, 'longitud': -71.6640833333},
    {'camion': 'M1', 'nombre': 'Maria Inostroza', 'dia': 'JUEVES', 'litros': 2800, 'telefono': '978120998', 'latitud': -33.11925, 'longitud': -71.6627222222},
    {'camion': 'M1', 'nombre': 'Maria Muñoz', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '948453623', 'latitud': -33.1145833333, 'longitud': -71.6611111111},
    {'camion': 'M1', 'nombre': 'Maria Rojas N\n(+56 9---)', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.117795, 'longitud': -71.666356},
    {'camion': 'M1', 'nombre': 'Maria Soto Soto', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.1159444444, 'longitud': -71.6643611111},
    {'camion': 'M1', 'nombre': 'Maria Valdivia', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.1221111111, 'longitud': -71.6645555556},
    {'camion': 'M1', 'nombre': 'Mariela Arias', 'dia': 'JUEVES', 'litros': 2800, 'telefono': '', 'latitud': -33.1151944444, 'longitud': -71.6614722222},
    {'camion': 'M1', 'nombre': 'Mario Gaubert', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1151666667, 'longitud': -71.6639444444},
    {'camion': 'M1', 'nombre': 'MARIO PROVOSTO HERVIA', 'dia': 'JUEVES', 'litros': 700, 'telefono': '973688445', 'latitud': -33.117975, 'longitud': -71.666682},
    {'camion': 'M1', 'nombre': 'Marisol Ottense', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '', 'latitud': -33.1177777778, 'longitud': -71.6624166667},
    {'camion': 'M1', 'nombre': 'MARTA MORALES GUTIERREZ', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '972969210', 'latitud': -33.121383, 'longitud': -71.667519},
    {'camion': 'M1', 'nombre': 'Michelle Tapia', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '981329222', 'latitud': -33.1131388889, 'longitud': -71.6640555556},
    {'camion': 'M1', 'nombre': 'Miloslava Olivares', 'dia': 'LUNES', 'litros': 4200, 'telefono': '', 'latitud': -33.1248611111, 'longitud': -71.6595},
    {'camion': 'M1', 'nombre': 'Milton Ortiz', 'dia': 'LUNES', 'litros': 1400, 'telefono': '', 'latitud': -33.125353, 'longitud': -71.663781},
    {'camion': 'M1', 'nombre': 'Mirna Carvajal', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1145277778, 'longitud': -71.6611944444},
    {'camion': 'M1', 'nombre': 'Mirna Reyes', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.125287, 'longitud': -71.663078},
    {'camion': 'M1', 'nombre': 'Monica Acosta P', 'dia': 'VIERNES', 'litros': 700, 'telefono': '972933392', 'latitud': -33.116887, 'longitud': -71.66586},
    {'camion': 'M1', 'nombre': 'Natalia Perez', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '922196056', 'latitud': -33.121507, 'longitud': -71.66791},
    {'camion': 'M1', 'nombre': 'Paola Choapa', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.1158333333, 'longitud': -71.665},
    {'camion': 'M1', 'nombre': 'Patricia Perez', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.1132777778, 'longitud': -71.6636388889},
    {'camion': 'M1', 'nombre': 'Paulina Matus', 'dia': 'VIERNES', 'litros': 700, 'telefono': '934601006', 'latitud': -33.11413, 'longitud': -71.660864},
    {'camion': 'M1', 'nombre': 'Paz Salvo', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1228611111, 'longitud': -71.6620277778},
    {'camion': 'M1', 'nombre': 'Raquel Mancilla', 'dia': 'LUNES', 'litros': 2800, 'telefono': '', 'latitud': -33.12775, 'longitud': -71.6599722222},
    {'camion': 'M1', 'nombre': 'Reinaldo Salazar', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '', 'latitud': -33.1159722222, 'longitud': -71.6617777778},
    {'camion': 'M1', 'nombre': 'Rodrigo Bravo', 'dia': 'VIERNES', 'litros': 700, 'telefono': '962313770', 'latitud': -33.117314, 'longitud': -71665618.0},
    {'camion': 'M1', 'nombre': 'Rosita Ramirez', 'dia': 'LUNES', 'litros': 1400, 'telefono': '', 'latitud': -33.123981, 'longitud': -71.666043},
    {'camion': 'M1', 'nombre': 'Sandra Sepulveda', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.1188055556, 'longitud': -71.6660833333},
    {'camion': 'M1', 'nombre': 'Segundo Parra', 'dia': 'LUNES', 'litros': 1400, 'telefono': '', 'latitud': -33.124811, 'longitud': -71.6634},
    {'camion': 'M1', 'nombre': 'Sergio Palacios', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '932907788', 'latitud': -33.121051, 'longitud': -71.663421},
    {'camion': 'M1', 'nombre': 'SOLEDAD MYRIAM RODRIGUEZ MANCILLA', 'dia': 'VIERNES', 'litros': 2800, 'telefono': '981890934', 'latitud': -33.112954, 'longitud': -71.663846},
    {'camion': 'M1', 'nombre': 'Stefani Aldunce', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '', 'latitud': -33.1115833333, 'longitud': -71.6623333333},
    {'camion': 'M1', 'nombre': 'Susan Meriño', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.12325, 'longitud': -71.662745},
    {'camion': 'M1', 'nombre': 'Tatiana Pinto', 'dia': 'MARTES', 'litros': 2100, 'telefono': '', 'latitud': -33.123024, 'longitud': -71.664607},
    {'camion': 'M1', 'nombre': 'Thabata Saenz', 'dia': 'VIERNES', 'litros': 2800, 'telefono': '966072820', 'latitud': -33.1147222222, 'longitud': -71.6645555556},
    {'camion': 'M1', 'nombre': 'Veronica Astudillo', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.1182777778, 'longitud': -71.6661944444},
    {'camion': 'M1', 'nombre': 'Ximena Bahamondes', 'dia': 'VIERNES', 'litros': 2800, 'telefono': '', 'latitud': -33.1149444444, 'longitud': -71.6619722222},
    {'camion': 'M1', 'nombre': 'Yolanda Salvatori', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.123915, 'longitud': -71.66374},
    {'camion': 'M1', 'nombre': 'Zoila Rojas', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.125314, 'longitud': -71.663612},
    {'camion': 'M2', 'nombre': 'ADELA ESCURRA SEQUEIRA', 'dia': 'VIERNES', 'litros': 700, 'telefono': '931269573', 'latitud': -33.1236663, 'longitud': -71.677613},
    {'camion': 'M2', 'nombre': 'ALEJANDRO CORTEZ CONTRERAS', 'dia': 'MIERCOLES', 'litros': 3500, 'telefono': '998750720', 'latitud': -33.129485, 'longitud': -71.685001},
    {'camion': 'M2', 'nombre': 'Ale Rios', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1262222222, 'longitud': -71.674},
    {'camion': 'M2', 'nombre': 'ALFONSO MOLINA FUENTES', 'dia': 'MARTES', 'litros': 700, 'telefono': '995268983', 'latitud': -33.132016, 'longitud': -71.681859},
    {'camion': 'M2', 'nombre': 'Alina Corvalan', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.126359, 'longitud': -71.676676},
    {'camion': 'M2', 'nombre': 'Ana Cabrera', 'dia': 'LUNES', 'litros': 2100, 'telefono': '', 'latitud': -33.133174, 'longitud': -71.68563},
    {'camion': 'M2', 'nombre': 'Ana Figueroa', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.132974, 'longitud': -71.689703},
    {'camion': 'M2', 'nombre': 'Andrea Soto Olguin', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '', 'latitud': -33.136875, 'longitud': -71.691823},
    {'camion': 'M2', 'nombre': 'ANGELA PAMELA ROBLES ZANZI', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '986837318', 'latitud': -33.130779, 'longitud': -71.678445},
    {'camion': 'M2', 'nombre': 'Aurora Zapata', 'dia': 'VIERNES', 'litros': 1000, 'telefono': '', 'latitud': -33.1259444444, 'longitud': -71.6743611111},
    {'camion': 'M2', 'nombre': 'Barbara Gutierres', 'dia': 'JUEVES', 'litros': 4200, 'telefono': '', 'latitud': -33.12872, 'longitud': -71.673192},
    {'camion': 'M2', 'nombre': 'BERNARDO ARTURO LOPEZ JIMENEZ', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '973400956', 'latitud': -33.1292907, 'longitud': -71.6730073},
    {'camion': 'M2', 'nombre': 'Berta Canales', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.128129, 'longitud': -71.67334},
    {'camion': 'M2', 'nombre': 'Blas Araneda', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.126249, 'longitud': -71.677135},
    {'camion': 'M2', 'nombre': 'Bony Ordenes', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.1296944444, 'longitud': -71.6782222222},
    {'camion': 'M2', 'nombre': 'Carlos Barrales', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.127703, 'longitud': -71.67611},
    {'camion': 'M2', 'nombre': 'Carmen Basualto', 'dia': 'MARTES', 'litros': 1400, 'telefono': '999868523', 'latitud': -33.1328055556, 'longitud': -71.6756944444},
    {'camion': 'M2', 'nombre': 'Carol Hernandez', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.125903, 'longitud': -71.676652},
    {'camion': 'M2', 'nombre': 'Carolina Quitral', 'dia': 'MARTES', 'litros': 3500, 'telefono': '', 'latitud': -33.1317777778, 'longitud': -71.67575},
    {'camion': 'M2', 'nombre': 'Cathalyna Hernandez', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '', 'latitud': -33.129037, 'longitud': -71.67315},
    {'camion': 'M2', 'nombre': 'Claudia Martinez', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.1338333333, 'longitud': -71.6810833333},
    {'camion': 'M2', 'nombre': 'Claudio Correa', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '', 'latitud': -33.126843, 'longitud': -71.681437},
    {'camion': 'M2', 'nombre': 'DAVID MANUEL PINO ROCCO', 'dia': 'MARTES', 'litros': 1400, 'telefono': '926099398', 'latitud': -33.131256, 'longitud': -71.676323},
    {'camion': 'M2', 'nombre': 'EDUARDO ERNESTO ARANGUIZ CHAVEZ', 'dia': 'MARTES', 'litros': 700, 'telefono': '992137274', 'latitud': -33.131875, 'longitud': -71.68578},
    {'camion': 'M2', 'nombre': 'ELIAS RIVERA VALDIVIA', 'dia': 'LUNES', 'litros': 3500, 'telefono': '956930790', 'latitud': -33.135565, 'longitud': -71.684784},
    {'camion': 'M2', 'nombre': 'EMA MENESES LOPEZ', 'dia': 'LUNES', 'litros': 700, 'telefono': '940023177', 'latitud': -33.135011, 'longitud': -71.690909},
    {'camion': 'M2', 'nombre': 'EMILIANO FRANCISCO PIMIENTA SAAVEDRA', 'dia': 'MARTES', 'litros': 1400, 'telefono': '944639753', 'latitud': -33.13184, 'longitud': -71.678869},
    {'camion': 'M2', 'nombre': 'Escuela El Bosque', 'dia': 'VIERNES', 'litros': 3500, 'telefono': '', 'latitud': -33.1265, 'longitud': -71.6786666667},
    {'camion': 'M2', 'nombre': 'Eugenia Dasme', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.126674, 'longitud': -71.67782},
    {'camion': 'M2', 'nombre': 'Eva Poblete', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.127525, 'longitud': -71.671952},
    {'camion': 'M2', 'nombre': 'Francisca Soto', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.12703, 'longitud': -71.671686},
    {'camion': 'M2', 'nombre': 'Galindo Vera', 'dia': 'JUEVES', 'litros': 2800, 'telefono': '', 'latitud': -33.128, 'longitud': -71.677101},
    {'camion': 'M2', 'nombre': 'German Delgado', 'dia': 'JUEVES', 'litros': 4200, 'telefono': '', 'latitud': -33.128936, 'longitud': -71.681667},
    {'camion': 'M2', 'nombre': 'GINA LIRA RICH', 'dia': 'LUNES', 'litros': 700, 'telefono': '991763650', 'latitud': -33.1352019, 'longitud': -71.6869729},
    {'camion': 'M2', 'nombre': 'Gisela Pasten', 'dia': 'MARTES', 'litros': 2800, 'telefono': '', 'latitud': -33.132126, 'longitud': -71.686629},
    {'camion': 'M2', 'nombre': 'Griselda Escobar', 'dia': 'MARTES', 'litros': 2100, 'telefono': '', 'latitud': -33.1326388889, 'longitud': -71.6769722222},
    {'camion': 'M2', 'nombre': 'HERNAN GARRIDO', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.130624, 'longitud': -71.675878},
    {'camion': 'M2', 'nombre': 'Himberly Rojas', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.135082, 'longitud': -71.68698},
    {'camion': 'M2', 'nombre': 'Isabel Concha', 'dia': 'MIERCOLES', 'litros': 2800, 'telefono': '', 'latitud': -33.1291388889, 'longitud': -71.6711944444},
    {'camion': 'M2', 'nombre': 'ISOLINA SALVATIERRA TORRES', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '964646123', 'latitud': -33.129936, 'longitud': -71.679253},
    {'camion': 'M2', 'nombre': 'JACQUELINE DEL CARMEN GARCÍA GARRIDO', 'dia': 'LUNES', 'litros': 2800, 'telefono': '964352116', 'latitud': -33.129335, 'longitud': -71.679557},
    {'camion': 'M2', 'nombre': 'Jacqueline Gomez', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '', 'latitud': -33.12425, 'longitud': -71.6758611111},
    {'camion': 'M2', 'nombre': 'JACQUELINE LEUMAN LEON', 'dia': 'MARTES', 'litros': 1400, 'telefono': '996336841', 'latitud': -33.131503, 'longitud': -71.684143},
    {'camion': 'M2', 'nombre': 'Jasmine Ibañez', 'dia': 'LUNES', 'litros': 2100, 'telefono': '', 'latitud': -33.1336111111, 'longitud': -71.6822777778},
    {'camion': 'M2', 'nombre': 'Johanna Morales', 'dia': 'JUEVES', 'litros': 2100, 'telefono': '', 'latitud': -33.128181, 'longitud': -71.68195},
    {'camion': 'M2', 'nombre': 'Jorge Hermocilla', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.128498, 'longitud': -71.674115},
    {'camion': 'M2', 'nombre': 'Jorge Vargas', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '', 'latitud': -33.1297777778, 'longitud': -71.6716944444},
    {'camion': 'M2', 'nombre': 'JOSE AVENDAÑO', 'dia': 'LUNES', 'litros': 1400, 'telefono': '977774160', 'latitud': -33.133418, 'longitud': -71.68969},
    {'camion': 'M2', 'nombre': 'Jose Hidalgo', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '986207689', 'latitud': -33.125595, 'longitud': -71.677065},
    {'camion': 'M2', 'nombre': 'Juan Diaz Silva', 'dia': 'MARTES', 'litros': 2800, 'telefono': '', 'latitud': -33.1318055556, 'longitud': -71.6783611111},
    {'camion': 'M2', 'nombre': 'Julio Villegas', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.127408, 'longitud': -71.67785},
    {'camion': 'M2', 'nombre': 'Kamila Pasten', 'dia': 'MARTES', 'litros': 2100, 'telefono': '981441852', 'latitud': -33.13216, 'longitud': -71.686218},
    {'camion': 'M2', 'nombre': 'Karina Franco', 'dia': 'VIERNES', 'litros': 700, 'telefono': '', 'latitud': -33.124087, 'longitud': -71.676382},
    {'camion': 'M2', 'nombre': 'Kyra Olivares', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1259444444, 'longitud': -71.6761388889},
    {'camion': 'M2', 'nombre': 'LEONTINA JARA RETAMAL', 'dia': 'MARTES', 'litros': 1400, 'telefono': '995732608', 'latitud': -33.131631, 'longitud': -71.680756},
    {'camion': 'M2', 'nombre': 'Luisa Rey', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.128102, 'longitud': -71.681064},
    {'camion': 'M2', 'nombre': 'Luis Fuentes', 'dia': 'MARTES', 'litros': 1400, 'telefono': '', 'latitud': -33.1315833333, 'longitud': -71.6755555556},
    {'camion': 'M2', 'nombre': 'LUIS MANUEL RODRIGUEZ BENAVIDES', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '996336841', 'latitud': -33.129335, 'longitud': -71.679557},
    {'camion': 'M2', 'nombre': 'Luis Marchan', 'dia': 'JUEVES', 'litros': 700, 'telefono': '', 'latitud': -33.128017, 'longitud': -71.677004},
    {'camion': 'M2', 'nombre': 'MARCELO HOLLOWAY MENA', 'dia': 'LUNES', 'litros': 700, 'telefono': '964646123', 'latitud': -33.129936, 'longitud': -71.679253},
    {'camion': 'M2', 'nombre': 'Margarita Maira', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.13275, 'longitud': -71.6803055556},
    {'camion': 'M2', 'nombre': 'Maria Berrios', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '', 'latitud': -33.127109, 'longitud': -71.67142},
    {'camion': 'M2', 'nombre': 'Maria Fuentes', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.13286, 'longitud': -71.688758},
    {'camion': 'M2', 'nombre': 'Maria Isabel Fernandez', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '', 'latitud': -33.1296111111, 'longitud': -71.6717777778},
    {'camion': 'M2', 'nombre': 'Maria Jose Vidal', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '', 'latitud': -33.126778, 'longitud': -71.672855},
    {'camion': 'M2', 'nombre': 'Maria Martinez', 'dia': 'JUEVES', 'litros': 700, 'telefono': '939694772', 'latitud': -33.127389, 'longitud': -71.678047},
    {'camion': 'M2', 'nombre': 'MARIA NORALBA MENESES', 'dia': 'MIERCOLES', 'litros': 700, 'telefono': '954089939', 'latitud': -33.130639, 'longitud': -71.680041},
    {'camion': 'M2', 'nombre': 'Maria Pino', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '', 'latitud': -33.125052, 'longitud': -71.677508},
    {'camion': 'M2', 'nombre': 'Maria Teresa Mora', 'dia': 'VIERNES', 'litros': 2100, 'telefono': '', 'latitud': -33.1252777778, 'longitud': -71.6771944444},
    {'camion': 'M2', 'nombre': 'Maria Zapata Muñoz', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '', 'latitud': -33.128817, 'longitud': -71.6827},
    {'camion': 'M2', 'nombre': 'Maricela Perez', 'dia': 'VIERNES', 'litros': 4200, 'telefono': '', 'latitud': -33.126108, 'longitud': -71.675645},
    {'camion': 'M2', 'nombre': 'Marisol Mendoza', 'dia': 'VIERNES', 'litros': 3500, 'telefono': '', 'latitud': -33.124335, 'longitud': -71.678157},
    {'camion': 'M2', 'nombre': 'Marta Arcaya', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1265, 'longitud': -71.6794166667},
    {'camion': 'M2', 'nombre': 'Matilde Cortez', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.1328333333, 'longitud': -71.6758333333},
    {'camion': 'M2', 'nombre': 'Miguel Vargas', 'dia': 'JUEVES', 'litros': 2800, 'telefono': '', 'latitud': -33.128435, 'longitud': -71.676645},
    {'camion': 'M2', 'nombre': 'MONICA ANDREA SANZANA CAMPOS', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '993110694', 'latitud': -33.12911, 'longitud': -71.674348},
    {'camion': 'M2', 'nombre': 'Nancy Ascueta', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '985882777', 'latitud': -33.10069, 'longitud': -71660800.0},
    {'camion': 'M2', 'nombre': 'Nancy Santander', 'dia': 'LUNES', 'litros': 2500, 'telefono': '', 'latitud': -33.1332222222, 'longitud': -71.68},
    {'camion': 'M2', 'nombre': 'Nicolas Padilla', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '957117639', 'latitud': -33.1310555556, 'longitud': -71.6730555556},
    {'camion': 'M2', 'nombre': 'PATRICIA ALVAREZ MIQUEL', 'dia': 'LUNES', 'litros': 2800, 'telefono': '962714265', 'latitud': -33.134328, 'longitud': -71.686365},
    {'camion': 'M2', 'nombre': 'Patricio Moya', 'dia': 'MARTES', 'litros': 2100, 'telefono': '', 'latitud': -33.1318055556, 'longitud': -71.67875},
    {'camion': 'M2', 'nombre': 'PAULA LOPEZ MARTIN', 'dia': 'LUNES', 'litros': 2800, 'telefono': '989428502', 'latitud': -33.134775, 'longitud': -71.682011},
    {'camion': 'M2', 'nombre': 'Paulina Miranda', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '992279947', 'latitud': -33.129452, 'longitud': -71.678903},
    {'camion': 'M2', 'nombre': 'Raul Cares', 'dia': 'LUNES', 'litros': 1400, 'telefono': '', 'latitud': -33.13432, 'longitud': -71.687424},
    {'camion': 'M2', 'nombre': 'Rita Norin', 'dia': 'JUEVES', 'litros': 1400, 'telefono': '', 'latitud': -33.128399, 'longitud': -71.680649},
    {'camion': 'M2', 'nombre': 'ROBERTO FUENTES', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '987006705', 'latitud': -33.130364, 'longitud': -71.675257},
    {'camion': 'M2', 'nombre': 'Rocio Flores', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '', 'latitud': -33.130397, 'longitud': -71.680082},
    {'camion': 'M2', 'nombre': 'Rogelio Canales', 'dia': 'LUNES', 'litros': 4200, 'telefono': '', 'latitud': -33.1347222222, 'longitud': -71.6806388889},
    {'camion': 'M2', 'nombre': 'Romina Carrasco', 'dia': 'MIERCOLES', 'litros': 2100, 'telefono': '', 'latitud': -33.129176, 'longitud': -71.672128},
    {'camion': 'M2', 'nombre': 'ROSA PALMA', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.13054, 'longitud': -71.67515},
    {'camion': 'M2', 'nombre': 'Rosa Vidal', 'dia': 'LUNES', 'litros': 2800, 'telefono': '', 'latitud': -33.1331388889, 'longitud': -71.6800833333},
    {'camion': 'M2', 'nombre': 'Ruben Burgos', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.12651, 'longitud': -71.676568},
    {'camion': 'M2', 'nombre': 'Sara Contreras', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.1266666667, 'longitud': -71.6788055556},
    {'camion': 'M2', 'nombre': 'Sergio Espinozas', 'dia': 'LUNES', 'litros': 700, 'telefono': '', 'latitud': -33.1330833333, 'longitud': -71.6800833333},
    {'camion': 'M2', 'nombre': 'Sergio Quezada', 'dia': 'MIERCOLES', 'litros': 1400, 'telefono': '', 'latitud': -33.129545, 'longitud': -71.678599},
    {'camion': 'M2', 'nombre': 'Sonia Fernandez', 'dia': 'VIERNES', 'litros': 1400, 'telefono': '', 'latitud': -33.125797, 'longitud': -71.674382},
    {'camion': 'M2', 'nombre': 'Stephanie Ordenes', 'dia': 'LUNES', 'litros': 2100, 'telefono': '', 'latitud': -33.1296944444, 'longitud': -71.6782222222},
    {'camion': 'M2', 'nombre': 'Susana Valenzuela', 'dia': 'MARTES', 'litros': 700, 'telefono': '', 'latitud': -33.132601, 'longitud': -71.68563},
    {'camion': 'M2', 'nombre': 'Tomas Salinas', 'dia': 'LUNES', 'litros': 2100, 'telefono': '', 'latitud': -33.1336111111, 'longitud': -71.6798611111},
    {'camion': 'M2', 'nombre': 'Veronica Sanchez', 'dia': 'VIERNES', 'litros': 700, 'telefono': '990693634', 'latitud': -33.117657, 'longitud': -71665445.0},
    {'camion': 'M2', 'nombre': 'Virginia Norambuena', 'dia': 'LUNES', 'litros': 1400, 'telefono': '', 'latitud': -33.133213, 'longitud': -71.689529},
    {'camion': 'M3', 'nombre': 'ALEJANDRO ZUÑIGA', 'dia': 'LUNES', 'litros': 4900, 'telefono': '', 'latitud': -33.1210555556, 'longitud': -71.6777777778},
    {'camion': 'M3', 'nombre': 'Arnaldo Henriquez', 'dia': 'LUNES', 'litros': 5600, 'telefono': '', 'latitud': -33.1320833333, 'longitud': -71.6796666667},
    {'camion': 'M3', 'nombre': 'BASTIAN ESPINA', 'dia': 'LUNES', 'litros': 4900, 'telefono': '', 'latitud': -33.1225277778, 'longitud': -71.6641666667},
    {'camion': 'M3', 'nombre': 'Dominique Zapata', 'dia': 'MARTES', 'litros': 5600, 'telefono': '', 'latitud': -33.104888, 'longitud': -71.667635},
    {'camion': 'M3', 'nombre': 'ESTANQUE AGUAS CLARAS', 'dia': 'VIERNES', 'litros': 10000, 'telefono': '', 'latitud': -33.1317909, 'longitud': -71.683882},
    {'camion': 'M3', 'nombre': 'ESTANQUE CACIQUE LAUTARO', 'dia': 'VIERNES', 'litros': 10000, 'telefono': '', 'latitud': -33.1258244, 'longitud': -71.6726797},
    {'camion': 'M3', 'nombre': 'ESTANQUE CAMINO AL FARO', 'dia': 'VIERNES', 'litros': 10000, 'telefono': '', 'latitud': 0.0, 'longitud': 0.0},
    {'camion': 'M3', 'nombre': 'ESTANQUE COLA DE ZORRO', 'dia': 'VIERNES', 'litros': 10000, 'telefono': '', 'latitud': -33.1197593, 'longitud': -71.692351},
    {'camion': 'M3', 'nombre': 'ESTANQUE DON ROBERTO', 'dia': 'MARTES', 'litros': 10000, 'telefono': '', 'latitud': 0.0, 'longitud': 0.0},
    {'camion': 'M3', 'nombre': 'ESTANQUE ECOFERIA', 'dia': 'JUEVES', 'litros': 5000, 'telefono': '', 'latitud': -33.1264186, 'longitud': -71.6677528},
    {'camion': 'M3', 'nombre': 'ESTANQUE EL SAUCE', 'dia': 'VIERNES', 'litros': 10000, 'telefono': '', 'latitud': 0.0, 'longitud': 0.0},
    {'camion': 'M3', 'nombre': 'ESTANQUE ESCUELITA CALEDOSCOPIO', 'dia': 'MIERCOLES', 'litros': 5000, 'telefono': '', 'latitud': 0.0, 'longitud': 0.0},
    {'camion': 'M3', 'nombre': 'ESTANQUE LA BALLICA', 'dia': 'JUEVES', 'litros': 10000, 'telefono': '', 'latitud': -33.1407401, 'longitud': -71.6756405},
    {'camion': 'M3', 'nombre': 'ESTANQUE LOS BOLDOS', 'dia': 'JUEVES', 'litros': 10000, 'telefono': '', 'latitud': -33.1384207, 'longitud': -71.6772153},
    {'camion': 'M3', 'nombre': 'ESTANQUE LOS CIPRECES', 'dia': 'VIERNES', 'litros': 10000, 'telefono': '', 'latitud': -33.1222208, 'longitud': -71.6776666},
    {'camion': 'M3', 'nombre': 'ESTANQUE MEMBRILLAR', 'dia': 'MIERCOLES', 'litros': 30000, 'telefono': '', 'latitud': -33.142191, 'longitud': -71.651788},
    {'camion': 'M3', 'nombre': 'ESTANQUE POEMA DE OLY', 'dia': 'nan', 'litros': 10000, 'telefono': '', 'latitud': -33.1230208, 'longitud': -71.6933257},
    {'camion': 'M3', 'nombre': 'ESTANQUE QUEBRADA HONDA', 'dia': 'VIERNES', 'litros': 15000, 'telefono': '', 'latitud': -33.1330791, 'longitud': -71.6799881},
    {'camion': 'M3', 'nombre': 'ESTANQUE QUINTAY 2', 'dia': 'JUEVES', 'litros': 10000, 'telefono': '', 'latitud': -33.149015, 'longitud': -71.672304},
    {'camion': 'M3', 'nombre': 'ESTANQUE RIO BUENO', 'dia': 'VIERNES', 'litros': 10000, 'telefono': '', 'latitud': -33.131018, 'longitud': -71.675748},
    {'camion': 'M3', 'nombre': 'ESTANQUE TIERRA ROJAS', 'dia': 'MIERCOLES', 'litros': 10000, 'telefono': '', 'latitud': -33.134298, 'longitud': -71.65894},
    {'camion': 'M3', 'nombre': 'ESTANQUE TIO EMILIO', 'dia': 'MARTES', 'litros': 10000, 'telefono': '', 'latitud': 0.0, 'longitud': 0.0},
    {'camion': 'M3', 'nombre': 'ESTEFANI MIRANDA', 'dia': 'MARTES', 'litros': 4900, 'telefono': '', 'latitud': -33.1195555556, 'longitud': -71.7069166667},
    {'camion': 'M3', 'nombre': 'JOSE RODRIGUEZ', 'dia': 'LUNES', 'litros': 4900, 'telefono': '', 'latitud': -33.1293888889, 'longitud': -71.6653333333},
    {'camion': 'M3', 'nombre': 'LUIS ALLENDE', 'dia': 'MARTES', 'litros': 2500, 'telefono': '', 'latitud': -33.1196825963, 'longitud': -71.6919259173},
    {'camion': 'M3', 'nombre': 'MOISES SOTO', 'dia': 'LUNES', 'litros': 4900, 'telefono': '', 'latitud': -33.1434444444, 'longitud': -71.6523333333},
    {'camion': 'M3', 'nombre': 'PEDRO RETAMAL', 'dia': 'LUNES', 'litros': 4900, 'telefono': '', 'latitud': -33.1267777778, 'longitud': -71.6814166667},
    {'camion': 'M3', 'nombre': 'RUBEN TAPIA SOSSA', 'dia': 'MARTES', 'litros': 4900, 'telefono': '', 'latitud': -33.1183611111, 'longitud': -71.7024166667},
    {'camion': 'M3', 'nombre': 'SALOME MONTENEGRO', 'dia': 'LUNES', 'litros': 4900, 'telefono': '983051532', 'latitud': -33.1269166667, 'longitud': -71.66625},
    {'camion': 'M3', 'nombre': 'SEBASTIANA VEGA', 'dia': 'LUNES', 'litros': 4900, 'telefono': '', 'latitud': -33.12675, 'longitud': -71.6798611111},
    {'camion': 'M3', 'nombre': 'TOMAS CAMPO', 'dia': 'LUNES', 'litros': 4900, 'telefono': '', 'latitud': -33.12525, 'longitud': -71.6596944444}
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
app = FastAPI(title=APP_NAME, version="2.5")

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
    return {"status": "ok", "version": "2.5", "data_mode": DATA_MODE,
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
