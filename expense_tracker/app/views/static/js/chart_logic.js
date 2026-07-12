/**
 * chart_logic.js — 圖表分析頁
 *
 * 資料由 charts.html 以 window.CHART_DATA 注入（原始 expenses / categories /
 * groups / accounts / monthly_history），所有聚合與篩選都在前端進行，
 * 帳戶／群組／類別的複選篩選才能任意組合。
 *
 * 時間模式：
 *   近年 — 一次顯示 5 年，左右滑動或按箭頭平移視窗
 *   近月 — 一次顯示 5 個月，同上
 * 收支頁的趨勢圖疊上「總資產」折線（期初餘額 + 各月現金流累計，受帳戶篩選影響）；
 * 開始記帳前的期間不畫點。
 */

const D = window.CHART_DATA || { expenses: [], categories: [], groups: [], accounts: [], history: [] };

const INCOME_COLOR = "#22c55e";
const EXPENSE_COLOR = "#ef4444";
const ASSET_COLOR = "#3b82f6";
// 固定 8 色色票（design-style.md），顏色跟著群組本身，不隨排名或篩選改變
const CAT_PALETTE = ["#60a5fa", "#4ade80", "#fbbf24", "#f472b6", "#a78bfa", "#2dd4bf", "#fb923c", "#94a3b8"];
const SKIP_CATS = new Set(["股票交易", "期初餘額"]);
const WINDOW_SIZE = 5;

Chart.defaults.color = "#9a9da2";
Chart.defaults.borderColor = "rgba(255,255,255,0.10)";
Chart.defaults.font.family = "'Figtree', 'Noto Sans TC', sans-serif";

// ── Lookup maps ───────────────────────────────────────────────────────────────

const catByName = new Map(D.categories.map(c => [c.name, c]));
const groupOf = name => {
  const c = catByName.get(name);
  return (c && c.group_name) || "未分類";
};

const groupColor = new Map();
{
  const names = D.groups.map(g => g.name);
  if (!names.includes("未分類")) names.push("未分類");
  names.forEach((n, i) => groupColor.set(n, CAT_PALETTE[i % CAT_PALETTE.length]));
}
const colorOfGroup = name => groupColor.get(name) || CAT_PALETTE[CAT_PALETTE.length - 1];

// ── State ─────────────────────────────────────────────────────────────────────

var _NS = window.NavState || {
  get: function (ns, k, d) { try { var v = sessionStorage.getItem('navstate_' + ns + '_' + k); return v !== null ? JSON.parse(v) : d; } catch (e) { return d; } },
  set: function (ns, k, v) { try { sessionStorage.setItem('navstate_' + ns + '_' + k, JSON.stringify(v)); } catch (e) { } }
};

let currentTab = _NS.get('charts', 'tab', 'balance');       // balance | expense | income
let timeMode = _NS.get('charts', 'time_mode', 'month');     // year | month
if (!['year', 'month'].includes(timeMode)) timeMode = 'month';
let filters = _NS.get('charts', 'filters', null) || { accs: [], grps: [], cats: [] };
let winOffset = { year: 0, month: 0 };                      // 0 = 最新視窗，負值往過去平移

let trendChart = null;

// ── Date helpers（月份以 year*12+month0 的索引運算） ──────────────────────────

function parseYM(s) {
  if (!s || s.length < 7) return null;
  const y = parseInt(s.slice(0, 4), 10), m = parseInt(s.slice(5, 7), 10);
  if (!y || !m) return null;
  return y * 12 + (m - 1);
}
const idxLabel = i => `${Math.floor(i / 12)}/${String(i % 12 + 1).padStart(2, "0")}`;
const range = (a, b) => { const r = []; for (let i = a; i <= b; i++) r.push(i); return r; };

const _now = new Date();
const nowIdx = _now.getFullYear() * 12 + _now.getMonth();

let minIdx = nowIdx, maxIdx = nowIdx;
D.expenses.forEach(e => {
  const i = parseYM(e.date);
  if (i !== null) { minIdx = Math.min(minIdx, i); maxIdx = Math.max(maxIdx, i); }
});
D.history.forEach(h => {
  const y = parseInt(h.year, 10), m = parseInt(h.month, 10);
  if (y && m) { const i = y * 12 + (m - 1); minIdx = Math.min(minIdx, i); maxIdx = Math.max(maxIdx, i); }
});
maxIdx = Math.max(maxIdx, nowIdx);
const minYear = Math.floor(minIdx / 12), maxYear = Math.floor(maxIdx / 12);

// ── Filter predicates ─────────────────────────────────────────────────────────

function catPass(name) {
  if (filters.grps.length && !filters.grps.includes(groupOf(name))) return false;
  if (filters.cats.length && !filters.cats.includes(name)) return false;
  return true;
}

function flowPass(e) {
  if (e.type !== 'income' && e.type !== 'expense') return false;
  if (SKIP_CATS.has(e.category)) return false;
  if (!catPass(e.category)) return false;
  if (filters.accs.length && !filters.accs.includes(e.account_id)) return false;
  return true;
}

// 匯入的歷史月結（monthly_history）沒有帳戶資訊：帳戶篩選啟用時整批排除
function histPass(h) {
  if (filters.accs.length) return false;
  if (h.type !== 'income' && h.type !== 'expense') return false;
  if (SKIP_CATS.has(h.category)) return false;
  return catPass(h.category);
}

// ── Time window ───────────────────────────────────────────────────────────────

function clampOffsets() {
  winOffset.year = Math.min(0, Math.max(minYear - maxYear, winOffset.year));
  winOffset.month = Math.min(0, Math.max(minIdx - maxIdx, winOffset.month));
}

// keys：year 模式為西元年，month 模式為月索引
function visiblePeriods() {
  clampOffsets();
  if (timeMode === 'year') {
    const end = maxYear + winOffset.year;
    return { unit: 'year', keys: range(end - (WINDOW_SIZE - 1), end) };
  }
  const end = maxIdx + winOffset.month;
  return { unit: 'month', keys: range(end - (WINDOW_SIZE - 1), end) };
}

function periodKey(monthIdx, unit) {
  return unit === 'year' ? Math.floor(monthIdx / 12) : monthIdx;
}

function scopeText(periods) {
  const ks = periods.keys;
  if (periods.unit === 'year') return `${ks[0]} – ${ks[ks.length - 1]}`;
  return `${idxLabel(ks[0])} – ${idxLabel(ks[ks.length - 1])}`;
}

function shiftWindow(dir) {
  if (timeMode === 'year') winOffset.year += dir;
  else winOffset.month += dir;
  clampOffsets();
  renderAll();
}

// ── Aggregation ───────────────────────────────────────────────────────────────

function aggregateFlows(periods) {
  const keySet = new Set(periods.keys);
  const inc = new Map(), exp = new Map();
  const add = (map, k, v) => map.set(k, (map.get(k) || 0) + v);

  D.expenses.forEach(e => {
    if (!flowPass(e)) return;
    const i = parseYM(e.date);
    if (i === null) return;
    const k = periodKey(i, periods.unit);
    if (!keySet.has(k)) return;
    add(e.type === 'income' ? inc : exp, k, Number(e.amount) || 0);
  });

  D.history.forEach(h => {
    if (!histPass(h)) return;
    const y = parseInt(h.year, 10), m = parseInt(h.month, 10);
    if (!y || !m) return;
    const k = periods.unit === 'year' ? y : y * 12 + (m - 1);
    if (!keySet.has(k)) return;
    add(h.type === 'income' ? inc : exp, k, Number(h.amount) || 0);
  });

  return { inc, exp };
}

// 各月、各帳戶的現金流變化（一次建好，之後只要依帳戶篩選累加）
// 與後端 /charts 統計同一套規則：is_asset=0 的類別不影響帳戶餘額，轉帳一律計入
const monthDeltas = new Map(); // monthIdx -> Map(accountId -> delta)
{
  const addDelta = (i, acc, v) => {
    if (!monthDeltas.has(i)) monthDeltas.set(i, new Map());
    const m = monthDeltas.get(i);
    m.set(acc, (m.get(acc) || 0) + v);
  };
  D.expenses.forEach(e => {
    const i = parseYM(e.date);
    if (i === null) return;
    const amt = Number(e.amount) || 0;
    if (e.type === 'transfer') {
      addDelta(i, e.account_id, -amt);
      addDelta(i, e.to_account_id, Number(e.to_amount) || amt);
      return;
    }
    const c = catByName.get(e.category);
    if (c && !Number(c.is_asset)) return;
    if (e.type === 'income') addDelta(i, e.account_id, amt);
    else if (e.type === 'expense') addDelta(i, e.account_id, -amt);
  });
}
const deltaIdxs = [...monthDeltas.keys()].sort((a, b) => a - b);

// 每個期間「期末」的總資產（期初餘額 + 累計現金流），只受帳戶篩選影響。
// 開始記帳前（minIdx 之前）的期間回傳 null，圖上不畫點也不連線。
function assetSeries(periods) {
  const selected = filters.accs.length ? new Set(filters.accs) : null;
  const accPass = id => !selected || selected.has(id);

  let cum = 0;
  D.accounts.forEach(a => { if (accPass(a.id)) cum += Number(a.opening_balance) || 0; });

  const ends = periods.keys.map(k => periods.unit === 'year' ? k * 12 + 11 : k);
  let p = 0;
  return ends.map(endIdx => {
    while (p < deltaIdxs.length && deltaIdxs[p] <= endIdx) {
      monthDeltas.get(deltaIdxs[p]).forEach((v, acc) => { if (accPass(acc)) cum += v; });
      p++;
    }
    if (endIdx < minIdx) return null;
    return Math.round(cum * 100) / 100;
  });
}

// ── Trend chart ───────────────────────────────────────────────────────────────

function fmtMoney(v) {
  return Math.round(v).toLocaleString();
}

function fmtShort(v) {
  const a = Math.abs(v);
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (a >= 1e4) return `${(v / 1e3).toFixed(0)}k`;
  return v.toLocaleString();
}

function renderTrend(periods) {
  const { inc, exp } = aggregateFlows(periods);
  const labels = periods.keys.map(k => periods.unit === 'year' ? String(k) : idxLabel(k));

  const datasets = [];
  if (currentTab === 'balance' || currentTab === 'expense') {
    datasets.push({
      label: "支出",
      data: periods.keys.map(k => exp.get(k) || 0),
      backgroundColor: "rgba(239,68,68,0.55)",
      borderColor: EXPENSE_COLOR,
      borderWidth: 1.5,
      borderRadius: 4,
      maxBarThickness: 26,
      order: 2,
    });
  }
  if (currentTab === 'balance' || currentTab === 'income') {
    datasets.push({
      label: "收入",
      data: periods.keys.map(k => inc.get(k) || 0),
      backgroundColor: "rgba(34,197,94,0.55)",
      borderColor: INCOME_COLOR,
      borderWidth: 1.5,
      borderRadius: 4,
      maxBarThickness: 26,
      order: 2,
    });
  }
  // 總資產趨勢線只在「收支」頁疊加，與長條共用同一個 y 軸，落點與刻度一致
  if (currentTab === 'balance') {
    datasets.push({
      type: 'line',
      label: "總資產",
      data: assetSeries(periods),
      borderColor: ASSET_COLOR,
      backgroundColor: ASSET_COLOR,
      borderWidth: 2,
      pointRadius: 3,
      pointHoverRadius: 5,
      pointHitRadius: 10,
      tension: .3,
      spanGaps: false,
      order: 1,
    });
  }

  const ctx = document.getElementById("trend-chart").getContext("2d");
  if (trendChart) trendChart.destroy();
  trendChart = new Chart(ctx, {
    type: "bar",
    data: { labels, datasets },
    options: {
      responsive: true,
      plugins: {
        legend: { display: true, labels: { usePointStyle: true, boxWidth: 8, boxHeight: 8 } },
        tooltip: {
          callbacks: { label: ctx => ` ${ctx.dataset.label}：NT$ ${(Number(ctx.parsed.y) || 0).toLocaleString()}` },
        },
      },
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: true, ticks: { callback: fmtShort } },
      },
    },
  });
}

// ── Ranking（主要收/支，依群組分類） ──────────────────────────────────────────

function aggregateByGroup(periods, type) {
  const keySet = new Set(periods.keys);
  const totals = new Map(); // catName -> sum
  const add = (k, v) => totals.set(k, (totals.get(k) || 0) + v);

  D.expenses.forEach(e => {
    if (e.type !== type || !flowPass(e)) return;
    const i = parseYM(e.date);
    if (i === null) return;
    if (keySet.has(periodKey(i, periods.unit))) add(e.category || "未分類", Number(e.amount) || 0);
  });
  D.history.forEach(h => {
    if (h.type !== type || !histPass(h)) return;
    const y = parseInt(h.year, 10), m = parseInt(h.month, 10);
    if (!y || !m) return;
    const k = periods.unit === 'year' ? y : y * 12 + (m - 1);
    if (keySet.has(k)) add(h.category || "未分類", Number(h.amount) || 0);
  });

  const groups = new Map();
  totals.forEach((v, cat) => {
    const g = groupOf(cat);
    if (!groups.has(g)) groups.set(g, { name: g, total: 0, cats: [] });
    const o = groups.get(g);
    o.total += v;
    o.cats.push({ name: cat, total: v });
  });
  const arr = [...groups.values()].sort((a, b) => b.total - a.total);
  arr.forEach(g => g.cats.sort((a, b) => b.total - a.total));
  return arr;
}

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function rankSectionHtml(type, groups, showTitle) {
  const titleMap = { expense: "主要支出", income: "主要收入" };
  let html = '<div class="rank-section">';
  if (showTitle) html += `<div class="rank-section-title ${type}">${titleMap[type]}</div>`;

  if (!groups.length) {
    html += '<div class="rank-empty">此區間沒有資料</div></div>';
    return html;
  }

  const sectionTotal = groups.reduce((s, g) => s + g.total, 0);
  const maxTotal = groups[0].total || 1;
  const TOP_GROUPS = 6, TOP_CATS = 3;

  groups.slice(0, TOP_GROUPS).forEach(g => {
    const color = colorOfGroup(g.name);
    const pct = sectionTotal ? (g.total / sectionTotal * 100).toFixed(1) : 0;
    const width = Math.max(2, g.total / maxTotal * 100);

    const catRow = c => `
      <div class="rank-cat">
        <span>${esc(c.name)}</span>
        <span class="amt"><span class="amt-sign">NT$</span><span class="amt-digits">${fmtMoney(c.total)}</span></span>
      </div>`;
    let cats = g.cats.slice(0, TOP_CATS).map(catRow).join('');
    // 其他項目縮起來，點擊展開/收合
    if (g.cats.length > TOP_CATS) {
      const restCats = g.cats.slice(TOP_CATS);
      const restSum = restCats.reduce((s, c) => s + c.total, 0);
      cats += `
      <div class="rank-cat rank-more" onclick="toggleRankMore(this)">
        <span><span class="chev">▸</span>其他 ${restCats.length} 項</span>
        <span class="amt"><span class="amt-sign">NT$</span><span class="amt-digits">${fmtMoney(restSum)}</span></span>
      </div>
      <div class="rank-rest" style="display:none">${restCats.map(catRow).join('')}</div>`;
    }

    html += `
    <div class="rank-group">
      <div class="rank-head">
        <span class="rank-name"><span class="dot" style="background:${color}"></span>${esc(g.name)}</span>
        <span class="rank-val"><span class="amt-sign">NT$</span><span class="amt-digits">${fmtMoney(g.total)}</span><span class="pct">${pct}%</span></span>
      </div>
      <div class="rank-track"><div class="rank-fill" style="width:${width}%;background:${color}"></div></div>
      <div class="rank-cats">${cats}</div>
    </div>`;
  });

  html += '</div>';
  return html;
}

function toggleRankMore(el) {
  const rest = el.nextElementSibling;
  const chev = el.querySelector('.chev');
  const open = rest.style.display !== 'none';
  rest.style.display = open ? 'none' : 'block';
  chev.textContent = open ? '▸' : '▾';
}

function renderRanking(periods) {
  const container = document.getElementById("rank-container");
  const title = document.getElementById("rank-title");

  if (currentTab === 'balance') {
    title.textContent = "主要收支";
    container.classList.add('two-col');
    container.innerHTML =
      rankSectionHtml('expense', aggregateByGroup(periods, 'expense'), true) +
      rankSectionHtml('income', aggregateByGroup(periods, 'income'), true);
  } else {
    title.textContent = currentTab === 'expense' ? "主要支出" : "主要收入";
    container.classList.remove('two-col');
    container.innerHTML = rankSectionHtml(currentTab, aggregateByGroup(periods, currentTab), false);
  }
}

// ── Filter dropdowns ──────────────────────────────────────────────────────────

const FILTER_KINDS = ['acc', 'grp', 'cat'];
const filterKeyOf = { acc: 'accs', grp: 'grps', cat: 'cats' };
const filterNameOf = { acc: '帳戶', grp: '群組', cat: '類別' };

const CHECK_SVG = '<svg class="check" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>';

function optHtml(kind, value, label) {
  return `<button class="mfilter-opt" data-value="${esc(String(value))}" onclick="toggleOpt('${kind}', this)">
    <span>${label}</span>${CHECK_SVG}</button>`;
}

// 群組/類別選單都拆成「支出／收入」兩段；已選群組會限制類別選單能選的項目
const TYPE_SECTIONS = [['expense', '支出'], ['income', '收入']];
const grpTypeOf = name => {
  const g = D.groups.find(x => x.name === name);
  return g && g.type === 'income' ? 'income' : 'expense';
};

function typeLabelHtml(t, label) {
  return `<div class="mfilter-type-label ${t}">${label}</div>`;
}

function grpMenuHtml() {
  const grpNames = D.groups.map(g => g.name);
  const hasUngrouped = D.categories.some(c => !c.group_name || !grpNames.includes(c.group_name));
  let html = optHtml('grp', '', '全部') + '<div class="mfilter-sep"></div>';
  TYPE_SECTIONS.forEach(([t, label]) => {
    const gs = D.groups.filter(g => grpTypeOf(g.name) === t);
    if (!gs.length) return;
    html += typeLabelHtml(t, label) + gs.map(g => optHtml('grp', g.name, esc(g.name))).join('');
  });
  if (hasUngrouped) html += '<div class="mfilter-sep"></div>' + optHtml('grp', '未分類', '未分類');
  return html;
}

function catMenuHtml() {
  const grpNames = D.groups.map(g => g.name);
  const allowedGrp = g => !filters.grps.length || filters.grps.includes(g);
  let html = optHtml('cat', '', '全部') + '<div class="mfilter-sep"></div>';
  TYPE_SECTIONS.forEach(([t, label]) => {
    const grpOrder = [...D.groups.filter(g => grpTypeOf(g.name) === t).map(g => g.name), '未分類'];
    let body = '';
    grpOrder.forEach(g => {
      if (!allowedGrp(g)) return;
      const cats = D.categories.filter(c => {
        if (c.type !== t) return false;
        const cg = (c.group_name && grpNames.includes(c.group_name)) ? c.group_name : '未分類';
        return cg === g;
      });
      if (!cats.length) return;
      body += `<div class="mfilter-group-label">${esc(g)}</div>` +
        cats.map(c => optHtml('cat', c.name, esc(c.name))).join('');
    });
    if (body) html += typeLabelHtml(t, label) + body;
  });
  return html;
}

// 帳戶選單依類型分組（現金／銀行／預付儲值／…），與記帳專區的放大鏡篩選一致
const ACC_TYPE_ORDER = ['現金', '銀行', '預付儲值', '投資', '保單', '其他', '信用卡', '借貸'];
const ACC_ICON_TYPE = { '💵': '現金', '🏦': '銀行', '🪙': '預付儲值', '💳': '信用卡', '👝': '其他' };
const ACC_SUBTYPE_NORM = { '負債其他': '其他' };
const accEffType = a => {
  const raw = a.sub_type || ACC_ICON_TYPE[a.icon] || '其他';
  return ACC_SUBTYPE_NORM[raw] || raw;
};

function accMenuHtml() {
  let html = optHtml('acc', '', '全部') + '<div class="mfilter-sep"></div>';
  ACC_TYPE_ORDER.forEach(t => {
    const accs = D.accounts.filter(a => accEffType(a) === t);
    if (!accs.length) return;
    html += `<div class="mfilter-group-label">${esc(t)}</div>` +
      accs.map(a => optHtml('acc', a.id, esc(`${a.icon ? a.icon + ' ' : ''}${a.name}`))).join('');
  });
  return html;
}

function buildMenus() {
  document.getElementById('mf-menu-acc').innerHTML = accMenuHtml();
  document.getElementById('mf-menu-grp').innerHTML = grpMenuHtml();
  document.getElementById('mf-menu-cat').innerHTML = catMenuHtml();
}

function syncMenuUI(kind) {
  const key = filterKeyOf[kind];
  const selected = filters[key].map(String);
  const menu = document.getElementById(`mf-menu-${kind}`);
  menu.querySelectorAll('.mfilter-opt').forEach(opt => {
    const v = opt.dataset.value;
    opt.classList.toggle('active', v === '' ? selected.length === 0 : selected.includes(v));
  });
  const btn = document.getElementById(`mf-btn-${kind}`);
  const label = document.getElementById(`mf-label-${kind}`);
  btn.classList.toggle('filtered', selected.length > 0);
  label.textContent = selected.length ? `${filterNameOf[kind]} · ${selected.length}` : filterNameOf[kind];
}

function toggleMenu(ev, kind) {
  ev.stopPropagation();
  const el = document.querySelector(`.mfilter[data-kind="${kind}"]`);
  const wasOpen = el.classList.contains('open');
  closeMenus();
  if (!wasOpen) el.classList.add('open');
}

function closeMenus() {
  document.querySelectorAll('.mfilter.open').forEach(el => el.classList.remove('open'));
}

function toggleOpt(kind, btn) {
  const key = filterKeyOf[kind];
  const raw = btn.dataset.value;
  if (raw === '') {
    filters[key] = [];
  } else {
    const value = kind === 'acc' ? parseInt(raw, 10) : raw;
    const i = filters[key].findIndex(v => String(v) === raw);
    if (i >= 0) filters[key].splice(i, 1);
    else filters[key].push(value);
  }
  // 群組變動時：類別選單只留所選群組的類別，已選但不再允許的類別一併剔除
  if (kind === 'grp') {
    if (filters.grps.length) {
      filters.cats = filters.cats.filter(name => filters.grps.includes(groupOf(name)));
    }
    document.getElementById('mf-menu-cat').innerHTML = catMenuHtml();
    syncMenuUI('cat');
  }
  _NS.set('charts', 'filters', filters);
  syncMenuUI(kind);
  renderAll();
}

document.addEventListener('click', ev => {
  if (!ev.target.closest('.mfilter')) closeMenus();
});

// ── Tabs & time modes ─────────────────────────────────────────────────────────

function switchTab(tab) {
  currentTab = tab;
  _NS.set('charts', 'tab', tab);
  document.querySelectorAll('.page-tab').forEach(t =>
    t.classList.toggle('active', t.dataset.tab === tab));
  document.getElementById('chart-title').textContent =
    tab === 'balance' ? '收支趨勢' : (tab === 'expense' ? '支出趨勢' : '收入趨勢');
  renderAll();
}

function setTimeFilter(mode) {
  timeMode = mode;
  _NS.set('charts', 'time_mode', mode);
  winOffset = { year: 0, month: 0 };
  document.querySelectorAll('.time-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.mode === mode));
  renderAll();
}

function updateWindowNav(periods) {
  const nav = document.getElementById('win-nav');
  nav.style.display = 'flex';
  document.getElementById('win-label').textContent = scopeText(periods);
  const off = timeMode === 'year' ? winOffset.year : winOffset.month;
  const minOff = timeMode === 'year' ? minYear - maxYear : minIdx - maxIdx;
  document.getElementById('win-prev').disabled = off <= minOff;
  document.getElementById('win-next').disabled = off >= 0;
}

// ── Render ────────────────────────────────────────────────────────────────────

function renderAll() {
  const periods = visiblePeriods();
  updateWindowNav(periods);
  const scope = scopeText(periods);
  document.getElementById('chart-scope').textContent = scope;
  document.getElementById('rank-scope').textContent = scope;
  renderTrend(periods);
  renderRanking(periods);
}

// ── Swipe（向左滑 → 較早的視窗；向右滑 → 較新的視窗） ─────────────────────────

{
  const area = document.getElementById('trend-swipe');
  let startX = null;
  area.addEventListener('pointerdown', e => { startX = e.clientX; });
  area.addEventListener('pointercancel', () => { startX = null; });
  area.addEventListener('pointerup', e => {
    if (startX === null) return;
    const dx = e.clientX - startX;
    startX = null;
    if (Math.abs(dx) < 40) return;
    shiftWindow(dx < 0 ? -1 : 1);
  });
}

// ── Init ─────────────────────────────────────────────────────────────────────

buildMenus();
FILTER_KINDS.forEach(syncMenuUI);
document.querySelectorAll('.time-btn').forEach(b =>
  b.classList.toggle('active', b.dataset.mode === timeMode));
switchTab(currentTab);
