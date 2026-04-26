/* Polara Quant Dashboard — Shared utilities */

/* ── Formatting ─────────────────────────────────────────────────────────── */
const fmt = {
  pnl:   (v) => { const n = parseFloat(v); return (n >= 0 ? '+' : '') + n.toFixed(2); },
  pct:   (v) => `${parseFloat(v).toFixed(1)}%`,
  price: (v) => v != null ? parseFloat(v).toFixed(2) : '—',
  date:  (iso) => iso ? iso.slice(0, 10) : '—',
  time:  (iso) => iso ? iso.slice(11, 16) : '—',
  num:   (v) => v ?? '—',
  compact: (v) => {
    const n = parseFloat(v);
    if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return n.toFixed(2);
  },
};

function pnlClass(v) {
  const n = parseFloat(v);
  if (n > 0) return 'pos';
  if (n < 0) return 'neg';
  return 'dim';
}

/* ── Ticker glyph colors ────────────────────────────────────────────────── */
const TICKER_COLORS = {
  TSLA:'#E31E24', NVDA:'#76B900', MSFT:'#1E88E5', AAPL:'#A2AAAD',
  AMZN:'#FF9900', GOOGL:'#4285F4', META:'#0866FF', COIN:'#0052FF',
  PLTR:'#6B1FA2', SMCI:'#E06000', DEFAULT:'#3F51B5',
};
function tickerColor(sym) {
  return TICKER_COLORS[sym?.toUpperCase()] || TICKER_COLORS.DEFAULT;
}
function tickerGlyph(sym, size = 22) {
  const bg = tickerColor(sym);
  const r = Math.round(size * 0.23);
  const fs = Math.round(size * 0.46);
  return `<span class="ticker-glyph" style="width:${size}px;height:${size}px;border-radius:${r}px;background:${bg};font-size:${fs}px">${(sym||'?')[0].toUpperCase()}</span>`;
}

/* ── Icon library (Lucide-style inline SVG) ─────────────────────────────── */
const ICONS = {
  home:     `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12 12 3l9 9"/><path d="M5 10v10h14V10"/></svg>`,
  chart:    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="m7 14 4-4 4 4 5-7"/></svg>`,
  calendar: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 10h18"/></svg>`,
  bookmark: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>`,
  settings: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1A2 2 0 1 1 4.4 16.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1A2 2 0 1 1 7 4.3l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1A2 2 0 1 1 19.7 7l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>`,
  search:   `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>`,
  arrowUR:  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M7 17 17 7M9 7h8v8"/></svg>`,
  back:     `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg>`,
};
function icon(name, size = 18) {
  const svg = ICONS[name];
  if (!svg) return '';
  return svg.replace('<svg ', `<svg width="${size}" height="${size}" `);
}

/* Brand glyph — 4-point coral star */
function starGlyph(size = 20) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none"><path d="M12 1.5 13.6 10.4 22.5 12 13.6 13.6 12 22.5 10.4 13.6 1.5 12 10.4 10.4z" fill="#E26B4F"/></svg>`;
}

/* ── Status loading ─────────────────────────────────────────────────────── */
async function loadStatus() {
  try {
    const d = await (await fetch('/dashboard/api/status')).json();
    const dot = document.getElementById('status-dot');
    const txt = document.getElementById('status-text');
    const nav = document.getElementById('status-nav');
    const acct = document.getElementById('status-acct');
    if (dot) dot.className = 'status-dot ' + (d.connected ? 'live' : 'dead');
    if (txt) { txt.textContent = d.connected ? 'LIVE' : 'DISC'; txt.style.color = d.connected ? 'var(--pos)' : 'var(--neg)'; }
    if (nav && d.nav) nav.textContent = parseFloat(d.nav).toFixed(0) + ' ' + (d.currency || '');
    if (acct && d.account_id) acct.textContent = d.account_id;
  } catch {}
}

/* ── Topbar HTML ────────────────────────────────────────────────────────── */
function topbar(title, right = '') {
  return `
    <header class="topbar">
      <div class="topbar-left">
        ${starGlyph(18)}
        <span class="topbar-title">${title}</span>
      </div>
      <div class="topbar-right">
        <span id="status-dot" class="status-dot"></span>
        <span id="status-text" style="color:var(--fg-3)">—</span>
        <span class="topbar-stat">NAV <span id="status-nav">—</span></span>
        <span class="topbar-stat">ACCT <span id="status-acct">—</span></span>
        <span id="status-time" style="color:var(--fg-4)"></span>
        ${right}
      </div>
    </header>`;
}

/* ── Capsule nav HTML ───────────────────────────────────────────────────── */
function capsuleNav(active) {
  const items = [
    { href: '/',                      name: 'Today',      icon: 'home'     },
    { href: '/dashboard/strategies',  name: 'Strategies', icon: 'chart'    },
    { href: '/dashboard/positions',   name: 'Positions',  icon: 'bookmark' },
    { href: '/dashboard/calendar',    name: 'Calendar',   icon: 'calendar' },
    { href: '/dashboard/settings',    name: 'Settings',   icon: 'settings' },
  ];
  const links = items.map(it => {
    const cls = active === it.name ? 'active' : '';
    return `<a href="${it.href}" class="${cls}" title="${it.name}">${icon(it.icon, 17)}</a>`;
  }).join('');
  return `
    <nav class="capsule-nav">
      <div class="capsule-nav-inner">
        ${links}
        <button class="nav-search" title="Search">${icon('search', 17)}</button>
      </div>
    </nav>`;
}

/* ── Sparkline SVG ──────────────────────────────────────────────────────── */
function sparklinePath(pts, w, h, pad = 3) {
  if (!pts || pts.length < 2) return '';
  const lo = Math.min(...pts), hi = Math.max(...pts);
  const range = hi - lo || 1;
  const step = (w - pad * 2) / (pts.length - 1);
  return pts.map((v, i) => {
    const x = pad + i * step;
    const y = pad + (1 - (v - lo) / range) * (h - pad * 2);
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(' ');
}

function sparkline(pts, { color = 'var(--fg)', w = 100, h = 32, sw = 1.4 } = {}) {
  const d = sparklinePath(pts, w, h);
  if (!d) return `<svg width="${w}" height="${h}"></svg>`;
  return `<svg width="${w}" height="${h}" style="display:block"><path d="${d}" stroke="${color}" stroke-width="${sw}" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}

/* Random-walk curve generator (for placeholder sparklines) */
function genCurve(seed = 1, n = 60, start = 100, vol = 0.018, drift = 0.001) {
  let v = start, x = seed * 9301;
  const pts = [];
  for (let i = 0; i < n; i++) {
    x = (x * 9301 + 49297) % 233280;
    v = v * (1 + drift + ((x / 233280) - 0.5) * 2 * vol);
    pts.push(v);
  }
  return pts;
}

/* ── Time display ───────────────────────────────────────────────────────── */
function setTime() {
  const el = document.getElementById('status-time');
  if (el) el.textContent = new Date().toUTCString().slice(17, 25) + ' UTC';
}

/* ── init ───────────────────────────────────────────────────────────────── */
function init() {
  loadStatus();
  setTime();
  setInterval(loadStatus, 30_000);
  setInterval(setTime, 1000);
}
