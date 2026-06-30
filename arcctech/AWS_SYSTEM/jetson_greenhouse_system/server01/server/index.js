import './init-db.js';
import path from 'path';
import { fileURLToPath } from 'url';
import express from 'express';
import cors from 'cors';
import Database from 'better-sqlite3';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.join(__dirname, '..');
const db = new Database(path.join(rootDir, 'data', 'strew_vision.db'));
const app = express();
const port = Number(process.env.PORT || 4100);

db.pragma('foreign_keys = ON');
app.use(cors());
app.use(express.json());
app.use(express.static(rootDir));

const parts = ['잎', '뿌리', '꽃', '열매'];
const diseaseTypes = ['정상', '탄저병', '흰곰팡이병'];
const taskNames = ['보식', '감시'];
const randomInt = (min, max) => Math.floor(Math.random() * (max - min + 1)) + min;
const randomFloat = (min, max, digits = 1) => Number((Math.random() * (max - min) + min).toFixed(digits));
const pick = (items) => items[randomInt(0, items.length - 1)];

const insertRandomReading = db.prepare(`
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

const randomizeDatabase = db.transaction(() => {
  db.prepare('DELETE FROM monitoring_reading').run();

  const now = Date.now();
  for (let panelId = 1; panelId <= 4; panelId += 1) {
    for (let step = 23; step >= 0; step -= 1) {
      const working = Math.random() > 0.16 ? 1 : 0;
      const diseaseType = Math.random() > 0.78 ? pick(diseaseTypes.slice(1)) : '정상';
      const diseaseProbability = diseaseType === '정상' ? randomInt(0, 18) : randomInt(58, 100);
      const wave = Math.sin((24 - step + panelId) / 4);
      const measuredAt = new Date(now - step * 15 * 60 * 1000).toISOString();

      insertRandomReading.run(
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

const rowToReading = (row) => ({
  id: row.panel_id,
  measuredAt: row.measured_at,
  temperature: row.temperature,
  humidity: row.humidity,
  isWorking: Boolean(row.is_working),
  workRate: row.work_rate,
  taskName: row.task_name,
  diseasePart: row.disease_part,
  diseaseType: row.disease_type,
  diseaseProbability: row.disease_probability,
  supplyAmount: row.supply_amount,
  isVerified: Boolean(row.is_verified),
  status: row.disease_type === '정상' && row.is_verified ? 'normal' : row.disease_probability >= 75 ? 'danger' : 'warning'
});

const buildDashboard = () => {
  const latest = db.prepare(`
    SELECT *
    FROM monitoring_reading mr
    WHERE reading_id = (
      SELECT reading_id
      FROM monitoring_reading
      WHERE panel_id = mr.panel_id
      ORDER BY measured_at DESC, reading_id DESC
      LIMIT 1
    )
    ORDER BY panel_id
  `).all().map(rowToReading);

  const history = db.prepare(`
    SELECT *
    FROM monitoring_reading
    ORDER BY measured_at DESC, reading_id DESC
    LIMIT 96
  `).all().map(rowToReading).reverse();

  const average = (field) => latest.length
    ? Number((latest.reduce((sum, item) => sum + Number(item[field] || 0), 0) / latest.length).toFixed(1))
    : 0;

  const activeCount = latest.filter((item) => item.isWorking).length;
  const warningCount = latest.filter((item) => item.status !== 'normal').length;
  const verifiedCount = latest.filter((item) => item.isVerified).length;

  return {
    generatedAt: new Date().toISOString(),
    panels: latest,
    history,
    summary: {
      panelCount: latest.length,
      activeCount,
      warningCount,
      verifiedCount,
      avgTemperature: average('temperature'),
      avgHumidity: average('humidity'),
      avgWorkRate: average('workRate'),
      avgDiseaseProbability: average('diseaseProbability'),
      totalSupply: Number(latest.reduce((sum, item) => sum + Number(item.supplyAmount || 0), 0).toFixed(1))
    }
  };
};

app.get('/api/dashboard', (_req, res) => {
  res.json(buildDashboard());
});

app.get('/api/readings', (_req, res) => {
  const readings = db.prepare(`
    SELECT *
    FROM monitoring_reading
    ORDER BY measured_at DESC, reading_id DESC
    LIMIT 120
  `).all().map(rowToReading);

  res.json({ readings });
});

app.post('/api/randomize', (_req, res) => {
  randomizeDatabase();
  res.json(buildDashboard());
});

app.listen(port, () => {
  console.log(`STREW monitoring web/API: http://localhost:${port}`);
});
