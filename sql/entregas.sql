CREATE TABLE IF NOT EXISTS entregas (
  id BIGSERIAL PRIMARY KEY,
  fecha DATE NOT NULL,
  camion VARCHAR(10) NOT NULL,
  nombre TEXT NOT NULL,
  litros NUMERIC(10,2),
  estado SMALLINT NOT NULL,
  motivo TEXT,
  telefono TEXT,
  latitud NUMERIC(10,6),
  longitud NUMERIC(10,6),
  foto_url TEXT,
  usuario TEXT,
  creado_en TIMESTAMP DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_entregas_nncf ON entregas (fecha, camion, nombre);
CREATE INDEX IF NOT EXISTS ix_entregas_fecha ON entregas(fecha);
CREATE INDEX IF NOT EXISTS ix_entregas_camion_fecha ON entregas(camion, fecha);
