/* ═══════════════════════════════════════════════════════════════════
   BATA Tablet Monitor — MQTT WebSocket direct connection
   Broker: ws://192.168.0.50:9001
   Topic:  BAGO/M{N}/Status  (subscribe)
           BAGO/M{N}/Cmd     (publish)
   ═══════════════════════════════════════════════════════════════════ */

// ── 설정 ─────────────────────────────────────────────────────────────
// LAN이면 Mosquitto 직접 연결, 외부(터널)이면 FastAPI /mqtt-ws 프록시 경유
const _LAN_HOSTS = ['192.168.0.50', '127.0.0.1', 'localhost'];
const MQTT_BROKER = _LAN_HOSTS.includes(window.location.hostname)
    ? 'ws://192.168.0.50:9001'
    : (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/mqtt-ws';
const TOPIC_STATUS  = n => `BAGO/M${String(n).padStart(2,'0')}/Status`;
const TOPIC_CMD     = n => `BAGO/M${String(n).padStart(2,'0')}/Cmd`;

// ── 전역 상태 ─────────────────────────────────────────────────────────
let selectedMachine = 2;
let appliedMachine  = 2;
let mqttClient      = null;
let msgCount        = 0;
let lastPayload     = null;
let clockTimer      = null;

// SVG Arc 파라미터 (기존 app.js 와 동일)
const ARC_CX = 80, ARC_CY = 88, ARC_R = 76;   // 태블릿용 radius 업스케일
const ARC_START = 140, ARC_SPAN = 260;

// ── 유틸리티 ──────────────────────────────────────────────────────────
function fmtMachine(n) { return `M${String(n).padStart(2,'0')}`; }

function fmtHHMMSS(sec) {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

function fmtRelTime(isoStr) {
  if (!isoStr) return '--';
  try {
    const ago = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000);
    if (ago < 60)    return `${ago}s ago`;
    if (ago < 3600)  return `${Math.floor(ago/60)}m ago`;
    if (ago < 86400) return `${Math.floor(ago/3600)}h ago`;
    return new Date(isoStr).toLocaleDateString();
  } catch { return '--'; }
}

// ── SVG Arc 게이지 (기존 로직 재활용, radius 조정) ───────────────────
function tempColor(pct) {
  if (pct < 0.25) return '#4a90d9';
  if (pct < 0.50) return '#35c98f';
  if (pct < 0.75) return '#ffd700';
  return '#ff6b6b';
}

function polarXY(deg) {
  const rad = deg * Math.PI / 180;
  return { x: ARC_CX + ARC_R * Math.cos(rad), y: ARC_CY + ARC_R * Math.sin(rad) };
}

function arcPath(s, e) {
  const sp = polarXY(s), ep = polarXY(e);
  const large = (e - s) > 180 ? 1 : 0;
  return `M ${sp.x.toFixed(1)} ${sp.y.toFixed(1)} A ${ARC_R} ${ARC_R} 0 ${large} 1 ${ep.x.toFixed(1)} ${ep.y.toFixed(1)}`;
}

function initArcGauges() {
  for (let i = 0; i < 4; i++) {
    const bg = document.getElementById(`g${i}bg`);
    if (bg) bg.setAttribute('d', arcPath(ARC_START, ARC_START + ARC_SPAN));
  }
}

function updateGauge(idx, value, maxVal = 120) {
  const pct = Math.max(0, Math.min(1, value / maxVal));
  const ind = document.getElementById(`g${idx}ind`);
  if (!ind) return;
  if (value <= 0) {
    ind.setAttribute('d', '');
  } else {
    ind.setAttribute('d', arcPath(ARC_START, ARC_START + pct * ARC_SPAN));
  }
  ind.setAttribute('stroke', tempColor(pct));
  const valEl = document.getElementById(`g${idx}val`);
  if (valEl) valEl.textContent = value.toFixed(1) + '°';
}

// ── 머신 UI 업데이트 ─────────────────────────────────────────────────
function updateMachineUI() {
  const fmt    = fmtMachine(selectedMachine);
  const appFmt = fmtMachine(appliedMachine);
  document.getElementById('machineNo').textContent    = appFmt;
  document.getElementById('machineStatus').textContent = selectedMachine === appliedMachine ? 'APPLIED' : 'PENDING';
  document.getElementById('navMachineNo').textContent  = fmt;
  document.getElementById('topicLabel').textContent    = TOPIC_STATUS(appliedMachine);
}

function prevMachine() { selectedMachine = Math.max(1, selectedMachine - 1); updateMachineUI(); }
function nextMachine() { selectedMachine = Math.min(99, selectedMachine + 1); updateMachineUI(); }

function applyMachine() {
  if (mqttClient && mqttClient.connected) {
    mqttClient.unsubscribe(TOPIC_STATUS(appliedMachine));
    appliedMachine = selectedMachine;
    mqttClient.subscribe(TOPIC_STATUS(appliedMachine));
  } else {
    appliedMachine = selectedMachine;
  }
  msgCount = 0;
  updateMachineUI();
  document.getElementById('totalLabel').textContent = '0';
  clearDashboard();
}

// ── MQTT 연결 ─────────────────────────────────────────────────────────
function connectMQTT() {
  const dot = document.getElementById('mqttDot');

  mqttClient = mqtt.connect(MQTT_BROKER, {
    clientId: 'bata_tablet_' + Math.random().toString(16).slice(2, 8),
    keepalive: 30,
    reconnectPeriod: 3000,
    connectTimeout: 8000,
  });

  mqttClient.on('connect', () => {
    dot.className = 'mqtt-dot connected';
    mqttClient.subscribe(TOPIC_STATUS(appliedMachine), { qos: 1 });
  });

  mqttClient.on('reconnect', () => { dot.className = 'mqtt-dot reconnecting'; });
  mqttClient.on('offline',   () => { dot.className = 'mqtt-dot'; });
  mqttClient.on('error',     () => { dot.className = 'mqtt-dot'; });

  mqttClient.on('message', (topic, payload) => {
    try {
      const s = JSON.parse(payload.toString());
      lastPayload = s;
      msgCount++;
      renderDashboard(s);
    } catch { /* 파싱 실패 무시 */ }
  });
}

// ── 명령 발행 ─────────────────────────────────────────────────────────
function publish(rawJson, label = '') {
  if (!mqttClient || !mqttClient.connected) {
    showResult('✗ Not connected', true);
    return;
  }
  mqttClient.publish(TOPIC_CMD(appliedMachine), rawJson, { qos: 1 }, err => {
    showResult(err ? `✗ ${err.message}` : `✓ Sent ${label}`, !!err);
  });
}

function showResult(msg, isErr = false) {
  const el = document.getElementById('publishResult');
  if (!el) return;
  el.textContent = msg;
  el.className = 'publish-result' + (isErr ? ' err' : '');
  setTimeout(() => { el.textContent = ''; el.className = 'publish-result'; }, 3000);
}

// ── 대시보드 렌더링 (기존 updateOperationTab 로직 재작성) ────────────
function clearDashboard() {
  ['sRecipe','sState','sElapsed','sRemain','sEnd','sFet','sRelay','sError',
   'g0val','g1val','g2val','g3val','amb0val','amb1val','air0val','air1val',
   'mq2val','mq7val','mq135val','ignT1Val','ignT2Val','ignQueue','bdgRtc','bdgBuild'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = '--';
  });
  for (let i = 0; i < 4; i++) updateGauge(i, 0);
}

function renderDashboard(s) {
  const now = new Date().toISOString();

  // ── 상태 패널 ──
  setText('sRecipe',  s.name ?? 'IDLE');
  setText('sState',   `${s.currentState ?? 0} · ${s.name ?? ''}`);
  setText('sElapsed', fmtHHMMSS(Math.floor(s.stateTimeInSeconds ?? 0)));
  const h = Math.floor((s.remain ?? 0) / 60);
  const m = (s.remain ?? 0) % 60;
  setText('sRemain', s.remain ? `${h}h ${m}m` : '0m');
  setText('sEnd',    s.end || '--');

  // FET / RELAY
  const fetOn   = (s.FET   || []).filter(v => v).length;
  const relayOn = (s.relay || []).filter(v => v).length;
  setText('sFet',   `${fetOn} / ${(s.FET   || []).length}`);
  setText('sRelay', `${relayOn} / ${(s.relay || []).length}`);
  renderDots('fetDots',   s.FET   || []);
  renderDots('relayDots', s.relay || []);

  // 점화 (ignition)
  const igEnabled = s.ig_st != null ? s.ig_st !== 0 : false;
  const igName    = s.ig_nm ?? 'OFF';
  const chip = document.getElementById('ignChip');
  if (chip) {
    chip.textContent  = igEnabled ? 'Ign ON' : 'Ign OFF';
    chip.className    = 'ign-enable-chip' + (igEnabled ? ' on' : '');
  }
  setText('ignState', `⏻ ${igName}`);
  const t1 = (s.TC || [])[0] ?? 0;
  const t2 = (s.TC || [])[1] ?? 0;
  setBar('ignT1Bar', t1, 1100); setText('ignT1Val', `${t1.toFixed(1)}°C`);
  setBar('ignT2Bar', t2, 1100); setText('ignT2Val', `${t2.toFixed(1)}°C`);
  setText('ignQueue', `Queue ↑ ${s.ig_on ?? 0}  ↓ ${s.ig_off ?? 0}`);

  // Error
  const errCode = (s.ERR_HIST_STATE || []).some(v => v) ? 'ERR' : 'OK';
  setText('sError', errCode);
  const errEl = document.getElementById('sError');
  if (errEl) errEl.style.color = errCode === 'OK' ? '#77ffa7' : '#ff6b6b';

  // ── 게이지 (temp[] TH1~TH4) ──
  const temp = s.temp || [];
  for (let i = 0; i < 4; i++) updateGauge(i, temp[i] ?? 0);

  // Ambient (TH5/TH6) 수직 바
  for (let i = 0; i < 2; i++) {
    const v = temp[4 + i] ?? 0;
    setBarV(`amb${i}bar`, v, 120);
    setText(`amb${i}val`, `${v.toFixed(1)}°C`);
  }

  // TC3/TC4 수평 바 (Air temps)
  const tc = s.TC || [];
  for (let i = 0; i < 2; i++) {
    const v = tc[2 + i] ?? 0;
    setBar(`air${i}bar`, v, 900);
    setText(`air${i}val`, `${v.toFixed(1)}°C`);
  }

  // AIR QUALITY
  const aq = s.AIR_CONDITION || {};
  const mq2   = aq.MQ2   ?? 0;
  const mq7   = aq.MQ7   ?? 0;
  const mq135 = aq.MQ135 ?? 0;
  setBar('mq2bar',   mq2,   1000); setText('mq2val',   `${mq2.toFixed(0)} ppm`);
  setBar('mq7bar',   mq7,   500);  setText('mq7val',   `${mq7.toFixed(0)} ppm`);
  setBar('mq135bar', mq135, 500);  setText('mq135val', `${mq135.toFixed(0)} ppm`);

  // 상단 배지
  setText('lastRxLabel', fmtRelTime(now));
  setText('totalLabel',  String(msgCount));
  setText('bdgRtc',   s.rtc_time ?? '--');
  setText('bdgBuild', s.BUILD_INFO?.version ?? '--');
}

// ── 헬퍼 ─────────────────────────────────────────────────────────────
function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function setBar(id, val, max) {
  const el = document.getElementById(id);
  if (el) el.style.width = Math.min(100, (val / max) * 100) + '%';
}

function setBarV(id, val, max) {
  const el = document.getElementById(id);
  if (el) el.style.height = Math.min(100, (val / max) * 100) + '%';
}

function renderDots(containerId, arr) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = arr.map((v, i) =>
    `<span class="io-dot ${v ? 'on' : ''}" title="${containerId.includes('fet') ? 'FET' : 'RELAY'} ${i}">${i}</span>`
  ).join('');
}

// ── 시계 ─────────────────────────────────────────────────────────────
function updateClock() {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2,'0');
  const mm = String(now.getMinutes()).padStart(2,'0');
  setText('clock', `${hh}:${mm}`);
}

// ── 초기화 & 이벤트 바인딩 ───────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initArcGauges();
  updateMachineUI();
  updateClock();
  clockTimer = setInterval(updateClock, 1000);

  // 머신 네비
  document.getElementById('prevMachineBtn')?.addEventListener('click', prevMachine);
  document.getElementById('nextMachineBtn')?.addEventListener('click', nextMachine);
  document.getElementById('setMachineBtn')?.addEventListener('click', applyMachine);

  // 하단 버튼
  document.getElementById('runBtn')?.addEventListener('click', () => {
    document.getElementById('runPopup').style.display = 'flex';
  });
  document.getElementById('stopBtn')?.addEventListener('click', () => {
    document.getElementById('stopPopup').style.display = 'flex';
  });
  document.getElementById('sleepBtn')?.addEventListener('click', () => {
    publish('{"run":[3,0,0]}', 'SLEEP');
  });

  // RUN 팝업
  document.getElementById('runPopupCancel')?.addEventListener('click', () => {
    document.getElementById('runPopup').style.display = 'none';
  });
  document.querySelectorAll('.recipe-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const n = btn.getAttribute('data-recipe');
      publish(`{"run":[1,${n},0]}`, `Recipe #${n}`);
      document.getElementById('runPopup').style.display = 'none';
    });
  });

  // STOP 팝업
  document.getElementById('stopNo')?.addEventListener('click', () => {
    document.getElementById('stopPopup').style.display = 'none';
  });
  document.getElementById('stopYes')?.addEventListener('click', () => {
    publish('{"run":[2,0,0]}', 'STOP');
    document.getElementById('stopPopup').style.display = 'none';
  });

  // MQTT 연결
  connectMQTT();
});
