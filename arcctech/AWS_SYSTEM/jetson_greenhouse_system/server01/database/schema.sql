PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS monitoring_reading (
  reading_id INTEGER PRIMARY KEY AUTOINCREMENT,
  panel_id INTEGER NOT NULL CHECK (panel_id BETWEEN 1 AND 4),
  measured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  temperature REAL NOT NULL CHECK (temperature BETWEEN 0 AND 120),
  humidity INTEGER NOT NULL CHECK (humidity BETWEEN 0 AND 100),
  is_working INTEGER NOT NULL CHECK (is_working IN (0, 1)),
  work_rate INTEGER NOT NULL CHECK (work_rate BETWEEN 0 AND 100),
  task_name TEXT NOT NULL CHECK (task_name IN ('보식', '감시')),
  disease_part TEXT NOT NULL CHECK (disease_part IN ('잎', '뿌리', '꽃', '열매')),
  disease_type TEXT NOT NULL CHECK (disease_type IN ('정상', '탄저병', '흰곰팡이병')),
  disease_probability INTEGER NOT NULL CHECK (disease_probability BETWEEN 0 AND 100),
  supply_amount REAL NOT NULL CHECK (supply_amount BETWEEN 0 AND 750),
  is_verified INTEGER NOT NULL CHECK (is_verified IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_monitoring_panel_time
ON monitoring_reading(panel_id, measured_at DESC);

CREATE INDEX IF NOT EXISTS idx_monitoring_time
ON monitoring_reading(measured_at DESC);
