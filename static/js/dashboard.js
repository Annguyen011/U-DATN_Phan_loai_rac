dat/* static/js/dashboard.js — TrashSorter Dashboard */
'use strict';

const CIRC = 2 * Math.PI * 46;

let prev       = { KIM_LOAI: 0, NHUA: 0, GIAY: 0, KHONG_PHAI_RAC: 0, rejects: 0 };
let eventCount = 0;

const $ = id => document.getElementById(id);

// ── Clock ─────────────────────────────────────────────────────────────────
setInterval(() => {
  $('clock').textContent = new Date().toLocaleTimeString('vi-VN', { hour12: false });
}, 1000);

// ── SocketIO ──────────────────────────────────────────────────────────────
const socket = io({ transports: ['websocket', 'polling'] });

socket.on('connect', () => {
  $('ws-dot').className     = 'status-dot online';
  $('ws-label').textContent = 'Live';
  loadBootstrapData();
});

socket.on('disconnect', () => {
  $('ws-dot').className     = 'status-dot offline';
  $('ws-label').textContent = 'Offline';
});

socket.on('stats_update', data => applyStats(data));
socket.on('sort_event',   e    => addLogEntry(e));

// ── Detection event từ server (push ngay khi detect) ──────────────────────
socket.on('detection', data => {
  const { label, confidence } = data;
  showDetectionOverlay(label, confidence);
});

// ── Bootstrap data khi mở trang ───────────────────────────────────────────
async function loadBootstrapData() {
  try {
    const r = await fetch('/api/stats/today');
    if (!r.ok) return;
    const d = await r.json();
    applyStats({
      KIM_LOAI: d.kim_loai || 0,
      NHUA: d.nhua || 0,
      GIAY: d.giay || 0,
      KHONG_PHAI_RAC: d.khong_phai_rac || 0,
      rejects: d.rejects || 0,
    });
  } catch {}

  try {
    const r = await fetch('/api/events/recent?limit=30');
    if (!r.ok) return;
    const events = await r.json();
    events.reverse().forEach(e => addLogEntry({
      trash_type: e.trash_type || e.fruit_color,
      confidence: e.confidence,
      action: e.action, station: e.station,
      is_reject: e.is_reject, ts_ms: e.sorted_at,
    }));
  } catch {}
}

// ── Stats update ──────────────────────────────────────────────────────────
function applyStats(data) {
  const kl  = data.KIM_LOAI       || 0;
  const nh  = data.NHUA           || 0;
  const gi  = data.GIAY           || 0;
  const kpr = data.KHONG_PHAI_RAC || 0;
  const rej = data.rejects        || 0;
  const tot = kl + nh + gi + kpr;

  setCard('cnt-kimloai',       kl,  'sub-kimloai',       prev.KIM_LOAI);
  setCard('cnt-nhua',          nh,  'sub-nhua',          prev.NHUA);
  setCard('cnt-giay',          gi,  'sub-giay',          prev.GIAY);
  setCard('cnt-khongphairac',  kpr, 'sub-khongphairac',  prev.KHONG_PHAI_RAC);

  $('cnt-total').textContent  = tot;
  $('sub-reject').textContent = tot > 0
    ? `Reject ${Math.round(rej / (tot + rej) * 100)}%`
    : 'Reject 0%';

  $('sb-kimloai').textContent       = kl;
  $('sb-nhua').textContent          = nh;
  $('sb-giay').textContent          = gi;
  $('sb-khongphairac').textContent  = kpr;
  $('sb-rejects').textContent       = rej;

  updateDonut(kl, nh, gi, kpr, tot);

  $('last-update').textContent = 'Updated ' +
    new Date().toLocaleTimeString('vi-VN', { hour12: false });

  prev = { KIM_LOAI: kl, NHUA: nh, GIAY: gi, KHONG_PHAI_RAC: kpr, rejects: rej };
}

function setCard(valId, val, subId, prevVal) {
  const el = $(valId);
  if (parseInt(el.textContent) !== val) {
    el.textContent = val;
    el.classList.remove('bumping');
    void el.offsetWidth;
    el.classList.add('bumping');
  }
  const diff = val - (prevVal || 0);
  $(subId).textContent = diff > 0 ? `+${diff} this session` : '—';
  $(subId).className   = 'stat-card__sub' + (diff > 0 ? ' up' : '');
}

// ── Donut ─────────────────────────────────────────────────────────────────
function updateDonut(kl, nh, gi, kpr, tot) {
  const total = tot || 1;
  const klArc  = (kl / total) * CIRC;
  const nhArc  = (nh / total) * CIRC;
  const giArc  = (gi / total) * CIRC;
  const kprArc = (kpr / total) * CIRC;

  setArc('d-kimloai',       klArc,  0);
  setArc('d-nhua',          nhArc,  klArc);
  setArc('d-giay',          giArc,  klArc + nhArc);
  setArc('d-khongphairac',  kprArc, klArc + nhArc + giArc);

  $('pct-kimloai').textContent       = Math.round(kl  / total * 100) + '%';
  $('pct-nhua').textContent          = Math.round(nh  / total * 100) + '%';
  $('pct-giay').textContent          = Math.round(gi  / total * 100) + '%';
  $('pct-khongphairac').textContent  = Math.round(kpr / total * 100) + '%';
  $('donut-total').textContent       = tot;
}

function setArc(id, arc, offset) {
  const el = $(id);
  el.setAttribute('stroke-dasharray',  `${arc.toFixed(2)} ${(CIRC - arc).toFixed(2)}`);
  el.setAttribute('stroke-dashoffset', (-offset).toFixed(2));
}

// ── Camera stream ──────────────────────────────────────────────────────────
let _camOnline = false;

function setCamOnline(online) {
  if (online === _camOnline) return;
  _camOnline = online;
  if (online) {
    $('cam-offline').classList.remove('visible');
    $('cam-live').classList.add('active');
  } else {
    $('cam-offline').classList.add('visible');
    $('cam-live').classList.remove('active');
    $('cam-fps-badge').textContent = '-- fps';
  }
}

// Kiểm tra server health mỗi 3 giây
setInterval(async () => {
  try {
    const r = await fetch('/api/health', { signal: AbortSignal.timeout(2000) });
    if (r.ok) {
      setCamOnline(true);
    } else {
      setCamOnline(false);
    }
  } catch {
    setCamOnline(false);
  }
}, 3000);

let _detCount  = 0;
let _fpsTs     = performance.now();

setInterval(() => {
  const now     = performance.now();
  const elapsed = (now - _fpsTs) / 1000;
  if (elapsed > 0) {
    if (_camOnline) {
      $('cam-fps-badge').textContent = 'streaming';
    }
  }
  _fpsTs = now;
}, 5000);

function handleCamLoad() {
  setCamOnline(true);
}

function handleCamError() {
  fetch('/api/health', { signal: AbortSignal.timeout(1000) })
    .then(r => { if (!r.ok) setCamOnline(false); })
    .catch(() => setCamOnline(false));
}

// ── Detection overlay ─────────────────────────────────────────────────────
let _detHideTimer = null;

function showDetectionOverlay(label, confidence) {
  const overlay  = $('cam-det-overlay');
  const labelEl  = $('cam-det-label');
  const confEl   = $('cam-det-conf');
  const badge    = $('cam-detect-badge');

  // Update overlay
  labelEl.textContent   = label;
  labelEl.className     = 'cam-det-label ' + label.toLowerCase();
  confEl.textContent    = (confidence * 100).toFixed(0) + '%';
  overlay.style.display = 'flex';

  // Update header badge
  badge.textContent = label + ' ' + (confidence * 100).toFixed(0) + '%';
  badge.className   = 'cam-badge cam-badge--detect ' + label.toLowerCase();

  // Auto-hide sau 2s nếu không có detection mới
  clearTimeout(_detHideTimer);
  _detHideTimer = setTimeout(() => {
    overlay.style.display = 'none';
    badge.textContent     = 'No detection';
    badge.className       = 'cam-badge cam-badge--detect';
  }, 2000);
}

// ── Event log ─────────────────────────────────────────────────────────────
function addLogEntry(e) {
  const logEl = $('event-log');
  if (logEl.children.length >= 200) logEl.lastElementChild?.remove();

  const ts  = e.ts_ms
    ? new Date(e.ts_ms).toLocaleTimeString('vi-VN', { hour12: false })
    : new Date().toLocaleTimeString('vi-VN', { hour12: false });

  const trashType = e.trash_type || e.fruit_color || 'UNKNOWN';

  const row = document.createElement('div');
  row.className = 'log-entry' + (e.is_reject ? ' reject' : '');
  row.innerHTML = `
    <span class="log-entry__time">${ts}</span>
    <span class="log-entry__color ${trashType}">${trashType}</span>
    <span class="log-entry__conf">${(e.confidence * 100).toFixed(0)}%</span>
    <span class="log-entry__action">${e.action}</span>
    <span class="log-entry__station">IR${e.station || 1}</span>
  `;
  logEl.prepend(row);

  eventCount++;
  $('event-count').textContent = eventCount + ' events';

  // Khi có event mới, show detection overlay nếu không phải reject
  if (!e.is_reject) {
    showDetectionOverlay(trashType, e.confidence);
  }
}