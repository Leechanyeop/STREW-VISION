import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import Database from 'better-sqlite3';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.join(__dirname, '..');
const dataDir = path.join(rootDir, 'data');
const dbPath = path.join(dataDir, 'greenhouse.db');
const schemaPath = path.join(rootDir, 'database', 'schema.sql');

fs.mkdirSync(dataDir, { recursive: true });

const db = new Database(dbPath);
db.pragma('foreign_keys = ON');
const rawSchema = fs.readFileSync(schemaPath, 'utf8');
const bootstrapSchema = rawSchema
  .replace(/CREATE INDEX IF NOT EXISTS idx_robot_tasks_queue[^;]+;\s*/g, '')
  .replace(/CREATE INDEX IF NOT EXISTS idx_vision_events_robot_time[^;]+;\s*/g, '');
db.exec(bootstrapSchema);

const columnNames = (table) => db.prepare(`PRAGMA table_info(${table})`).all().map((row) => row.name);
const addColumnIfMissing = (table, column, definition) => {
  if (!columnNames(table).includes(column)) db.exec(`ALTER TABLE ${table} ADD COLUMN ${column} ${definition}`);
};

addColumnIfMissing('robot_tasks', 'robot_id', "TEXT NOT NULL DEFAULT 'robot-01'");
addColumnIfMissing('robot_tasks', 'execute_task', "TEXT NOT NULL DEFAULT 'NOOP'");
addColumnIfMissing('robot_tasks', 'move_sign', "TEXT NOT NULL DEFAULT 'STOP'");
addColumnIfMissing('robot_tasks', 'target_label', 'TEXT');
addColumnIfMissing('robot_tasks', 'queue_status', "TEXT NOT NULL DEFAULT 'queued'");
addColumnIfMissing('robot_tasks', 'last_response_payload', 'TEXT');
addColumnIfMissing('robot_tasks', 'sent_at', 'TEXT');
addColumnIfMissing('robot_feedback', 'completion_sign', 'TEXT');
addColumnIfMissing('robot_feedback', 'response_payload', 'TEXT');

db.exec(`
  CREATE TABLE IF NOT EXISTS vision_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    robot_id TEXT NOT NULL DEFAULT 'robot-01',
    cell_id INTEGER,
    source TEXT NOT NULL DEFAULT 'jetson-csi-camera',
    label TEXT,
    confidence REAL,
    x_center INTEGER,
    y_center INTEGER,
    width INTEGER,
    height INTEGER,
    payload TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cell_id) REFERENCES cells(id) ON DELETE SET NULL
  );
  CREATE INDEX IF NOT EXISTS idx_robot_tasks_queue ON robot_tasks(robot_id, queue_status, created_at DESC);
  CREATE INDEX IF NOT EXISTS idx_vision_events_robot_time ON vision_events(robot_id, created_at DESC);
`);

db.prepare(`
  UPDATE robot_tasks
  SET execute_task = CASE task_name
    WHEN 'NUTRITION' THEN 'SUPPLY_NUTRITION'
    WHEN 'OBSERVE' THEN 'OBSERVE_BY_VISION'
    WHEN 'ESTOP' THEN 'EMERGENCY_STOP'
    ELSE 'NOOP'
  END
  WHERE execute_task IS NULL OR execute_task = 'NOOP'
`).run();

const randomInt = (min, max) => Math.floor(Math.random() * (max - min + 1)) + min;
const randomFloat = (min, max, digits = 1) => Number((Math.random() * (max - min) + min).toFixed(digits));
const pick = (items) => items[randomInt(0, items.length - 1)];

const riskFromProbability = (probability) => {
  if (probability >= 80) return { riskLevel: 'DANGER', recommendedTask: 'NUTRITION' };
  if (probability >= 50) return { riskLevel: 'WARNING', recommendedTask: 'OBSERVE' };
  return { riskLevel: 'NORMAL', recommendedTask: 'NONE' };
};

const count = db.prepare('SELECT COUNT(*) AS count FROM sensor_logs').get().count;

if (count === 0) {
  const insertSensor = db.prepare(`
    INSERT INTO sensor_logs(cell_id, measured_at, temperature, humidity, sap_amount_ml, growth_rate, env_warning)
    VALUES (?, ?, ?, ?, ?, ?, ?)
  `);
  const insertAi = db.prepare(`
    INSERT INTO ai_readings(cell_id, sensor_log_id, detected_at, ai_mode, disease_area, disease_name, disease_probability, risk_level, recommended_task, ai_message)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);

  const seed = db.transaction(() => {
    const now = Date.now();
    for (let cellId = 1; cellId <= 4; cellId += 1) {
      for (let step = 23; step >= 0; step -= 1) {
        const measuredAt = new Date(now - step * 15 * 60 * 1000).toISOString();
        const temperature = randomFloat(18 + cellId, 34 + cellId);
        const humidity = randomInt(45, 92);
        const sapAmount = randomFloat(80, 740);
        const growthRate = randomInt(35, 96);
        const envWarning = temperature > 40 || humidity > 95 || sapAmount > 750 ? 'WARNING' : 'NORMAL';
        const sensor = insertSensor.run(cellId, measuredAt, temperature, humidity, sapAmount, growthRate, envWarning);
        const probability = randomInt(0, 100);
        const { riskLevel, recommendedTask } = riskFromProbability(probability);
        insertAi.run(cellId, sensor.lastInsertRowid, measuredAt, probability >= 80 ? 'NUTRITION' : 'OBSERVE', pick(['LEAF', 'ROOT', 'STEM', 'FRUIT']), probability >= 50 ? pick(['leaf_spot', 'root_stress', 'growth_delay']) : 'NORMAL', probability, riskLevel, recommendedTask, `Cell ${cellId}: probability ${probability}%`);
      }
    }

    const dangerRows = db.prepare('SELECT * FROM ai_readings WHERE disease_probability >= 80 ORDER BY detected_at DESC LIMIT 2').all();
    for (const row of dangerRows) {
      const approval = db.prepare('INSERT INTO approvals(ai_reading_id, cell_id, review_message) VALUES (?, ?, ?)').run(row.id, row.cell_id, `Cell ${row.cell_id} requires nutrition approval (${row.disease_probability}%)`);
      const task = db.prepare(`
        INSERT INTO robot_tasks(cell_id, approval_id, robot_id, task_name, execute_task, move_sign, target_label, state_machine, robot_status, queue_status, command_payload)
        VALUES (?, ?, 'robot-01', 'NUTRITION', 'SUPPLY_NUTRITION', 'STOP', 'nutrition_target', 'WAIT_APPROVAL', 'WAITING_APPROVAL', 'queued', ?)
      `).run(row.cell_id, approval.lastInsertRowid, JSON.stringify({ cell_id: row.cell_id, task: 'NUTRITION', execute_task: 'SUPPLY_NUTRITION' }));
      db.prepare('UPDATE robot_tasks SET command_payload = ? WHERE id = ?').run(JSON.stringify({ task_id: task.lastInsertRowid, robot_id: 'robot-01', cell_id: row.cell_id, execute_task: 'SUPPLY_NUTRITION', task_name: 'NUTRITION', move_sign: 'STOP', target_label: 'nutrition_target' }), task.lastInsertRowid);
    }

    db.prepare("INSERT INTO system_events(event_type, message) VALUES ('SYSTEM', 'Database initialized with sample greenhouse data')").run();
  });

  seed();
}

console.log(`Greenhouse database ready: ${dbPath}`);

