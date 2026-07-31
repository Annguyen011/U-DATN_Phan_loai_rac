/* ═══════════════════════════════════════════════════════════════════════════
   TrashSorter Dashboard JS — Real-time SocketIO + Charts
   ═══════════════════════════════════════════════════════════════════════════ */
'use strict';

const CIRC = 2 * Math.PI * 54;
let prev = { KIM_LOAI:0, NHUA:0, GIAY:0, KHONG_PHAI_RAC:0, rejects:0 };
let eventCount = 0;
const $ = id => document.getElementById(id);

/* ── Clock ────────────────────────────────────────────────────────────── */
setInterval(() => {
  $('clock').textContent = new Date().toLocaleTimeString('vi-VN', {hour12:false});
}, 1000);

/* ── SocketIO ─────────────────────────────────────────────────────────── */
const socket = io({ transports:['websocket','polling'] });

socket.on('connect', () => {
  $('ws-dot').className = 'status-dot online';
  $('ws-label').textContent = 'Live';
  loadBootstrap();
});

socket.on('disconnect', () => {
  $('ws-dot').className = 'status-dot offline';
  $('ws-label').textContent = 'Offline';
});

socket.on('stats_update', data => renderStats(data));
socket.on('sort_event',   evt  => addLogRow(evt));
socket.on('detection',    det  => showDetect(det.label, det.confidence));

/* ── Arduino Status Poll ───────────────────────────────────────────────── */
setInterval(async () => {
  try {
    const r = await fetch('/api/arduino/status', { signal: AbortSignal.timeout(2000) });
    if (r.ok) {
      const d = await r.json();
      $('arduino-dot').className = 'hw-dot' + (d.online ? ' online' : '');
      $('arduino-label').textContent = d.online ? 'Online ✅' : 'Offline ❌';
      $('servo1-dot').className = 'hw-dot' + (d.online ? ' online' : '');
      $('servo1-label').textContent = d.online ? 'Ready' : '—';
      $('servo2-dot').className = 'hw-dot' + (d.online ? ' online' : '');
      $('servo2-label').textContent = d.online ? 'Ready' : '—';
    }
  } catch(_) {
    $('arduino-dot').className = 'hw-dot';
    $('arduino-label').textContent = '—';
  }
}, 3000);

/* ── Bootstrap data ───────────────────────────────────────────────────── */
async function loadBootstrap() {
  try {
    const r = await fetch('/api/stats/today');
    if (r.ok) {
      const d = await r.json();
      renderStats({
        KIM_LOAI: d.kim_loai||0, NHUA: d.nhua||0,
        GIAY: d.giay||0, KHONG_PHAI_RAC: d.khong_phai_rac||0,
        rejects: d.rejects||0,
      });
    }
  } catch(_) {}

  try {
    const r = await fetch('/api/events/recent?limit=30');
    if (r.ok) {
      const events = await r.json();
      events.reverse().forEach(e => addLogRow({
        trash_type: e.trash_type || e.fruit_color,
        confidence: e.confidence,
        action: e.action, station: e.station || 1,
        is_reject: e.is_reject,
        ts_ms: e.sorted_at,
      }));
    }
  } catch(_) {}
}

function renderStats(data) {
  const kl  = data.KIM_LOAI       || 0;
  const nh  = data.NHUA           || 0;
  const gi  = data.GIAY           || 0;
  const rej = data.rejects        || 0;
  const tot = kl + nh + gi;

  setCard('cnt-metal',   kl,  'sub-metal',   prev.KIM_LOAI);
  setCard('cnt-plastic', nh,  'sub-plastic', prev.NHUA);
  setCard('cnt-paper',   gi,  'sub-paper',   prev.GIAY);
  $('cnt-rejects').textContent = rej;
  $('sub-reject-pct').textContent = tot > 0 ? `${Math.round(rej/(tot+rej)*100)}%` : '0%';

  $('cnt-total').textContent = tot;
  $('sub-total-detail').textContent = `${kl}🪙 ${nh}🧴 ${gi}📄`;

  $('sb-metal').textContent   = kl;
  $('sb-plastic').textContent = nh;
  $('sb-paper').textContent   = gi;
  $('sb-other').textContent   = kpr;
  $('sb-rejects').textContent = rej;

  renderDonut(kl, nh, gi, kpr, tot);

  $('last-update').textContent = 'Updated ' +
    new Date().toLocaleTimeString('vi-VN', {hour12:false});

  prev = { KIM_LOAI:kl, NHUA:nh, GIAY:gi, KHONG_PHAI_RAC:kpr, rejects:rej };
}

function setCard(valId, val, subId, prevVal) {
  const el = $(valId);
  if (parseInt(el.textContent) !== val) {
    el.textContent = val;
    el.classList.remove('bumping');
    void el.offsetWidth;
    el.classList.add('bumping');
  }
  const diff = val - (prevVal||0);
  const sub = $(subId);
  sub.textContent = diff > 0 ? `+${diff} this session` : '—';
  sub.className = 'stat-sub' + (diff > 0 ? ' up' : '');
}

function renderDonut(kl, nh, gi, kpr, tot) {
  const total = tot || 1;
  const klArc  = (kl/total)  * CIRC;
  const nhArc  = (nh/total)  * CIRC;
  const giArc  = (gi/total)  * CIRC;
  const kprArc = (kpr/total) * CIRC;

  setArc('d-metal',   klArc,  0);
  setArc('d-plastic', nhArc,  klArc);
  setArc('d-paper',   giArc,  klArc + nhArc);
  setArc('d-other',   kprArc, klArc + nhArc + giArc);

  $('pct-metal').textContent   = Math.round(kl/total*100)  + '%';
  $('pct-plastic').textContent = Math.round(nh/total*100)  + '%';
  $('pct-paper').textContent   = Math.round(gi/total*100)  + '%';
  $('pct-other').textContent   = Math.round(kpr/total*100) + '%';
  $('donut-total').textContent = tot;
}

function setArc(id, arc, offset) {
  const el = $(id);
  el.setAttribute('stroke-dasharray', `${arc.toFixed(2)} ${(CIRC-arc).toFixed(2)}`);
  el.setAttribute('stroke-dashoffset', (-offset).toFixed(2));
}

let _camOnline = false;
function setCamStatus(online) {
  if (online === _camOnline) return;
  _camOnline = online;
  if (online) {
    $('cam-offline').classList.remove('visible');
    $('cam-live').classList.add('active');
    $('cam-status').textContent = 'streaming';
  } else {
    $('cam-offline').classList.add('visible');
    $('cam-live').classList.remove('active');
    $('cam-status').textContent = 'offline';
  }
}

setInterval(async () => {
  try {
    const r = await fetch('/api/health', { signal: AbortSignal.timeout(2000) });
    setCamStatus(r.ok);
  } catch { setCamStatus(false); }
}, 3000);

function handleCamLoad() { setCamStatus(true); }
function handleCamError() {
  fetch('/api/health', { signal: AbortSignal.timeout(1000) })
    .then(r => setCamStatus(r.ok))
    .catch(() => setCamStatus(false));
}

let _detTimer = null;
function showDetect(label, confidence) {
  const overlay = $('detect-overlay');
  const labelEl = $('detect-label');
  const confEl  = $('detect-conf');
  const badge   = $('detect-badge');

  labelEl.textContent = label;
  labelEl.className   = 'detect-label ' + label.toLowerCase();
  confEl.textContent  = (confidence*100).toFixed(0) + '%';
  overlay.style.display = 'flex';

  badge.textContent = label + ' ' + (confidence*100).toFixed(0) + '%';
  badge.className   = 'badge-accent';

  clearTimeout(_detTimer);
  _detTimer = setTimeout(() => {
    overlay.style.display = 'none';
    badge.textContent     = 'No detection';
  }, 2000);
}

function addLogRow(e) {
  const body = $('event-log');
  if (body.children.length >= 200) body.lastElementChild?.remove();

  const ts = e.ts_ms
    ? new Date(e.ts_ms).toLocaleTimeString('vi-VN', {hour12:false})
    : new Date().toLocaleTimeString('vi-VN', {hour12:false});

  const trash = e.trash_type || e.fruit_color || 'UNKNOWN';

  const row = document.createElement('div');
  row.className = 'log-row' + (e.is_reject ? ' reject' : '');
  row.innerHTML = `
    <span>${ts}</span>
    <span class="${trash}">${trash}</span>
    <span>${(e.confidence*100).toFixed(0)}%</span>
    <span>${e.action}</span>
    <span>IR${e.station||1}</span>
  `;
  body.prepend(row);

  eventCount++;
  $('event-count').textContent = eventCount + ' events';

  if (!e.is_reject) showDetect(trash, e.confidence);
}

/* ── Servo Calibration ──────────────────────────────────────────────────── */
async function testCalibrate(servoId, type) {
  const prefix = `s${servoId}-${type}`;
  const angle = parseInt(document.getElementById(prefix).value) || 0;
  const status = document.getElementById('cal-status');
  status.textContent = `Testing Servo ${servoId} → ${angle}°...`;
  status.className = 'manual-status sending';
  try {
    const r = await fetch('/api/servo/calibrate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({servo: servoId, angle: angle})
    });
    const d = await r.json();
    status.textContent = d.ok ? `✅ Servo ${d.servo} at ${d.angle}°` : `❌ ${d.msg}`;
    status.className = 'manual-status ' + (d.ok ? 'ok' : 'error');
  } catch(e) {
    status.textContent = '❌ Connection error';
    status.className = 'manual-status error';
  }
}

async function saveConfig(servoId) {
  const home  = parseInt(document.getElementById(`s${servoId}-home`).value) || 0;
  const sweep = parseInt(document.getElementById(`s${servoId}-sweep`).value) || 90;
  const status = document.getElementById('cal-status');
  status.textContent = `Saving config Servo ${servoId}...`;
  status.className = 'manual-status sending';
  try {
    const r = await fetch('/api/servo/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({servo: servoId, home: home, sweep: sweep})
    });
    const d = await r.json();
    status.textContent = d.ok ? `✅ Config saved: home=${d.home}° sweep=${d.sweep}°` : `❌ ${d.msg}`;
    status.className = 'manual-status ' + (d.ok ? 'ok' : 'error');
  } catch(e) {
    status.textContent = '❌ Connection error';
    status.className = 'manual-status error';
  }
}

async function testFire(servoId) {
  const status = document.getElementById('cal-status');
  status.textContent = `Firing Servo ${servoId}...`;
  status.className = 'manual-status sending';
  try {
    const r = await fetch('/api/servo/manual', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({type: (servoId===1)?'KIM_LOAI':'NHUA'})
    });
    const d = await r.json();
    status.textContent = d.ok ? `✅ Servo ${d.servo} fired!` : `❌ ${d.msg}`;
    status.className = 'manual-status ' + (d.ok ? 'ok' : 'error');
  } catch(e) {
    status.textContent = '❌ Connection error';
    status.className = 'manual-status error';
  }
}

async function triggerServo(type) {
  const status = $('manual-status');
  status.textContent = 'Sending...';
  status.className = 'manual-status sending';
  try {
    const r = await fetch('/api/servo/manual', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({type: type})
    });
    const d = await r.json();
    status.textContent = d.ok ? `✅ ${type} → Servo ${d.servo}` : `❌ ${d.msg}`;
    status.className = 'manual-status ' + (d.ok ? 'ok' : 'error');
  } catch(e) {
    status.textContent = '❌ Connection error';
    status.className = 'manual-status error';
  }
  setTimeout(() => { status.textContent = ''; status.className = 'manual-status'; }, 2500);
}