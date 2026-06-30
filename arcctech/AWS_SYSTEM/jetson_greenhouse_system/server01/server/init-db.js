import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import Database from 'better-sqlite3';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.join(__dirname, '..');
const dataDir = path.join(rootDir, 'data');
const dbPath = path.join(dataDir, 'strew_vision.db');
const schemaPath = path.join(rootDir, 'database', 'schema.sql');

fs.mkdirSync(dataDir, { recursive: true });

const db = new Database(dbPath);
db.pragma('foreign_keys = ON');

const legacyTables = [
  'farm',
  'zone',
  'cell',
  'pot',
  'robot',
  'device',
  'crop_planting',
  'sensor_reading',
  'nutrient_supply_log',
  'farm_diary',
  'plant_event',
  'robot_operation_log',
  'robot_task_log',
  'device_status_log',
  'power_usage_log',
  'vision_detection'
];

db.pragma('foreign_keys = OFF');
for (const tableName of legacyTables) {
  db.prepare(`DROP TABLE IF EXISTS ${tableName}`).run();
}
db.pragma('foreign_keys = ON');
db.exec(fs.readFileSync(schemaPath, 'utf8'));

const parts = ['잎', '뿌리', '꽃', '열매'];
const diseaseTypes = ['정상', '탄저병', '흰곰팡이병'];
const taskNames = ['보식', '감시'];
const randomInt = (min, max) => Math.floor(Math.random() * (max - min + 1)) + min;
const randomFloat = (min, max, digits = 1) => Number((Math.random() * (max - min) + min).toFixed(digits));
const pick = (items) => items[randomInt(0, items.length - 1)];

const insertReading = db.prepare(`
  INSERT INTO monitoring_reading
  (
    panel_id,
    measured_at,
    temperature,
    humidity,
    is_working,
    work_rate,
    task_name,
    disease_part,
    disease_type,
    disease_probability,
    supply_amount,
    is_verified
  )
  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
`);

const seedRandomReadings = db.transaction(() => {
  db.prepare('DELETE FROM monitoring_reading').run();

  const now = Date.now();
  for (let panelId = 1; panelId <= 4; panelId += 1) {
    for (let step = 23; step >= 0; step -= 1) {
      const working = Math.random() > 0.16 ? 1 : 0;
      const diseaseType = Math.random() > 0.78 ? pick(diseaseTypes.slice(1)) : '정상';
      const diseaseProbability = diseaseType === '정상' ? randomInt(0, 18) : randomInt(58, 100);
      const wave = Math.sin((24 - step + panelId) / 4);
      const measuredAt = new Date(now - step * 15 * 60 * 1000).toISOString();

      insertReading.run(
        panelId,
        measuredAt,
        randomFloat(18 + panelId * 1.2 + wave * 4, 34 + panelId * 1.8 + wave * 5),
        randomInt(42, 92),
        working,
        working ? randomInt(35, 100) : randomInt(0, 12),
        pick(taskNames),
        pick(parts),
        diseaseType,
        diseaseProbability,
        randomFloat(80, 750),
        diseaseType === '정상' || Math.random() > 0.35 ? 1 : 0
      );
    }
  }
});

seedRandomReadings();

console.log(`STREW monitoring database ready: ${dbPath}`);
