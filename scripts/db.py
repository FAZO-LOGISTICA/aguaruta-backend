import sqlite3

def crear_base_datos():
    conn = sqlite3.connect("entregas.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS entregas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            jefe_hogar TEXT,
            litros INTEGER,
            camion TEXT,
            dia TEXT,
            entregado INTEGER,
            codigo INTEGER,
            motivo TEXT,
            foto TEXT,
            fecha TEXT
        )
    """)
    conn.commit()
    conn.close()

