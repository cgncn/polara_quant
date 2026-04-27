/* Polara Quant Dashboard — Shared utilities
   Matches design system from ui_kits/web/
   ========================================================================== */

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

/* ── Ticker glyph ───────────────────────────────────────────────────────── */
const TICKER_COLORS = {
  TSLA:'#E31E24', NVDA:'#76B900', MSFT:'#1E88E5', AAPL:'#A2AAAD',
  AMZN:'#FF9900', GOOGL:'#4285F4', META:'#0866FF', COIN:'#0052FF',
  PLTR:'#6B1FA2', SMCI:'#E06000', ADBE:'#FF0000', NKE:'#FA9F03',
  RIVN:'#00B388', BABA:'#FF6A00', HSBC:'#DB0011', CSCO:'#1BA0D7',
  TM:'#EB0A1E', CRM:'#00A1E0', WMT:'#0071CE', AMD:'#ED1C24',
  DEFAULT:'#3F51B5',
};
function tickerColor(sym) {
  return TICKER_COLORS[(sym||'').toUpperCase()] || TICKER_COLORS.DEFAULT;
}
function tickerGlyph(sym, size = 24) {
  const bg = tickerColor(sym);
  const r = Math.round(size * 0.25);
  const fs = Math.round(size * 0.46);
  return `<span style="display:inline-flex;align-items:center;justify-content:center;width:${size}px;height:${size}px;border-radius:${r}px;background:${bg};font-family:var(--font-mono);font-weight:600;font-size:${fs}px;color:white;flex-shrink:0">${(sym||'?')[0].toUpperCase()}</span>`;
}

/* ── Lucide-style icons (matching design system Primitives.jsx) ─────────── */
const ICONS = {
  home:     `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12 12 3l9 9"/><path d="M5 10v10h14V10"/></svg>`,
  compass:  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m15 9-2 6-6 2 2-6 6-2z"/></svg>`,
  calendar: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 10h18"/></svg>`,
  bookmark: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>`,
  chart:    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="m7 14 4-4 4 4 5-7"/></svg>`,
  msg:      `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`,
  settings: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1A2 2 0 1 1 4.4 16.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1A2 2 0 1 1 7 4.3l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1A2 2 0 1 1 19.7 7l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>`,
  search:   `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>`,
  back:     `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg>`,
  plus:     `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M12 5v14"/></svg>`,
  x:        `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>`,
  expand:   `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9V3h6M21 9V3h-6M3 15v6h6M21 15v6h-6"/></svg>`,
  arrowUR:  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M7 17 17 7M9 7h8v8"/></svg>`,
  arrowDR:  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M7 7l10 10M17 9v8H9"/></svg>`,
  moon:     `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/></svg>`,
  sort:     `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M7 4v16M3 8l4-4 4 4M17 20V4M21 16l-4 4-4-4"/></svg>`,
  bookOpen: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2 4h7a3 3 0 0 1 3 3v13a2 2 0 0 0-2-2H2zM22 4h-7a3 3 0 0 0-3 3v13a2 2 0 0 1 2-2h8z"/></svg>`,
  analyze:  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><rect x="7" y="13" width="2.5" height="5"/><rect x="11" y="9" width="2.5" height="9"/><rect x="15" y="6" width="2.5" height="12"/></svg>`,
};

/* Brand glyph — 4-point compass-rose star */
function starGlyph(size = 20) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none"><path d="M12 1.5 13.6 10.4 22.5 12 13.6 13.6 12 22.5 10.4 13.6 1.5 12 10.4 10.4z" fill="#E26B4F"/></svg>`;
}

function icon(name, size = 18) {
  const svg = ICONS[name];
  if (!svg) return '';
  return svg.replace('<svg ', `<svg width="${size}" height="${size}" `);
}

/* ── Status loading ─────────────────────────────────────────────────────── */
async function loadStatus() {
  try {
    const d = await (await fetch('/dashboard/api/status')).json();
    const dot  = document.getElementById('status-dot');
    const txt  = document.getElementById('status-text');
    const nav  = document.getElementById('status-nav');
    const acct = document.getElementById('status-acct');
    if (dot)  dot.className = 'status-dot ' + (d.connected ? 'live' : 'dead');
    if (txt) { txt.textContent = d.connected ? 'LIVE' : 'DISC'; txt.style.color = d.connected ? 'var(--pos)' : 'var(--neg)'; }
    if (nav && d.nav)     nav.textContent  = fmt.compact(d.nav) + ' ' + (d.currency || '');
    if (acct && d.account_id) acct.textContent = d.account_id;
  } catch {}
}

/* ── Topbar HTML ────────────────────────────────────────────────────────── */
function topbar(title, opts = {}) {
  const isHello = opts.greeting;
  return `
    <header class="topbar">
      <div class="topbar-left">
        ${starGlyph(18)}
        <span class="topbar-title">${title}</span>
      </div>
      <div class="topbar-right">
        <span id="status-dot" class="status-dot"></span>
        <span id="status-text" style="color:var(--fg-3)">—</span>
        <span style="color:var(--fg-3)">NAV <span id="status-nav" style="color:var(--fg-2)">—</span></span>
        <span style="color:var(--fg-3)">ACCT <span id="status-acct" style="color:var(--fg-2)">—</span></span>
        <span id="status-time" style="color:var(--fg-4)"></span>
      </div>
    </header>`;
}

/* ── Capsule nav HTML ────────────────────────────────────────────────────── */
function capsuleNav(active) {
  const items = [
    { href: '/dashboard/',            name: 'Today',       iconName: 'home'     },
    { href: '/dashboard/performance', name: 'Performance', iconName: 'chart'    },
    { href: '/dashboard/strategies',  name: 'Strategies',  iconName: 'compass'  },
    { href: '/dashboard/positions',   name: 'Positions',   iconName: 'bookmark' },
    { href: '/dashboard/calendar',    name: 'Calendar',    iconName: 'calendar' },
    { href: '/dashboard/settings',    name: 'Settings',    iconName: 'settings' },
  ];
  const links = items.map(it => {
    const isCurrent = active === it.name;
    return `<a href="${it.href}" ${isCurrent ? 'aria-current="page"' : ''} title="${it.name}">${icon(it.iconName, 17)}</a>`;
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
  const step  = (w - pad * 2) / (pts.length - 1);
  return pts.map((v, i) => {
    const x = pad + i * step;
    const y = pad + (1 - (v - lo) / range) * (h - pad * 2);
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(' ');
}

function sparkline(pts, { color = 'var(--fg)', w = 100, h = 32, sw = 1.5 } = {}) {
  const d = sparklinePath(pts, w, h);
  if (!d) return `<svg width="${w}" height="${h}"></svg>`;
  return `<svg width="${w}" height="${h}" style="display:block"><path d="${d}" stroke="${color}" stroke-width="${sw}" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}

/* Random-walk curve generator (placeholder sparklines) */
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

/* ── Clock ──────────────────────────────────────────────────────────────── */
function setTime() {
  const el = document.getElementById('status-time');
  if (el) el.textContent = new Date().toUTCString().slice(17, 25) + ' UTC';
}

/* ── Init ────────────────────────────────────────────────────────────────── */
function init() {
  loadStatus();
  setTime();
  setInterval(loadStatus, 30_000);
  setInterval(setTime, 1_000);
}
