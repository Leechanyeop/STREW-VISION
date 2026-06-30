//PRAGMA foreign_keys = ON; // 외래 키 제약 조건 활성화

CREATE TABLE IF NOT EXISTS cells ( // 온실의 각 셀에 대한 정보를 저장하는 테이블
  id INTEGER PRIMARY KEY CHECK (id BETWEEN 1 AND 4),
  cell_name TEXT NOT NULL,
  location TEXT,
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS thresholds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  metric TEXT NOT NULL UNIQUE,
  min_value REAL,
  max_value REAL,
  unit TEXT,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  description TEXT
);

CREATE TABLE IF NOT EXISTS sensor_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cell_id INTEGER NOT NULL,
  measured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  temperature REAL NOT NULL CHECK (temperature BETWEEN -20 AND 80),
  humidity INTEGER NOT NULL CHECK (humidity BETWEEN 0 AND 100),
  sap_amount_ml REAL NOT NULL CHECK (sap_amount_ml >= 0),
  growth_rate INTEGER CHECK (growth_rate BETWEEN 0 AND 100),
  env_warning TEXT DEFAULT 'NORMAL',
  FOREIGN KEY (cell_id) REFERENCES cells(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ai_readings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cell_id INTEGER NOT NULL,
  sensor_log_id INTEGER,
  detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ai_mode TEXT NOT NULL CHECK (ai_mode IN ('OBSERVE', 'NUTRITION', 'NORMAL')),
  disease_area TEXT CHECK (disease_area IN ('LEAF', 'ROOT', 'STEM', 'FRUIT')),
  disease_name TEXT NOT NULL DEFAULT 'NORMAL',
  disease_probability INTEGER NOT NULL CHECK (disease_probability BETWEEN 0 AND 100),
  risk_level TEXT NOT NULL CHECK (risk_level IN ('NORMAL', 'WARNING', 'DANGER')),
  recommended_task TEXT NOT NULL DEFAULT 'NONE' CHECK (recommended_task IN ('NONE', 'OBSERVE', 'NUTRITION')),
  ai_message TEXT,
  FOREIGN KEY (cell_id) REFERENCES cells(id) ON DELETE CASCADE,
  FOREIGN KEY (sensor_log_id) REFERENCES sensor_logs(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ai_reading_id INTEGER NOT NULL,
  cell_id INTEGER NOT NULL,
  requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  approval_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (approval_status IN ('PENDING', 'APPROVED', 'REJECTED')),
  review_message TEXT NOT NULL,
  approved_by TEXT,
  approved_at TEXT,
  FOREIGN KEY (ai_reading_id) REFERENCES ai_readings(id) ON DELETE CASCADE,
  FOREIGN KEY (cell_id) REFERENCES cells(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS robot_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cell_id INTEGER NOT NULL,
  approval_id INTEGER,
  task_name TEXT NOT NULL CHECK (task_name IN ('NUTRITION', 'OBSERVE', 'NONE', 'ESTOP')),
  control_state TEXT NOT NULL DEFAULT 'RUN' CHECK (control_state IN ('RUN', 'STOP', 'ESTOP')),
  state_machine TEXT NOT NULL CHECK (state_machine IN ('AI_DETECT', 'WAIT_APPROVAL', 'EXECUTE_TASK', 'REPORT_STATUS', 'COMPLETE')),
  progress_rate INTEGER NOT NULL DEFAULT 0 CHECK (progress_rate BETWEEN 0 AND 100),
  robot_status TEXT NOT NULL DEFAULT 'WAITING',
  command_payload TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at TEXT,
  completed_at TEXT,
  FOREIGN KEY (cell_id) REFERENCES cells(id) ON DELETE CASCADE,
  FOREIGN KEY (approval_id) REFERENCES approvals(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS robot_feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  cell_id INTEGER NOT NULL,
  reported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  progress_rate INTEGER NOT NULL CHECK (progress_rate BETWEEN 0 AND 100),
  temperature REAL,
  humidity INTEGER CHECK (humidity BETWEEN 0 AND 100),
  sap_amount_ml REAL,
  robot_status TEXT NOT NULL,
  FOREIGN KEY (task_id) REFERENCES robot_tasks(id) ON DELETE CASCADE,
  FOREIGN KEY (cell_id) REFERENCES cells(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS growth_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cell_id INTEGER NOT NULL,
  recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  replant_date TEXT,
  avg_growth_rate INTEGER CHECK (avg_growth_rate BETWEEN 0 AND 100),
  note TEXT,
  FOREIGN KEY (cell_id) REFERENCES cells(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS system_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  event_type TEXT NOT NULL,
  cell_id INTEGER,
  message TEXT NOT NULL,
  FOREIGN KEY (cell_id) REFERENCES cells(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_sensor_logs_cell_time ON sensor_logs(cell_id, measured_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_readings_cell_time ON ai_readings(cell_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(approval_status, requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_robot_tasks_state ON robot_tasks(state_machine, created_at DESC);

INSERT OR IGNORE INTO cells(id, cell_name, location) VALUES
  (1, 'Cell 1', 'A-1'),
  (2, 'Cell 2', 'A-2'),
  (3, 'Cell 3', 'B-1'),
  (4, 'Cell 4', 'B-2');

INSERT OR IGNORE INTO thresholds(metric, min_value, max_value, unit, description) VALUES
  ('temperature', 0, 40, 'C', 'Temperature operating range'),
  ('humidity', 0, 100, '%', 'Humidity operating range'),
  ('sap_amount_ml', 0, 750, 'ml', 'Supply amount operating range'),
  ('disease_probability', 0, 79, '%', '80 percent or higher requires approval');

CREATE TABLE IF NOT EXISTS system_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO system_settings(key, value) VALUES
  ('ai_mode_enabled', '0'),
  ('ai_mode_name', 'AUTO_MONITOR');
