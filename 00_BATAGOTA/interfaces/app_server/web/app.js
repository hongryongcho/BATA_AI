/*  ═══════════════════════════════════════════════════════════════════════════
    BATAGOTA MQTT App Server — HMI 3열 레이아웃 UI Logic
    3열: 왼쪽패널 | 중앙콘텐츠 | 우측버튼 / 화면: Operation/Status/Setup/Review
    ═══════════════════════════════════════════════════════════════════════════ */

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 전역 상태
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
let selectedMachine = 2;  // 현재 선택 머신 (UI 표시)
let appliedMachine = 2;   // 구독 중인 머신 (데이터 조회/발행)
let currentScreen = 0;    // 현재 활성 화면 (0=Op, 1=Status, 2=Setup, 3=Review)
let pollingInterval = null;
let clockInterval = null;

const SCREEN_NAMES = ['Operation', 'System Status', 'Setup / CMD', 'Review'];

// SVG Arc 게이지 파라미터 (LVGL과 일치)
const ARC_CX = 80, ARC_CY = 88, ARC_R = 62;
const ARC_START = 140, ARC_SPAN = 260;

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 유틸리티
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
function fmtMachineNo(n) { return `M${String(n).padStart(2, '0')}`; }

function fmtHHMMSS(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function fmtRelTime(isoStr) {
  if (!isoStr) return '-/-';
  try {
    const d = new Date(isoStr);
    const ago = Math.floor((Date.now() - d.getTime()) / 1000);
    if (ago < 60) return `${ago}s ago`;
    if (ago < 3600) return `${Math.floor(ago / 60)}m ago`;
    if (ago < 86400) return `${Math.floor(ago / 3600)}h ago`;
    return d.toLocaleDateString();
  } catch { return '-/-'; }
}

function tempColor(pct) {
  // 0% blue → 25% cyan → 50% green → 75% yellow → 100% red
  if (pct < 0.25) return '#4a90d9';
  if (pct < 0.50) return '#35c98f';
  if (pct < 0.75) return '#ffd700';
  return '#ff6b6b';
}

function polarToXY(angleDeg) {
  const rad = angleDeg * Math.PI / 180;
  return {
    x: ARC_CX + ARC_R * Math.cos(rad),
    y: ARC_CY + ARC_R * Math.sin(rad)
  };
}

function arcPath(startDeg, endDeg) {
  const s = polarToXY(startDeg);
  const e = polarToXY(endDeg);
  const span = endDeg - startDeg;
  const large = span > 180 ? 1 : 0;
  return `M ${s.x.toFixed(1)} ${s.y.toFixed(1)} A ${ARC_R} ${ARC_R} 0 ${large} 1 ${e.x.toFixed(1)} ${e.y.toFixed(1)}`;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// API
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
async function apiCall(path, options = {}) {
  try {
    const res = await fetch(path, options);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (e) {
    console.error(e);
    return null;
  }
}

async function publishRaw(machineNo, rawJson) {
  const res = await apiCall(`/api/machine/${machineNo}/publish`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ raw_json: rawJson })
  });
  return res;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// UI 업데이트 — SVG Arc 게이지
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
function initArcGauges() {
  for (let i = 0; i < 4; i++) {
    const bgId = 'g' + i + 'bg';
    const el = document.getElementById(bgId);
    if (el) el.setAttribute('d', arcPath(ARC_START, ARC_START + ARC_SPAN));
  }
}

function updateGauge(idx, value, maxVal = 120) {
  const pct = Math.max(0, Math.min(1, value / maxVal));
  const endDeg = ARC_START + pct * ARC_SPAN;
  const ind = document.getElementById('g' + idx + 'ind');
  
  if (value <= 0) {
    ind.setAttribute('d', '');
  } else {
    const path = arcPath(ARC_START, endDeg);
    ind.setAttribute('d', path);
  }
  
  const color = tempColor(pct);
  ind.setAttribute('stroke', color);
  
  const valEl = document.getElementById('g' + idx + 'val');
  if (valEl) valEl.textContent = value.toFixed(1) + '°';
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// UI 업데이트 — 화면 전환 (3열 레이아웃)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
function switchScreen(idx) {
  if (idx === currentScreen) return;
  
  // 화면 콘텐츠
  document.querySelectorAll('.screen').forEach(el => {
    el.classList.remove('screen-active');
  });
  document.getElementById('screen-' + idx)?.classList.add('screen-active');
  
  // 네비게이션 버튼
  document.querySelectorAll('.nav-btn').forEach(el => {
    el.classList.remove('active');
  });
  document.querySelectorAll('.nav-btn')[idx]?.classList.add('active');
  
  currentScreen = idx;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// UI 업데이트 — 머신 선택/적용
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
function updateMachineDisplay() {
  const fmt = fmtMachineNo(selectedMachine);
  const appliedFmt = fmtMachineNo(appliedMachine);
  
  // 왼쪽 패널: 머신번호
  const leftMachineNo = document.getElementById('leftMachineNo');
  if (leftMachineNo) {
    leftMachineNo.textContent = fmt;
  }
  
  // 왼쪽 패널: 상태 (APPLIED/PENDING)
  const leftMachineStatus = document.getElementById('leftMachineStatus');
  if (leftMachineStatus) {
    leftMachineStatus.textContent = selectedMachine === appliedMachine ? 'APPLIED' : 'PENDING';
  }
  
  // Operation 화면 - 머신 정보 업데이트
  ['opMqttNo', 'opBottomMNo'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = appliedFmt;
  });
  
  // MQTT 토픽 표시 업데이트
  const topicStr = `BAGO/${appliedFmt}/Status`;
  ['stTopic', 'opTopic', 'opMqttTopic'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = topicStr;
  });
}

function prevMachine() {
  selectedMachine = Math.max(1, selectedMachine - 1);
  updateMachineDisplay();
}

function nextMachine() {
  selectedMachine = Math.min(99, selectedMachine + 1);
  updateMachineDisplay();
}

function applyMachine() {
  appliedMachine = selectedMachine;
  updateMachineDisplay();
  // 즉시 새로운 머신 데이터 조회
  pollOnce();
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Operation 탭 업데이트
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
function updateOperationTab(data) {
  const latest = data.latest;
  if (!latest || !data.has_data) {
    // 데이터 없음 상태
    document.getElementById('opRecipeName').textContent = '-/-';
    document.getElementById('opState').textContent = '-/-';
    document.getElementById('opStep').textContent = '-/-';
    document.getElementById('opElapsed').textContent = '00:00:00';
    document.getElementById('opRemain').textContent = '-/-';
    document.getElementById('opEnd').textContent = '-/-';
    document.getElementById('opFet').textContent = '-/-';
    document.getElementById('opRelay').textContent = '-/-';
    document.getElementById('opError').textContent = '-/-';
    document.getElementById('opLastRx').textContent = '-/-';
    for (let i = 0; i < 4; i++) updateGauge(i, 0);
    return;
  }
  
  let s;
  try {
    s = JSON.parse(latest.payload);
  } catch {
    return;
  }
  
  // Recipe / State / Step
  document.getElementById('opRecipeName').textContent = s.name ?? 'IDLE';
  document.getElementById('opState').textContent = s.state ?? 0;
  document.getElementById('opStep').textContent = s.name ?? '-/-';
  
  // Time
  if (s.time != null) {
    const sec = Math.floor(s.time / 1000);
    document.getElementById('opElapsed').textContent = fmtHHMMSS(sec);
  }
  if (s.remain != null) {
    const h = Math.floor(s.remain / 60);
    const m = s.remain % 60;
    document.getElementById('opRemain').textContent = `${h}h ${m}m`;
  }
  document.getElementById('opEnd').textContent = s.end ?? '-/-';
  
  // FET / RELAY
  if (s.fet) {
    const on = (s.fet || []).filter(v => v).length;
    document.getElementById('opFet').textContent = `${on} / ${s.fet.length}`;
  }
  if (s.relay) {
    const on = (s.relay || []).filter(v => v).length;
    document.getElementById('opRelay').textContent = `${on} / ${s.relay.length}`;
  }
  
  // Error
  const errCode = s.err_code ?? 0;
  const errName = s.err_name ?? '';
  document.getElementById('opError').textContent = `${errCode} (${errName || 'OK'})`;
  
  // Last RX
  document.getElementById('opLastRx').textContent = fmtRelTime(latest.ts_utc);
  
  // 온도 게이지
  if (s.temp && Array.isArray(s.temp)) {
    for (let i = 0; i < 4; i++) {
      updateGauge(i, s.temp[i] ?? 0);
    }
    
    // Ambient (TH5/TH6) 수직 바
    for (let i = 0; i < 2; i++) {
      const v = s.temp[4 + i] ?? 0;
      const pct = Math.min(100, (v / 120) * 100);
      const barEl = document.getElementById('amb' + i + 'bar');
      const valEl = document.getElementById('amb' + i + 'val');
      if (barEl) barEl.style.height = pct + '%';
      if (valEl) valEl.textContent = v.toFixed(1) + '°C';
    }
  }
  
  // TC (Air temps) 수평 바
  if (s.tc && Array.isArray(s.tc)) {
    const maxAir = 900;
    for (let i = 0; i < 2; i++) {
      const v = s.tc[2 + i] ?? 0;
      const pct = Math.min(100, (v / maxAir) * 100);
      const barEl = document.getElementById('air' + i + 'bar');
      const valEl = document.getElementById('air' + i + 'val');
      if (barEl) barEl.style.width = pct + '%';
      if (valEl) valEl.textContent = v.toFixed(1) + '°C';
    }
    
    // Ignition T1/T2 (tc[0], tc[1])
    const t1 = s.tc[0] ?? 0;
    const t2 = s.tc[1] ?? 0;
    const ign0el = document.getElementById('ign0val');
    const ign1el = document.getElementById('ign1val');
    if (ign0el) ign0el.textContent = `${t1.toFixed(1)}/250°C`;
    if (ign1el) ign1el.textContent = `${t2.toFixed(1)}/150°C`;
    
    const ign0b = document.getElementById('ign0bar');
    const ign1b = document.getElementById('ign1bar');
    if (ign0b) ign0b.style.width = Math.min(100, (t1 / 1100) * 100) + '%';
    if (ign1b) ign1b.style.width = Math.min(100, (t2 / 1100) * 100) + '%';
  }
  
  // Ignition State
  if (s.ignition) {
    const ign = s.ignition;
    const enabled = ign.enabled ?? false;
    const chip = document.getElementById('ignEnableChip');
    if (chip) {
      chip.textContent = enabled ? 'Ign ON' : 'Ign OFF';
      chip.className = 'ign-enable-chip' + (enabled ? ' on' : '');
    }
    
    const state = ign.state ?? 'IDLE';
    const stateText = document.getElementById('ignStateText');
    if (stateText) stateText.textContent = `⏻ ${state}`;
    
    const pill = document.getElementById('ignStatePill');
    if (pill) {
      const colors = {
        'IDLE': '#223556',
        'IGNITING': '#3d1a0a',
        'FLAME': '#3a0d1c',
        'COOLDOWN': '#0d2a1e'
      };
      pill.style.background = colors[state] ?? '#223556';
    }
    
    const queue = document.getElementById('ignQueue');
    if (queue) {
      queue.textContent = `↺ Queue ↑ ${ign.queue_on ?? 0}  ↓ ${ign.queue_off ?? 0}`;
    }
  }
  
  // 통계 배지
  document.getElementById('opTotalBadge').textContent = `Total: ${data.total}`;
  document.getElementById('opHourBadge').textContent = `Last 1h: ${data.last_hour}`;
  document.getElementById('opLastTsBadge').textContent = `Last: ${fmtRelTime(latest.ts_utc)}`;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Status 탭 업데이트
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
function updateStatusTab(data) {
  document.getElementById('stTotal').textContent = data.total;
  document.getElementById('stLastHour').textContent = data.last_hour;
  document.getElementById('stLastTs').textContent = data.latest ? fmtRelTime(data.latest.ts_utc) : '-/-';
  
  if (!data.latest || !data.has_data) {
    document.getElementById('rawJsonView').textContent = '(No data)';
    document.getElementById('recentBody').innerHTML = '<tr class="no-data-row"><td colspan="3">No data</td></tr>';
    return;
  }
  
  const payload = data.latest.payload;
  document.getElementById('rawJsonView').textContent = payload;
  
  // JSON 파싱
  try {
    const obj = JSON.parse(payload);
    const grid = document.getElementById('parsedGrid');
    if (grid) {
      grid.innerHTML = '';
      for (const [key, val] of Object.entries(obj)) {
        const item = document.createElement('div');
        item.className = 'parsed-item';
        item.innerHTML = `<span class="p-key">${key}</span><span class="p-val">${JSON.stringify(val)}</span>`;
        grid.appendChild(item);
      }
    }
  } catch {}
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 폴링
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
async function pollOnce() {
  const data = await apiCall(`/api/machine/${appliedMachine}/overview`);
  if (!data) return;
  
  if (currentScreen === 0) updateOperationTab(data);
  if (currentScreen === 1) updateStatusTab(data);
}

function startPolling() {
  pollOnce();
  pollingInterval = setInterval(pollOnce, 5000);
}

function stopPolling() {
  if (pollingInterval) clearInterval(pollingInterval);
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 헤더 시계
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
function updateClock() {
  const clock = document.getElementById('leftClock');
  if (clock) {
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, '0');
    const mm = String(now.getMinutes()).padStart(2, '0');
    clock.textContent = `${hh}:${mm}`;
  }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// MQTT Publish 버튼
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
async function handlePublish(rawJson, cmdType = '') {
  if (!rawJson) return;
  const res = await publishRaw(appliedMachine, rawJson);
  
  const resultEl = document.getElementById('opPublishResult');
  if (resultEl) {
    if (res && res.payload_sent) {
      resultEl.textContent = `✓ Sent ${cmdType}`;
      resultEl.classList.remove('err');
      setTimeout(() => { resultEl.textContent = ''; }, 3000);
    } else {
      resultEl.textContent = '✗ Failed';
      resultEl.classList.add('err');
    }
  }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 팝업 핸들러
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
function showRunPopup() {
  const popup = document.getElementById('runPopup');
  if (popup) popup.style.display = 'flex';
}

function hideRunPopup() {
  const popup = document.getElementById('runPopup');
  if (popup) popup.style.display = 'none';
}

async function confirmStop() {
  await handlePublish('{"run":[2,0,0]}', 'STOP');
  hideStopPopup();
}

function showStopPopup() {
  const popup = document.getElementById('stopPopup');
  if (popup) popup.style.display = 'flex';
}

function hideStopPopup() {
  const popup = document.getElementById('stopPopup');
  if (popup) popup.style.display = 'none';
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 초기화 & 이벤트 바인딩
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
document.addEventListener('DOMContentLoaded', () => {
  // 헤더 머신 네비
  document.getElementById('prevMachineBtn')?.addEventListener('click', prevMachine);
  document.getElementById('nextMachineBtn')?.addEventListener('click', nextMachine);
  document.getElementById('setMachineBtn')?.addEventListener('click', applyMachine);
  
  // 왼쪽 패널 네비게이션 버튼 (화면 전환)
  document.querySelectorAll('.nav-btn').forEach((btn, i) => {
    btn.addEventListener('click', () => switchScreen(i));
  });
  
  // 하단 버튼
  document.getElementById('runBtn')?.addEventListener('click', showRunPopup);
  document.getElementById('stopBtn')?.addEventListener('click', showStopPopup);
  document.getElementById('sleepBtn')?.addEventListener('click', () => {
    handlePublish('{"run":[3,0,0]}', 'SLEEP');
  });
  
  // 팝업
  document.getElementById('runPopupCancel')?.addEventListener('click', hideRunPopup);
  document.getElementById('stopPopupNo')?.addEventListener('click', hideStopPopup);
  document.getElementById('stopPopupYes')?.addEventListener('click', confirmStop);
  
  // 레시피 버튼
  document.querySelectorAll('[data-recipe]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const recipeNo = btn.getAttribute('data-recipe');
      await handlePublish(`{"run":[1,${recipeNo},0]}`, `RUN Recipe#${recipeNo}`);
      hideRunPopup();
    });
  });
  
  // Setup 빠른 명령
  document.querySelectorAll('[data-raw]').forEach(btn => {
    btn.addEventListener('click', () => {
      const raw = btn.getAttribute('data-raw');
      handlePublish(raw, btn.textContent.trim());
    });
  });
  
  // Setup JSON 퍼블리시
  document.getElementById('jsonPublishBtn')?.addEventListener('click', () => {
    const text = document.getElementById('jsonEditor')?.value || '';
    if (text.trim()) {
      handlePublish(text, 'JSON');
    }
  });
  document.getElementById('jsonClearBtn')?.addEventListener('click', () => {
    const ed = document.getElementById('jsonEditor');
    if (ed) ed.value = '';
  });
  
  // Setup helper (set cmd)
  document.getElementById('setHelperBtn')?.addEventListener('click', () => {
    const cmd = document.getElementById('setCmd')?.value || '0';
    const ch = document.getElementById('setCh')?.value || '0';
    const val = document.getElementById('setVal')?.value || '0';
    const raw = `{"set":[${cmd},${ch},${val}]}`;
    handlePublish(raw, `SET cmd=${cmd}`);
  });
  
  // Review 조회
  document.getElementById('reviewFetchBtn')?.addEventListener('click', async () => {
    const limit = parseInt(document.getElementById('reviewLimit')?.value || '30');
    const res = await apiCall(`/api/machine/${appliedMachine}/recent?limit=${limit}`);
    if (!res || !Array.isArray(res)) {
      document.getElementById('reviewBody').innerHTML = '<tr><td colspan="3">No data</td></tr>';
      return;
    }
    
    const html = res.map(msg => `
      <tr>
        <td>${msg.machine_no}</td>
        <td>${msg.timestamp}</td>
        <td class="payload-cell">${msg.payload}</td>
      </tr>
    `).join('');
    document.getElementById('reviewBody').innerHTML = html || '<tr><td colspan="3">No data</td></tr>';
  });
  
  // 초기 UI 설정
  initArcGauges();
  updateMachineDisplay();
  switchScreen(0);
  updateClock();
  startPolling();
  clockInterval = setInterval(updateClock, 1000);
});

document.addEventListener('beforeunload', () => {
  stopPolling();
  if (clockInterval) clearInterval(clockInterval);
});
