import './init-db.js';
import path from 'path';
import { fileURLToPath } from 'url';
import express from 'express';
import cors from 'cors';
import Database from 'better-sqlite3';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.join(__dirname, '..');
const db = new Database(path.join(rootDir, 'data', 'greenhouse.db'));
const app = express();
const port = Number(process.env.PORT || 4100);
const defaultRobotId = process.env.ROBOT_ID || 'robot-01';

db.pragma('foreign_keys = ON');
app.use(cors());
app.use(express.json());
app.use(express.static(rootDir));
app.get('/admin', (_req, res) => res.sendFile(path.join(rootDir, 'admin.html')));
app.get('/details', (_req, res) => res.sendFile(path.join(rootDir, 'details.html')));

const randomInt = (min, max) => Math.floor(Math.random() * (max - min + 1)) + min;
const randomFloat = (min, max, digits = 1) => Number((Math.random() * (max - min) + min).toFixed(digits));
const pick = (items) => items[randomInt(0, items.length - 1)];

const normalizeTask = (value) => {
  const task = String(value || 'NONE').toUpperCase();
  if (['NUTRITION', 'OBSERVE', 'ESTOP', 'NONE'].includes(task)) return task;
  if (task.includes('PICK') || task.includes('VISION')) return 'OBSERVE';
  return 'NONE';
};

const taskToExecute = (taskName) => {
  if (taskName === 'NUTRITION') return 'SUPPLY_NUTRITION';
  if (taskName === 'OBSERVE') return 'OBSERVE_BY_VISION';
  if (taskName === 'ESTOP') return 'EMERGENCY_STOP';
  return 'NOOP';
};

const safeJsonParse = (text, fallback = {}) => {
  if (!text) return fallback;
  try { return JSON.parse(text); } catch { return fallback; }
};

const riskFromProbability = (probability) => {
  if (probability >= 80) return { riskLevel: 'DANGER', recommendedTask: 'NUTRITION' };
  if (probability >= 50) return { riskLevel: 'WARNING', recommendedTask: 'OBSERVE' };
  return { riskLevel: 'NORMAL', recommendedTask: 'NONE' };
};

const envWarning = (thresholds, payload) => {
  const failed = [];
  for (const metric of ['temperature', 'humidity', 'sap_amount_ml']) {
    const threshold = thresholds[metric];
    const value = payload[metric];
    if (!threshold || value === undefined || value === null) continue;
    if (threshold.min_value !== null && value < threshold.min_value) failed.push(metric);
    if (threshold.max_value !== null && value > threshold.max_value) failed.push(metric);
  }
  return failed.length ? `WARNING:${failed.join(',')}` : 'NORMAL';
};

const getThresholds = () => Object.fromEntries(
  db.prepare('SELECT * FROM thresholds WHERE enabled = 1').all().map((row) => [row.metric, row])
);

const getAiMode = () => {
  const rows = db.prepare("SELECT key, value FROM system_settings WHERE key IN ('ai_mode_enabled', 'ai_mode_name')").all();
  const settings = Object.fromEntries(rows.map((row) => [row.key, row.value]));
  return { enabled: settings.ai_mode_enabled === '1', modeName: settings.ai_mode_name || 'AUTO_MONITOR' };
};

const setAiMode = (enabled, modeName = 'AUTO_MONITOR') => {
  const tx = db.transaction(() => {
    db.prepare(`
      INSERT INTO system_settings(key, value, updated_at)
      VALUES ('ai_mode_enabled', ?, CURRENT_TIMESTAMP)
      ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
    `).run(enabled ? '1' : '0');
    db.prepare(`
      INSERT INTO system_settings(key, value, updated_at)
      VALUES ('ai_mode_name', ?, CURRENT_TIMESTAMP)
      ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
    `).run(modeName || 'AUTO_MONITOR');
    db.prepare("INSERT INTO system_events(event_type, message) VALUES ('AI_MODE', ?)")
      .run(enabled ? `AI mode enabled: ${modeName || 'AUTO_MONITOR'}` : 'AI mode disabled');
  });
  tx();
  return getAiMode();
};

const buildCommandPayload = ({ taskId, cellId, taskName, moveSign = 'STOP', targetLabel = null, payload = {} }) => ({
  task_id: taskId,
  robot_id: defaultRobotId,
  cell_id: cellId,
  execute_task: taskToExecute(taskName),
  task_name: taskName,
  move_sign: moveSign,
  target_label: targetLabel || payload.target_label || taskName.toLowerCase(),
  payload
});

const createRobotTask = ({ cellId, approvalId = null, taskName, stateMachine = 'EXECUTE_TASK', robotStatus = 'QUEUED', moveSign = 'STOP', targetLabel = null, payload = {}, robotId = defaultRobotId }) => {
  const normalizedTask = normalizeTask(taskName);
  const result = db.prepare(`
    INSERT INTO robot_tasks(cell_id, approval_id, robot_id, task_name, execute_task, move_sign, target_label, state_machine, robot_status, command_payload, queue_status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued')
  `).run(cellId, approvalId, robotId, normalizedTask, taskToExecute(normalizedTask), moveSign, targetLabel, stateMachine, robotStatus, JSON.stringify({ ...payload, cell_id: cellId, task: normalizedTask }));
  const command = buildCommandPayload({ taskId: result.lastInsertRowid, cellId, taskName: normalizedTask, moveSign, targetLabel, payload });
  db.prepare('UPDATE robot_tasks SET command_payload = ? WHERE id = ?').run(JSON.stringify(command), result.lastInsertRowid);
  return result.lastInsertRowid;
};

const taskRowToApi = (row) => {
  if (!row) return null;
  const command = safeJsonParse(row.command_payload, {});
  return {
    id: row.id,
    task_id: row.id,
    robot_id: row.robot_id || defaultRobotId,
    cell_id: row.cell_id,
    approval_id: row.approval_id,
    execute_task: row.execute_task || command.execute_task || taskToExecute(row.task_name),
    task_name: row.task_name,
    move_sign: row.move_sign || command.move_sign || 'STOP',
    target_label: row.target_label || command.target_label || null,
    status: row.queue_status || 'queued',
    state_machine: row.state_machine,
    control_state: row.control_state,
    progress_rate: row.progress_rate,
    robot_status: row.robot_status,
    command_payload: command,
    created_at: row.created_at
  };
};

const rowToPanel = (row) => ({
  id: row.cell_id,
  cellName: row.cell_name,
  location: row.location,
  measuredAt: row.measured_at,
  temperature: row.temperature,
  humidity: row.humidity,
  sapAmountMl: row.sap_amount_ml,
  growthRate: row.growth_rate,
  envWarning: row.env_warning || 'NORMAL',
  aiMode: row.ai_mode,
  diseaseArea: row.disease_area,
  diseaseName: row.disease_name || 'NORMAL',
  diseaseProbability: row.disease_probability || 0,
  riskLevel: row.risk_level || 'NORMAL',
  recommendedTask: row.recommended_task || 'NONE',
  taskName: row.task_name,
  controlState: row.control_state,
  stateMachine: row.state_machine || 'AI_DETECT',
  progressRate: row.progress_rate || 0,
  robotStatus: row.robot_status || 'WAITING',
  status: row.risk_level === 'DANGER' ? 'danger' : row.risk_level === 'WARNING' || row.env_warning !== 'NORMAL' ? 'warning' : 'normal'
});

const buildDashboard = () => {
  const panels = db.prepare(`
    SELECT c.id AS cell_id, c.cell_name, c.location, s.measured_at, s.temperature, s.humidity, s.sap_amount_ml,
      s.growth_rate, s.env_warning, a.ai_mode, a.disease_area, a.disease_name, a.disease_probability,
      a.risk_level, a.recommended_task, rt.task_name, rt.control_state, rt.state_machine, rt.progress_rate, rt.robot_status
    FROM cells c
    LEFT JOIN sensor_logs s ON s.id = (SELECT id FROM sensor_logs WHERE cell_id = c.id ORDER BY measured_at DESC, id DESC LIMIT 1)
    LEFT JOIN ai_readings a ON a.id = (SELECT id FROM ai_readings WHERE cell_id = c.id ORDER BY detected_at DESC, id DESC LIMIT 1)
    LEFT JOIN robot_tasks rt ON rt.id = (SELECT id FROM robot_tasks WHERE cell_id = c.id ORDER BY created_at DESC, id DESC LIMIT 1)
    WHERE c.is_active = 1
    ORDER BY c.id
  `).all().map(rowToPanel);

  const history = db.prepare(`
    SELECT s.*, c.cell_name FROM sensor_logs s JOIN cells c ON c.id = s.cell_id
    ORDER BY s.measured_at DESC, s.id DESC LIMIT 120
  `).all().reverse();

  const pendingApprovals = db.prepare(`
    SELECT ap.*, ar.disease_name, ar.disease_probability, ar.ai_mode
    FROM approvals ap JOIN ai_readings ar ON ar.id = ap.ai_reading_id
    WHERE ap.approval_status = 'PENDING'
    ORDER BY ap.requested_at DESC
  `).all();

  const events = db.prepare('SELECT * FROM system_events ORDER BY event_time DESC, id DESC LIMIT 20').all();
  const average = (field) => panels.length ? Number((panels.reduce((sum, item) => sum + Number(item[field] || 0), 0) / panels.length).toFixed(1)) : 0;

  return {
    generatedAt: new Date().toISOString(),
    aiMode: getAiMode(),
    panels,
    history,
    pendingApprovals,
    events,
    summary: {
      cellCount: panels.length,
      warningCount: panels.filter((item) => item.status !== 'normal').length,
      pendingApprovalCount: pendingApprovals.length,
      activeTaskCount: panels.filter((item) => ['WAIT_APPROVAL', 'EXECUTE_TASK', 'REPORT_STATUS'].includes(item.stateMachine)).length,
      avgTemperature: average('temperature'),
      avgHumidity: average('humidity'),
      avgGrowthRate: average('growthRate'),
      avgDiseaseProbability: average('diseaseProbability'),
      totalSapAmountMl: Number(panels.reduce((sum, item) => sum + Number(item.sapAmountMl || 0), 0).toFixed(1))
    }
  };
};

app.get('/api/dashboard', (_req, res) => res.json(buildDashboard()));
app.get('/api/ai-mode', (_req, res) => res.json(getAiMode()));
app.post('/api/ai-mode', (req, res) => res.json(setAiMode(Boolean(req.body?.enabled), req.body?.modeName || 'AUTO_MONITOR')));

app.get('/api/details', (_req, res) => {
  const tasks = db.prepare(`
    SELECT rt.*, c.cell_name, ap.approval_status
    FROM robot_tasks rt
    JOIN cells c ON c.id = rt.cell_id
    LEFT JOIN approvals ap ON ap.id = rt.approval_id
    ORDER BY rt.created_at DESC, rt.id DESC
    LIMIT 80
  `).all();
  const sensorLogs = db.prepare(`
    SELECT s.*, c.cell_name FROM sensor_logs s JOIN cells c ON c.id = s.cell_id
    ORDER BY s.measured_at DESC, s.id DESC LIMIT 160
  `).all();
  const aiReadings = db.prepare(`
    SELECT a.*, c.cell_name FROM ai_readings a JOIN cells c ON c.id = a.cell_id
    ORDER BY a.detected_at DESC, a.id DESC LIMIT 160
  `).all();
  const feedback = db.prepare(`
    SELECT rf.*, c.cell_name FROM robot_feedback rf JOIN cells c ON c.id = rf.cell_id
    ORDER BY rf.reported_at DESC, rf.id DESC LIMIT 100
  `).all();
  const growth = db.prepare(`
    SELECT gr.*, c.cell_name FROM growth_records gr JOIN cells c ON c.id = gr.cell_id
    ORDER BY gr.recorded_at DESC, gr.id DESC LIMIT 80
  `).all();
  const thresholds = db.prepare('SELECT * FROM thresholds ORDER BY metric').all();
  const events = db.prepare('SELECT * FROM system_events ORDER BY event_time DESC, id DESC LIMIT 120').all();
  res.json({ generatedAt: new Date().toISOString(), aiMode: getAiMode(), tasks, sensorLogs, aiReadings, feedback, growth, thresholds, events });
});

app.get('/api/readings', (_req, res) => {
  const readings = db.prepare(`
    SELECT s.*, c.cell_name FROM sensor_logs s JOIN cells c ON c.id = s.cell_id
    ORDER BY s.measured_at DESC, s.id DESC LIMIT 120
  `).all();
  res.json({ readings });
});

app.get('/api/approvals', (_req, res) => {
  const approvals = db.prepare(`
    SELECT ap.*, ar.disease_name, ar.disease_probability, ar.ai_mode
    FROM approvals ap JOIN ai_readings ar ON ar.id = ap.ai_reading_id
    ORDER BY ap.requested_at DESC, ap.id DESC
  `).all();
  res.json({ approvals });
});

app.post('/api/sensor', (req, res) => {
  const payload = req.body || {};
  const warning = envWarning(getThresholds(), payload);
  const result = db.prepare(`
    INSERT INTO sensor_logs(cell_id, temperature, humidity, sap_amount_ml, growth_rate, env_warning)
    VALUES (?, ?, ?, ?, ?, ?)
  `).run(payload.cell_id, payload.temperature, payload.humidity, payload.sap_amount_ml, payload.growth_rate ?? null, warning);
  db.prepare("INSERT INTO system_events(event_type, cell_id, message) VALUES ('SENSOR', ?, ?)").run(payload.cell_id, `Sensor input saved: ${warning}`);
  res.status(201).json({ sensorLogId: result.lastInsertRowid, envWarning: warning });
});

app.post('/api/ai', (req, res) => {
  const payload = req.body || {};
  const probability = Number(payload.disease_probability || 0);
  const { riskLevel, recommendedTask } = riskFromProbability(probability);
  const tx = db.transaction(() => {
    const ai = db.prepare(`
      INSERT INTO ai_readings(cell_id, sensor_log_id, ai_mode, disease_area, disease_name, disease_probability, risk_level, recommended_task, ai_message)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(payload.cell_id, payload.sensor_log_id ?? null, payload.ai_mode || 'OBSERVE', payload.disease_area || 'LEAF', payload.disease_name || 'NORMAL', probability, riskLevel, recommendedTask, `Cell ${payload.cell_id}: ${payload.disease_name || 'NORMAL'} ${probability}%`);
    let approvalId = null;
    let taskId = null;
    if (probability >= 80) {
      const approval = db.prepare('INSERT INTO approvals(ai_reading_id, cell_id, review_message) VALUES (?, ?, ?)').run(ai.lastInsertRowid, payload.cell_id, `Cell ${payload.cell_id} requires nutrition approval (${probability}%)`);
      approvalId = approval.lastInsertRowid;
      taskId = createRobotTask({ cellId: payload.cell_id, approvalId, taskName: 'NUTRITION', stateMachine: 'WAIT_APPROVAL', robotStatus: 'WAITING_APPROVAL', targetLabel: payload.target_label || 'nutrition_target', payload: { ai_reading_id: ai.lastInsertRowid, probability } });
    } else if (recommendedTask === 'OBSERVE' && getAiMode().enabled) {
      taskId = createRobotTask({ cellId: payload.cell_id, taskName: 'OBSERVE', stateMachine: 'EXECUTE_TASK', robotStatus: 'QUEUED', targetLabel: payload.target_label || 'observe_target', payload: { ai_reading_id: ai.lastInsertRowid, probability } });
    }
    db.prepare('INSERT INTO system_events(event_type, cell_id, message) VALUES (?, ?, ?)').run(probability >= 80 ? 'AI_DANGER' : 'AI_READING', payload.cell_id, `AI reading saved: ${riskLevel}`);
    return { aiReadingId: ai.lastInsertRowid, riskLevel, recommendedTask, approvalId, taskId };
  });
  res.status(201).json(tx());
});

const approveApproval = (approvalId, approvedBy = 'admin') => {
  const approval = db.prepare('SELECT * FROM approvals WHERE id = ?').get(approvalId);
  if (!approval) return null;
  db.prepare("UPDATE approvals SET approval_status = 'APPROVED', approved_by = ?, approved_at = CURRENT_TIMESTAMP WHERE id = ?").run(approvedBy, approvalId);
  db.prepare(`
    UPDATE robot_tasks
    SET state_machine = 'EXECUTE_TASK', control_state = 'RUN', robot_status = 'QUEUED', queue_status = 'queued', started_at = NULL
    WHERE approval_id = ?
  `).run(approvalId);
  db.prepare("INSERT INTO system_events(event_type, cell_id, message) VALUES ('APPROVED', ?, ?)").run(approval.cell_id, `Approval completed: ${approvalId}`);
  return { approvalId, stateMachine: 'EXECUTE_TASK' };
};

app.post('/api/approval/:approvalId/approve', (req, res) => {
  const result = approveApproval(Number(req.params.approvalId), req.query.approved_by || req.body?.approved_by || 'admin');
  if (!result) return res.status(404).json({ error: 'approval not found' });
  return res.json(result);
});

app.post('/api/approval/:approvalId/reject', (req, res) => {
  const approvalId = Number(req.params.approvalId);
  const approvedBy = req.query.approved_by || req.body?.approved_by || 'admin';
  const approval = db.prepare('SELECT * FROM approvals WHERE id = ?').get(approvalId);
  if (!approval) return res.status(404).json({ error: 'approval not found' });
  db.prepare("UPDATE approvals SET approval_status = 'REJECTED', approved_by = ?, approved_at = CURRENT_TIMESTAMP WHERE id = ?").run(approvedBy, approvalId);
  db.prepare("UPDATE robot_tasks SET state_machine = 'COMPLETE', control_state = 'STOP', robot_status = 'REJECTED', queue_status = 'cancelled' WHERE approval_id = ?").run(approvalId);
  db.prepare("INSERT INTO system_events(event_type, cell_id, message) VALUES ('REJECTED', ?, ?)").run(approval.cell_id, `Approval rejected: ${approvalId}`);
  return res.json({ approvalId, stateMachine: 'COMPLETE' });
});

app.post('/api/robot/request', (req, res) => {
  const payload = req.body || {};
  const cellId = Number(payload.cell_id || payload.cellId || 1);
  const taskName = normalizeTask(payload.task_name || payload.task || payload.execute_task || 'OBSERVE');
  const taskId = createRobotTask({
    cellId,
    taskName,
    stateMachine: 'EXECUTE_TASK',
    robotStatus: 'QUEUED',
    moveSign: payload.move_sign || payload.moveSign || 'STOP',
    targetLabel: payload.target_label || payload.targetLabel || null,
    robotId: payload.robot_id || payload.robotId || defaultRobotId,
    payload: payload.payload || {}
  });
  db.prepare("INSERT INTO system_events(event_type, cell_id, message) VALUES ('ROBOT_REQUEST', ?, ?)").run(cellId, `Manual robot task queued: ${taskName} #${taskId}`);
  res.status(201).json(taskRowToApi(db.prepare('SELECT * FROM robot_tasks WHERE id = ?').get(taskId)));
});

const claimNextTask = (robotId = defaultRobotId) => {
  const task = db.prepare(`
    SELECT * FROM robot_tasks
    WHERE state_machine = 'EXECUTE_TASK'
      AND control_state = 'RUN'
      AND queue_status IN ('queued', 'sent')
      AND (robot_id = ? OR robot_id IS NULL)
    ORDER BY created_at ASC, id ASC
    LIMIT 1
  `).get(robotId);
  if (!task) return null;
  if (task.queue_status === 'queued') {
    db.prepare(`
      UPDATE robot_tasks
      SET queue_status = 'sent', robot_status = 'SENT_TO_ROBOT', sent_at = CURRENT_TIMESTAMP, started_at = COALESCE(started_at, CURRENT_TIMESTAMP)
      WHERE id = ?
    `).run(task.id);
  }
  return taskRowToApi(db.prepare('SELECT * FROM robot_tasks WHERE id = ?').get(task.id));
};

app.get('/api/robot/next', (req, res) => {
  res.json(claimNextTask(req.query.robot_id || defaultRobotId));
});

app.get('/api/robot/next-task', (req, res) => {
  const task = claimNextTask(req.query.robot_id || defaultRobotId);
  res.json({ task });
});

app.post('/api/robot/response', (req, res) => {
  const payload = req.body || {};
  const taskId = Number(payload.task_id || payload.taskId);
  const task = db.prepare('SELECT * FROM robot_tasks WHERE id = ?').get(taskId);
  if (!task) return res.status(404).json({ error: 'task not found' });
  const completion = String(payload.completion_sign || payload.completionSign || 'RUNNING').toUpperCase();
  const progressRate = completion === 'DONE' ? 100 : completion === 'FAILED' ? Number(payload.progress_rate || 0) : Number(payload.progress_rate || task.progress_rate || 50);
  const nextState = completion === 'DONE' || completion === 'FAILED' ? 'COMPLETE' : 'REPORT_STATUS';
  const queueStatus = completion === 'DONE' ? 'done' : completion === 'FAILED' ? 'failed' : 'running';
  const robotStatus = payload.message || payload.robot_status || completion;
  const responsePayload = JSON.stringify(payload.payload || payload);

  const tx = db.transaction(() => {
    db.prepare(`
      INSERT INTO robot_feedback(task_id, cell_id, progress_rate, temperature, humidity, sap_amount_ml, robot_status, completion_sign, response_payload)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(taskId, task.cell_id, progressRate, payload.temperature ?? null, payload.humidity ?? null, payload.sap_amount_ml ?? null, robotStatus, completion, responsePayload);
    db.prepare(`
      UPDATE robot_tasks
      SET progress_rate = ?, robot_status = ?, state_machine = ?, queue_status = ?, last_response_payload = ?, completed_at = CASE WHEN ? = 'COMPLETE' THEN CURRENT_TIMESTAMP ELSE completed_at END
      WHERE id = ?
    `).run(progressRate, robotStatus, nextState, queueStatus, responsePayload, nextState, taskId);
    if (nextState === 'COMPLETE' && completion === 'DONE') {
      db.prepare(`
        INSERT INTO growth_records(cell_id, replant_date, avg_growth_rate, note)
        VALUES (?, date('now'), (SELECT AVG(growth_rate) FROM sensor_logs WHERE cell_id = ? AND growth_rate IS NOT NULL), 'Robot task completed')
      `).run(task.cell_id, task.cell_id);
    }
    db.prepare("INSERT INTO system_events(event_type, cell_id, message) VALUES ('ROBOT_RESPONSE', ?, ?)").run(task.cell_id, `Robot response for task ${taskId}: ${completion}`);
  });
  tx();
  res.json({ taskId, stateMachine: nextState, queueStatus });
});

app.post('/api/robot/status', (req, res) => {
  const payload = req.body || {};
  const taskId = Number(payload.task_id || payload.taskId);
  const task = db.prepare('SELECT * FROM robot_tasks WHERE id = ?').get(taskId);
  if (!task) return res.status(404).json({ error: 'task not found' });
  const progressRate = Number(payload.progress_rate || 0);
  const completion = progressRate >= 100 ? 'DONE' : 'RUNNING';
  const nextState = completion === 'DONE' ? 'COMPLETE' : 'REPORT_STATUS';
  const queueStatus = completion === 'DONE' ? 'done' : 'running';
  const robotStatus = payload.robot_status || 'RUNNING';
  const responsePayload = JSON.stringify(payload);
  const tx = db.transaction(() => {
    db.prepare(`
      INSERT INTO robot_feedback(task_id, cell_id, progress_rate, temperature, humidity, sap_amount_ml, robot_status, completion_sign, response_payload)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(taskId, task.cell_id, progressRate, payload.temperature ?? null, payload.humidity ?? null, payload.sap_amount_ml ?? null, robotStatus, completion, responsePayload);
    db.prepare(`
      UPDATE robot_tasks
      SET progress_rate = ?, robot_status = ?, state_machine = ?, queue_status = ?, last_response_payload = ?, completed_at = CASE WHEN ? = 'COMPLETE' THEN CURRENT_TIMESTAMP ELSE completed_at END
      WHERE id = ?
    `).run(progressRate, robotStatus, nextState, queueStatus, responsePayload, nextState, taskId);
  });
  tx();
  return res.json({ taskId, stateMachine: nextState, queueStatus });
});

app.post('/api/vision/event', (req, res) => {
  const payload = req.body || {};
  const result = db.prepare(`
    INSERT INTO vision_events(robot_id, cell_id, source, label, confidence, x_center, y_center, width, height, payload)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    payload.robot_id || defaultRobotId,
    payload.cell_id ?? null,
    payload.source || 'jetson-csi-camera',
    payload.label ?? null,
    payload.confidence ?? null,
    payload.x_center ?? null,
    payload.y_center ?? null,
    payload.width ?? null,
    payload.height ?? null,
    JSON.stringify(payload.payload || payload)
  );
  res.status(201).json({ id: result.lastInsertRowid });
});

app.post('/api/randomize', (_req, res) => {
  const tx = db.transaction(() => {
    for (let cellId = 1; cellId <= 4; cellId += 1) {
      const temperature = randomFloat(18, 36);
      const humidity = randomInt(42, 92);
      const sapAmount = randomFloat(80, 740);
      const growthRate = randomInt(35, 98);
      const warning = envWarning(getThresholds(), { temperature, humidity, sap_amount_ml: sapAmount });
      const sensor = db.prepare('INSERT INTO sensor_logs(cell_id, temperature, humidity, sap_amount_ml, growth_rate, env_warning) VALUES (?, ?, ?, ?, ?, ?)').run(cellId, temperature, humidity, sapAmount, growthRate, warning);
      const probability = randomInt(0, 100);
      const { riskLevel, recommendedTask } = riskFromProbability(probability);
      db.prepare(`
        INSERT INTO ai_readings(cell_id, sensor_log_id, ai_mode, disease_area, disease_name, disease_probability, risk_level, recommended_task, ai_message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).run(cellId, sensor.lastInsertRowid, probability >= 80 ? 'NUTRITION' : 'OBSERVE', pick(['LEAF', 'ROOT', 'STEM', 'FRUIT']), probability >= 50 ? 'growth_issue' : 'NORMAL', probability, riskLevel, recommendedTask, `Randomized reading ${probability}%`);
    }
  });
  tx();
  res.json(buildDashboard());
});

app.listen(port, () => {
  console.log(`Greenhouse web/API: http://localhost:${port}`);
});

