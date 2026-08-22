const STORAGE_KEY = 'bata-schedule-state-v1';
const defaultState = {
  school: { start: '09:00', classMinutes: 40, breakMinutes: 10, morningClasses: 4, lunchMinutes: 60, afternoonClasses: 3, startSound: 'school-start', endSound: 'school-end' },
  life: [
    { id: 'medicine', title: '아침 약 복용', time: '08:00', category: 'health', repeat: 'daily', message: '아침 약을 복용할 시간입니다.', sound: true, browser: true },
    { id: 'breakfast', title: '아침 식사', time: '08:30', category: 'meal', repeat: 'daily', message: '아침 식사 시간입니다.', sound: true, browser: true },
    { id: 'dinner', title: '저녁 식사', time: '18:30', category: 'meal', repeat: 'daily', message: '저녁 식사 시간입니다.', sound: true, browser: true },
    { id: 'sleep', title: '취침 준비', time: '21:30', category: 'sleep', repeat: 'daily', message: '하루를 정리하고 잠자리에 들 시간입니다.', sound: true, browser: true }
  ]
};
let state = loadState();
let selectedDate = new Date();
let editingLifeId = null;
const firedAlarms = new Set();

function loadState() { try { return { ...defaultState, ...JSON.parse(localStorage.getItem(STORAGE_KEY)) }; } catch { return structuredClone(defaultState); } }
function saveState() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  fetch('/api/state', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(state) }).catch(() => {});
}
function minutesToTime(total) { const h = Math.floor(total / 60) % 24; const m = total % 60; return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`; }
function timeToMinutes(time) { const [h, m] = time.split(':').map(Number); return h * 60 + m; }
function formatDate(date) { return new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'short' }).format(date); }
function dateKey(date) { return date.toISOString().slice(0, 10); }
function categoryIcon(category) { return { health: '＋', meal: '◒', sleep: '☾', other: '·' }[category] || '·'; }
function categoryName(category) { return { health: '건강', meal: '식사', sleep: '수면', other: '기타' }[category] || '생활'; }

function buildSchoolEvents() {
  const config = state.school;
  let cursor = timeToMinutes(config.start);
  const events = [{ id: 'arrival', time: minutesToTime(cursor), title: '등교 알림', sub: '학교 하루를 시작합니다', type: '등교' }];
  for (let period = 1; period <= config.morningClasses + config.afternoonClasses; period += 1) {
    events.push({ id: `class-${period}-start`, time: minutesToTime(cursor), title: `${period}교시 시작`, sub: `${config.classMinutes}분 수업`, type: '수업 시작', soundType: config.startSound || 'school-start' });
    cursor += config.classMinutes;
    if (period === config.morningClasses) {
      events.push({ id: 'lunch', time: minutesToTime(cursor), title: '점심시간', sub: `${config.lunchMinutes}분`, type: '점심' });
      cursor += config.lunchMinutes;
    } else if (period < config.morningClasses + config.afternoonClasses) {
      events.push({ id: `break-${period}`, time: minutesToTime(cursor), title: '쉬는 시간', sub: `${config.breakMinutes}분`, type: '휴식', soundType: 'message' });
      cursor += config.breakMinutes;
    }
    if (period === config.morningClasses + config.afternoonClasses) {
      events.push({ id: 'dismissal', time: minutesToTime(cursor), title: '하교 알림', sub: '오늘 수업이 끝났습니다', type: '하교', soundType: config.endSound || 'school-end' });
    }
  }
  return events;
}
function allEvents() { return [...buildSchoolEvents(), ...state.life.map(item => ({ ...item, type: categoryName(item.category), sub: item.message, soundType: item.soundType || 'message' }))].sort((a, b) => a.time.localeCompare(b.time)); }

function render() {
  document.getElementById('dateLabel').textContent = formatDate(selectedDate);
  renderSchool(); renderLife(); updateClock();
}
function renderSchool() {
  const now = new Date(); const today = dateKey(selectedDate) === dateKey(now); const currentMinutes = now.getHours() * 60 + now.getMinutes();
  document.getElementById('schoolTimeline').innerHTML = buildSchoolEvents().map(event => {
    const active = today && currentMinutes >= timeToMinutes(event.time) && currentMinutes < timeToMinutes(event.time) + (event.id.startsWith('class') ? state.school.classMinutes : 10);
    return `<div class="timeline-row ${active ? 'current' : ''}" data-event="${event.id}"><span class="event-time">${event.time}</span><div><div class="event-title">${event.title}</div><div class="event-sub">${event.sub}</div></div><span class="event-pill">${event.type}</span></div>`;
  }).join('');
  document.querySelectorAll('.timeline-row').forEach(row => row.addEventListener('click', () => document.getElementById('schoolDialog').showModal()));
}
function renderLife() {
  const list = [...state.life].sort((a, b) => a.time.localeCompare(b.time));
  document.getElementById('lifeList').innerHTML = list.map(item => `<div class="life-item" data-life-id="${item.id}"><span class="life-time">${item.time}</span><div><div class="life-title">${item.title}</div><div class="life-meta">${item.repeat === 'daily' ? '매일' : item.repeat === 'weekdays' ? '평일' : '주말'} · ${categoryName(item.category)}</div></div><span class="life-icon">${categoryIcon(item.category)}</span></div>`).join('');
  document.querySelectorAll('.life-item').forEach(row => row.addEventListener('click', () => openLifeDialog(row.dataset.lifeId)));
}
function updateClock() {
  const now = new Date(); const current = now.getHours() * 60 + now.getMinutes();
  document.getElementById('currentClock').textContent = now.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false });
  const schoolEvents = buildSchoolEvents(); const next = allEvents().find(event => timeToMinutes(event.time) > current) || allEvents()[0];
  if (next) { document.getElementById('nextTime').textContent = next.time; document.getElementById('nextTitle').textContent = next.title; document.getElementById('nextCountdown').textContent = countdown(next.time, current); }
  const first = timeToMinutes(schoolEvents[0].time); const last = timeToMinutes(schoolEvents[schoolEvents.length - 1].time); const progress = Math.max(0, Math.min(100, ((current - first) / (last - first)) * 100));
  document.getElementById('dayProgress').style.width = `${progress}%`; document.getElementById('progressLabel').textContent = `${Math.round(progress)}%`;
  const currentEvent = schoolEvents.slice().reverse().find(event => timeToMinutes(event.time) <= current);
  document.getElementById('currentStatus').textContent = currentEvent ? `${currentEvent.title} 진행 중` : '수업 시작 전';
}
function countdown(time, current) { let gap = timeToMinutes(time) - current; if (gap < 0) gap += 1440; if (gap < 60) return `${gap}분 후 시작`; return `${Math.floor(gap / 60)}시간 ${gap % 60}분 후`; }

function updateSchoolPreview() { const form = readSchoolForm(); let cursor = timeToMinutes(form.start) + form.morningClasses * (form.classMinutes + form.breakMinutes) - form.breakMinutes + form.lunchMinutes + form.afternoonClasses * (form.classMinutes + form.breakMinutes) - form.breakMinutes; document.getElementById('schoolEndPreview').textContent = minutesToTime(cursor); }
function readSchoolForm() { return { start: document.getElementById('schoolStart').value, classMinutes: Number(document.getElementById('classMinutes').value), breakMinutes: Number(document.getElementById('breakMinutes').value), morningClasses: Number(document.getElementById('morningClasses').value), lunchMinutes: Number(document.getElementById('lunchMinutes').value), afternoonClasses: Number(document.getElementById('afternoonClasses').value) }; }
function openLifeDialog(id = null) { editingLifeId = id; const item = state.life.find(entry => entry.id === id); document.getElementById('lifeDialogTitle').textContent = item ? '생활 알림 편집' : '생활 알림 추가'; document.getElementById('lifeId').value = item?.id || ''; document.getElementById('lifeTitle').value = item?.title || ''; document.getElementById('lifeTime').value = item?.time || '08:00'; document.getElementById('lifeCategory').value = item?.category || 'health'; document.getElementById('lifeRepeat').value = item?.repeat || 'daily'; document.getElementById('lifeSoundType').value = item?.soundType || 'message'; document.getElementById('lifeMessage').value = item?.message || ''; document.getElementById('lifeSound').checked = item?.sound ?? true; document.getElementById('lifeBrowser').checked = item?.browser ?? true; document.getElementById('lifeDialog').showModal(); }
function enableNotifications() { if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission(); }
async function setupPushNotifications() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) return;
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') return;
  const registration = await navigator.serviceWorker.register('/sw.js');
  const response = await fetch('/api/push/public-key');
  const { publicKey } = await response.json();
  if (!publicKey) { document.getElementById('footerState').textContent = '서버 Push 키 설정 필요'; return; }
  let subscription = await registration.pushManager.getSubscription();
  if (!subscription) subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(publicKey) });
  await fetch('/api/push/subscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(subscription) });
  document.getElementById('footerState').textContent = '백그라운드 알림 연결됨';
}
function urlBase64ToUint8Array(value) { const padding = '='.repeat((4 - value.length % 4) % 4); const base64 = (value + padding).replace(/-/g, '+').replace(/_/g, '/'); return Uint8Array.from(atob(base64), character => character.charCodeAt(0)); }
function playSound(soundType = 'message') {
  const soundFiles = { 'school-start': '/sounds/school-start.mp3', 'school-end': '/sounds/school-end.mp3', message: '/sounds/message.mp3' };
  if (soundFiles[soundType]) {
    const audio = new Audio(soundFiles[soundType]);
    audio.play().catch(() => playMessageTone());
    document.getElementById('footerState').textContent = '학교 종소리 재생됨';
    return;
  }
  playMessageTone();
}
function playMessageTone() { const audio = new AudioContext(); const oscillator = audio.createOscillator(); const gain = audio.createGain(); oscillator.frequency.value = 880; gain.gain.setValueAtTime(.0001, audio.currentTime); gain.gain.exponentialRampToValueAtTime(.15, audio.currentTime + .02); gain.gain.exponentialRampToValueAtTime(.0001, audio.currentTime + .2); oscillator.connect(gain).connect(audio.destination); oscillator.start(); oscillator.stop(audio.currentTime + .25); document.getElementById('footerState').textContent = '일반 메시지 알림음 재생됨'; }
function playTestSound() { return fetch('/api/sounds/test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sound_type: 'message' }) }).then(response => { if (!response.ok) throw new Error('sound test failed'); document.getElementById('footerState').textContent = 'Mac mini에서 테스트 음원 재생됨'; }); }

document.getElementById('editSchoolButton').addEventListener('click', () => { const c = state.school; Object.entries({ schoolStart:c.start, classMinutes:c.classMinutes, breakMinutes:c.breakMinutes, morningClasses:c.morningClasses, lunchMinutes:c.lunchMinutes, afternoonClasses:c.afternoonClasses }).forEach(([id, value]) => { document.getElementById(id).value = value; }); document.getElementById('schoolStartSound').value = c.startSound || 'school-start'; document.getElementById('schoolEndSound').value = c.endSound || 'school-end'; updateSchoolPreview(); document.getElementById('schoolDialog').showModal(); });
document.getElementById('schoolForm').addEventListener('submit', event => { event.preventDefault(); state.school = { ...readSchoolForm(), startSound: document.getElementById('schoolStartSound').value, endSound: document.getElementById('schoolEndSound').value }; saveState(); document.getElementById('schoolDialog').close(); render(); });
document.querySelectorAll('#schoolForm input').forEach(input => input.addEventListener('input', updateSchoolPreview));
document.getElementById('addLifeButton').addEventListener('click', () => openLifeDialog()); document.getElementById('addLifeButtonBottom').addEventListener('click', () => openLifeDialog());
document.getElementById('lifeForm').addEventListener('submit', event => { event.preventDefault(); const item = { id: editingLifeId || `life-${Date.now()}`, title: document.getElementById('lifeTitle').value, time: document.getElementById('lifeTime').value, category: document.getElementById('lifeCategory').value, repeat: document.getElementById('lifeRepeat').value, soundType: document.getElementById('lifeSoundType').value, message: document.getElementById('lifeMessage').value, sound: document.getElementById('lifeSound').checked, browser: document.getElementById('lifeBrowser').checked }; const index = state.life.findIndex(entry => entry.id === editingLifeId); if (index >= 0) state.life[index] = item; else state.life.push(item); saveState(); document.getElementById('lifeDialog').close(); render(); });
document.getElementById('previousDay').addEventListener('click', () => { selectedDate.setDate(selectedDate.getDate() - 1); render(); }); document.getElementById('nextDay').addEventListener('click', () => { selectedDate.setDate(selectedDate.getDate() + 1); render(); });
document.getElementById('soundTestButton').addEventListener('click', () => { enableNotifications(); playTestSound().catch(() => { document.getElementById('footerState').textContent = 'Mac mini 테스트 음원 재생 실패'; }); setupPushNotifications().catch(() => { document.getElementById('footerState').textContent = '백그라운드 알림 연결 실패'; }); }); document.getElementById('settingsButton').addEventListener('click', () => alert('알림 권한과 소리 설정은 테스트 버튼에서 확인할 수 있습니다.'));
async function boot() {
  try { const response = await fetch('/api/state'); if (response.ok) state = await response.json(); } catch { /* local fallback */ }
  render();
}
boot(); setInterval(updateClock, 1000);
