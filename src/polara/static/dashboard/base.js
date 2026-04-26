/* Shared utilities for Polara Quant dashboard */

const fmt = {
  pnl: (v) => {
    const n = parseFloat(v);
    const sign = n >= 0 ? '+' : '';
    return `${sign}${n.toFixed(2)}`;
  },
  pct: (v) => `${parseFloat(v).toFixed(1)}%`,
  price: (v) => v ? parseFloat(v).toFixed(2) : '—',
  date: (iso) => iso ? iso.slice(0, 10) : '—',
  time: (iso) => iso ? iso.slice(11, 16) : '—',
  num: (v) => v ?? '—',
};

function pnlClass(v) {
  const n = parseFloat(v);
  if (n > 0) return 'up';
  if (n < 0) return 'down';
  return 'dim';
}

async function loadStatus() {
  try {
    const r = await fetch('/dashboard/api/status');
    const d = await r.json();
    const dot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    const navEl = document.getElementById('status-nav');
    const acctEl = document.getElementById('status-acct');

    if (dot) {
      dot.className = 'dot ' + (d.connected ? 'live' : 'dead');
    }
    if (statusText) {
      statusText.textContent = d.connected ? 'LIVE' : 'DISCONNECTED';
      statusText.className = d.connected ? 'up' : 'down';
    }
    if (navEl && d.nav) {
      const nav = parseFloat(d.nav);
      navEl.textContent = `${nav.toFixed(0)} ${d.currency || ''}`;
    }
    if (acctEl && d.account_id) {
      acctEl.textContent = d.account_id;
    }
  } catch (e) {
    console.warn('Status fetch failed', e);
  }
}

function statusBar() {
  return `
    <div class="status-bar">
      <span class="logo">◆ POLARA</span>
      <div class="status-indicator">
        <div class="dot" id="status-dot"></div>
        <span id="status-text" class="dim">—</span>
      </div>
      <div class="stat">NAV <span id="status-nav">—</span></div>
      <div class="stat">ACCT <span id="status-acct">—</span></div>
      <div class="spacer"></div>
      <span class="dim" id="status-time"></span>
    </div>
  `;
}

function nav(active) {
  const links = [
    ['/', 'Today'],
    ['/dashboard/calendar', 'Calendar'],
    ['/dashboard/strategies', 'Strategies'],
    ['/dashboard/positions', 'Positions'],
  ];
  return `
    <nav class="nav">
      ${links.map(([href, label]) =>
        `<a href="${href}" class="${active === label ? 'active' : ''}">${label}</a>`
      ).join('')}
    </nav>
  `;
}

function setTime() {
  const el = document.getElementById('status-time');
  if (el) el.textContent = new Date().toUTCString().slice(17, 25) + ' UTC';
}

function init() {
  loadStatus();
  setTime();
  setInterval(loadStatus, 30_000);
  setInterval(setTime, 1000);
}
