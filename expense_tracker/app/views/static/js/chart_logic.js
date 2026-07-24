/**
 * chart_logic.js — 圖表分析頁
 *
 * 資料由 charts.html 以 window.CHART_DATA 注入（原始 expenses / categories /
 * groups / accounts / monthly_history），所有聚合與篩選都在前端進行，
 * 帳戶／群組／類別的複選篩選才能任意組合。
 *
 * 時間控制（趨勢圖標題右側）：
 *   月／年 toggle — 決定 X 軸單位；切換時區間預設回到「最近 5 期」
 *   區間按鈕 — 點擊開啟彈窗，用起訖下拉指定顯示範圍（單位隨 toggle），最多 12 期
 *   全部 — 以年為單位一次顯示所有有資料的年份；年數 > 12 時，收支模式的
 *          收入／支出長條改「重疊成一根」呈現，避免長條過密
 * 起訖下拉只列出「有資料的區間」（最早一筆 ~ 現在）。
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
const DEFAULT_SPAN = 5;       // 預設顯示最近 5 期
const MAX_SPAN = 12;          // 區間最多 12 月／年

Chart.defaults.color = "#9a9da2";
Chart.defaults.borderColor = "rgba(255,255,255,0.10)";
Chart.defaults.font.family = "'Figtree', 'Noto Sans TC', sans-serif";

// ── Lookup maps ───────────────────────────────────────────────────────────────

// 同名類別可同時存在於收入與支出（如 清點差額），identity 是「id」或「名稱+收支類型」，
// 不可只用名稱查——否則支出列會解析到收入版類別（群組錯置到 匯入（收入））。
const catById = new Map(D.categories.filter(c => c.id).map(c => [Number(c.id), c]));
const catByNameType = new Map(D.categories.map(c => [`${c.name}|${c.type}`, c]));
const catByName = new Map(D.categories.map(c => [c.name, c]));

// row: { category, category_id?, type }（expenses 與 monthly_history 皆適用）
function resolveCat(row) {
  const cid = Number(row.category_id) || 0;
  if (cid && catById.has(cid)) return catById.get(cid);
  return catByNameType.get(`${row.category}|${row.type}`) || catByName.get(row.category) || null;
}

// 群組一律以「id」為 identity（'未分類' 為哨兵值）——收入與支出群組可以
// 同名（如 其他），用名稱當鍵會把兩個群組合併。categories 只存 group_name
// 字串，靠「群組 type 必須等於類別 type」消歧，找不到才退回純名稱比對。
const groupById = new Map(D.groups.map(g => [String(g.id), g]));
const grpTypeOf = g => g && g.type === 'income' ? 'income' : 'expense';
const groupsOfType = t => D.groups.filter(g => grpTypeOf(g) === t);

function groupIdOfCat(c) {
  if (!c || !c.group_name) return "未分類";
  const t = c.type === 'income' ? 'income' : 'expense';
  const g = D.groups.find(x => x.name === c.group_name && grpTypeOf(x) === t) ||
    D.groups.find(x => x.name === c.group_name);
  return g ? String(g.id) : "未分類";
}
const groupIdOf = (name, type) =>
  groupIdOfCat((type && catByNameType.get(`${name}|${type}`)) || catByName.get(name) || null);
const groupIdOfRow = row => groupIdOfCat(resolveCat(row));
const groupNameOfId = id => id === "未分類" ? "未分類" : ((groupById.get(String(id)) || {}).name || "未分類");

const groupColor = new Map();
{
  const ids = D.groups.map(g => String(g.id));
  ids.push("未分類");
  ids.forEach((id, i) => groupColor.set(id, CAT_PALETTE[i % CAT_PALETTE.length]));
}
const colorOfGroup = id => groupColor.get(String(id)) || CAT_PALETTE[CAT_PALETTE.length - 1];

// ── State ─────────────────────────────────────────────────────────────────────

var _NS = window.NavState || {
  get: function (ns, k, d) { try { var v = sessionStorage.getItem('navstate_' + ns + '_' + k); return v !== null ? JSON.parse(v) : d; } catch (e) { return d; } },
  set: function (ns, k, v) { try { sessionStorage.setItem('navstate_' + ns + '_' + k, JSON.stringify(v)); } catch (e) { } }
};

let currentTab = _NS.get('charts', 'tab', 'balance');       // balance | expense | income
let unit = _NS.get('charts', 'unit', 'month');              // month | year（X 軸單位）
if (!['month', 'year'].includes(unit)) unit = 'month';
let mode = _NS.get('charts', 'mode', 'range');              // range | all
if (!['range', 'all'].includes(mode)) mode = 'range';
// 自訂區間（起訖），依單位分開存：month 存月索引(year*12+m0)，year 存西元年。
// null = 尚未自訂 → 用預設「最近 5 期」。彈窗確認後才寫入。
let customRange = _NS.get('charts', 'range', null) || { month: null, year: null };
if (typeof customRange !== 'object' || customRange === null) customRange = { month: null, year: null };
let filters = _NS.get('charts', 'filters', null) || { accs: [], grps: [], cats: [] };
// 舊版把群組/類別「名稱」存進 sessionStorage，現在改用 id 當鍵——
// 把還原出來的舊值轉成 id（同名多筆全部保留），對不上的直接丟棄。
{
  const grpIds = new Set(D.groups.map(g => String(g.id)));
  filters.grps = (filters.grps || []).flatMap(v => {
    const s = String(v);
    if (s === '未分類' || grpIds.has(s)) return [s];
    return D.groups.filter(g => g.name === s).map(g => String(g.id));
  });
  filters.cats = (filters.cats || []).flatMap(v => {
    const s = String(v);
    if (catById.has(Number(s))) return [s];
    return D.categories.filter(c => c.name === s && c.id).map(c => String(c.id));
  });
  filters.accs = filters.accs || [];
}
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

// 目前單位下「有資料的區間」邊界（下拉選項只列這段），與資料總期數。
function unitBounds() {
  return unit === 'year' ? { lo: minYear, hi: maxYear } : { lo: minIdx, hi: maxIdx };
}
function unitCap() { const b = unitBounds(); return b.hi - b.lo + 1; }

// 目前單位的生效區間 [start, end]（皆含）。未自訂 → 最近 min(5, 資料期數) 期。
// 自訂值會被夾回資料邊界，並確保 start<=end 且長度不超過 12。
function activeRange() {
  const b = unitBounds();
  const saved = customRange[unit];
  if (saved && Number.isFinite(saved.start) && Number.isFinite(saved.end)) {
    let s = Math.max(b.lo, Math.min(b.hi, saved.start));
    let e = Math.max(b.lo, Math.min(b.hi, saved.end));
    if (s > e) [s, e] = [e, s];
    if (e - s + 1 > MAX_SPAN) s = e - (MAX_SPAN - 1);
    return { start: s, end: e };
  }
  const span = Math.min(DEFAULT_SPAN, Math.max(1, unitCap()));
  return { start: b.hi - (span - 1), end: b.hi };
}

// ── Filter predicates ─────────────────────────────────────────────────────────

function catPass(row) {
  if (filters.grps.length && !filters.grps.map(String).includes(groupIdOfRow(row))) return false;
  // 類別以 id 比對——收入與支出可有同名類別（如 匯入），名稱比對會合併兩者
  if (filters.cats.length) {
    const c = resolveCat(row);
    if (!c || !filters.cats.map(String).includes(String(c.id))) return false;
  }
  return true;
}

function flowPass(e) {
  if (e.type !== 'income' && e.type !== 'expense') return false;
  if (SKIP_CATS.has(e.category)) return false;
  if (!catPass(e)) return false;
  if (filters.accs.length && !filters.accs.includes(e.account_id)) return false;
  return true;
}

// 匯入的歷史月結（monthly_history）沒有帳戶資訊：帳戶篩選啟用時整批排除
function histPass(h) {
  if (filters.accs.length) return false;
  if (h.type !== 'income' && h.type !== 'expense') return false;
  if (SKIP_CATS.has(h.category)) return false;
  return catPass(h);
}

// ── Time window ───────────────────────────────────────────────────────────────

// keys：year/all 模式為西元年，month 模式為月索引
function visiblePeriods() {
  // 全部：以年為單位，一次涵蓋所有有資料的年份，不分頁
  if (mode === 'all') {
    return { unit: 'year', keys: range(minYear, maxYear) };
  }
  const r = activeRange();
  return { unit, keys: range(r.start, r.end) };
}

function periodKey(monthIdx, unit) {
  return unit === 'year' ? Math.floor(monthIdx / 12) : monthIdx;
}

function scopeText(periods) {
  const ks = periods.keys;
  if (periods.unit === 'year') return `${ks[0]} – ${ks[ks.length - 1]}`;
  return `${idxLabel(ks[0])} – ${idxLabel(ks[ks.length - 1])}`;
}

// 滑動：把目前生效區間整段平移 dir 期（維持長度），夾在資料邊界內。
// 全部模式不平移。平移後寫回 customRange 並持久化。
function shiftWindow(dir) {
  if (mode === 'all') return;
  const b = unitBounds();
  const r = activeRange();
  const len = r.end - r.start;
  let start = r.start + dir, end = r.end + dir;
  if (start < b.lo) { start = b.lo; end = b.lo + len; }
  if (end > b.hi) { end = b.hi; start = b.hi - len; }
  if (start === r.start && end === r.end) return;
  customRange[unit] = { start, end };
  _NS.set('charts', 'range', customRange);
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
    const c = resolveCat(e);
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

  // 全部模式且期數 > 12：收支長條過密，改讓收入／支出「重疊成一根」（不並排）。
  const overlap = mode === 'all' && currentTab === 'balance' && periods.keys.length > MAX_SPAN;

  const datasets = [];
  if (currentTab === 'balance' || currentTab === 'expense') {
    datasets.push({
      label: "支出",
      data: periods.keys.map(k => exp.get(k) || 0),
      backgroundColor: overlap ? "rgba(239,68,68,0.75)" : "rgba(239,68,68,0.55)",
      borderColor: EXPENSE_COLOR,
      borderWidth: overlap ? 0 : 1.5,
      borderRadius: overlap ? 0 : 4,
      maxBarThickness: 26,
      grouped: !overlap,               // 重疊：與收入畫在同一個 x 位置
      barPercentage: overlap ? 0.55 : 0.9,  // 支出畫窄一點、疊在收入前面，兩者都看得見
      order: overlap ? 1 : 2,
    });
  }
  if (currentTab === 'balance' || currentTab === 'income') {
    datasets.push({
      label: "收入",
      data: periods.keys.map(k => inc.get(k) || 0),
      backgroundColor: overlap ? "rgba(34,197,94,0.75)" : "rgba(34,197,94,0.55)",
      borderColor: INCOME_COLOR,
      borderWidth: overlap ? 0 : 1.5,
      borderRadius: overlap ? 0 : 4,
      maxBarThickness: 26,
      grouped: !overlap,
      barPercentage: overlap ? 0.9 : 0.9,   // 收入為寬底、畫在後面
      order: overlap ? 2 : 2,
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

  const groups = new Map(); // group id -> { id, name, total, cats }
  totals.forEach((v, cat) => {
    // 依「名稱+本區塊的收支類型」解析群組：主要支出只能對到支出版類別，
    // 主要收入只能對到收入版，同名類別（清點差額）不會跨型別錯置。
    const gid = groupIdOf(cat, type);
    if (!groups.has(gid)) groups.set(gid, { id: gid, name: groupNameOfId(gid), total: 0, cats: [] });
    const o = groups.get(gid);
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
    const pct = sectionTotal ? Math.round(g.total / sectionTotal * 100) : 0;

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
        <span class="rank-name"><span class="rank-pct">${pct}%</span>${esc(g.name)}</span>
        <span class="rank-val"><span class="amt-sign">NT$</span><span class="amt-digits">${fmtMoney(g.total)}</span></span>
      </div>
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

  if (currentTab === 'balance') {
    container.classList.add('two-col');
    container.innerHTML =
      rankSectionHtml('expense', aggregateByGroup(periods, 'expense'), true) +
      rankSectionHtml('income', aggregateByGroup(periods, 'income'), true);
  } else {
    container.classList.remove('two-col');
    container.innerHTML = rankSectionHtml(currentTab, aggregateByGroup(periods, currentTab), true);
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

// 群組/類別選單都拆成「支出／收入」兩段；已選群組會限制類別選單能選的項目。
// 「支出」「收入」分頁只針對單一收支類型 → 選單也只顯示該類型的群組/類別。
const TYPE_SECTIONS = [['expense', '支出'], ['income', '收入']];
const activeTypes = () => currentTab === 'balance' ? ['expense', 'income'] : [currentTab];

function typeLabelHtml(t, label) {
  return `<div class="mfilter-type-label ${t}">${label}</div>`;
}

function grpMenuHtml() {
  const showTypes = activeTypes();
  const hasUngrouped = D.categories.some(c => showTypes.includes(c.type) && groupIdOfCat(c) === '未分類');
  let html = optHtml('grp', '', '全部') + '<div class="mfilter-sep"></div>';
  TYPE_SECTIONS.forEach(([t, label]) => {
    if (!showTypes.includes(t)) return;
    const gs = groupsOfType(t);
    if (!gs.length) return;
    html += typeLabelHtml(t, label) + gs.map(g => optHtml('grp', g.id, esc(g.name))).join('');
  });
  if (hasUngrouped) html += '<div class="mfilter-sep"></div>' + optHtml('grp', '未分類', '未分類');
  return html;
}

function catMenuHtml() {
  const showTypes = activeTypes();
  const selGrps = filters.grps.map(String);
  const allowedGrp = id => !selGrps.length || selGrps.includes(String(id));
  let html = optHtml('cat', '', '全部') + '<div class="mfilter-sep"></div>';
  TYPE_SECTIONS.forEach(([t, label]) => {
    if (!showTypes.includes(t)) return;
    const grpOrder = [
      ...groupsOfType(t).map(g => ({ id: String(g.id), name: g.name })),
      { id: '未分類', name: '未分類' }
    ];
    let body = '';
    grpOrder.forEach(g => {
      if (!allowedGrp(g.id)) return;
      const cats = D.categories.filter(c => c.type === t && groupIdOfCat(c) === g.id);
      if (!cats.length) return;
      body += `<div class="mfilter-group-label">${esc(g.name)}</div>` +
        cats.map(c => optHtml('cat', c.id, esc(c.name))).join('');
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
  if (kind === 'rstart' || kind === 'rend') { pickRangeEnd(kind, Number(btn.dataset.value)); return; }
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
      const selGrps = filters.grps.map(String);
      filters.cats = filters.cats.filter(id => {
        const c = catById.get(Number(id));
        return c && selGrps.includes(groupIdOfCat(c));
      });
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
  // 「支出」「收入」分頁只針對單一收支類型：選單重建成只剩該類型的
  // 群組/類別，已選但不屬於該類型的一併剔除（'未分類' 兩型別皆可保留）
  const showTypes = activeTypes();
  filters.grps = filters.grps.filter(v =>
    String(v) === '未分類' || (groupById.has(String(v)) && showTypes.includes(grpTypeOf(groupById.get(String(v))))));
  filters.cats = filters.cats.filter(id => {
    const c = catById.get(Number(id));
    return c && showTypes.includes(c.type);
  });
  _NS.set('charts', 'filters', filters);
  document.getElementById('mf-menu-grp').innerHTML = grpMenuHtml();
  document.getElementById('mf-menu-cat').innerHTML = catMenuHtml();
  syncMenuUI('grp');
  syncMenuUI('cat');
  document.querySelectorAll('.page-tab').forEach(t =>
    t.classList.toggle('active', t.dataset.tab === tab));
  renderAll();
}

// 期間 key（月索引 or 西元年）→ 顯示字串
const periodLabel = (k, u) => u === 'year' ? String(k) : idxLabel(k);

// 月／年／全 toggle：單一控制項。月/年 → 設定 X 軸單位並套用區間；全 → 全部模式（以年呈現）。
function setMode(m) {
  if (m === 'month' || m === 'year') {
    unit = m;
    mode = 'range';
    _NS.set('charts', 'unit', unit);
  } else if (m === 'all') {
    mode = 'all';
  } else return;
  _NS.set('charts', 'mode', mode);
  syncTimeCtrl();
  renderAll();
}

// 更新時間控制項外觀：月/年/全 toggle 高亮 + 區間按鈕文字
function syncTimeCtrl() {
  // 全部模式高亮「全」；否則高亮目前單位（月／年）
  const activeMode = mode === 'all' ? 'all' : unit;
  document.querySelectorAll('.unit-opt').forEach(b =>
    b.classList.toggle('active', b.dataset.mode === activeMode));
  // 全部模式下區間按鈕停用（不可點）
  const rbtn = document.getElementById('range-btn');
  rbtn.disabled = mode === 'all';
  rbtn.style.opacity = mode === 'all' ? '.4' : '';
  const periods = visiblePeriods();
  const ks = periods.keys;
  document.getElementById('range-start').textContent = periodLabel(ks[0], periods.unit);
  document.getElementById('range-end').textContent = periodLabel(ks[ks.length - 1], periods.unit);
}

// ── 區間選擇彈窗 ──────────────────────────────────────────────────────────────

let pendingRange = null; // { start, end } 編輯中（確認前）

function rangeOptHtml(kind, k) {
  return `<button class="mfilter-opt" data-value="${k}" onclick="toggleOpt('${kind}', this)">
    <span>${periodLabel(k, unit)}</span>${CHECK_SVG}</button>`;
}

function buildRangeMenus() {
  const b = unitBounds();
  const keys = range(b.lo, b.hi);          // 只列有資料的區間
  const opts = kind => keys.map(k => rangeOptHtml(kind, k)).join('');
  document.getElementById('mf-menu-rstart').innerHTML = opts('rstart');
  document.getElementById('mf-menu-rend').innerHTML = opts('rend');
}

function openRangeDialog() {
  if (mode === 'all') return;
  const r = activeRange();
  pendingRange = { start: r.start, end: r.end };
  buildRangeMenus();
  syncRangeDialog();
  document.getElementById('range-overlay').classList.add('open');
}

function closeRangeDialog() {
  closeMenus();
  document.getElementById('range-overlay').classList.remove('open');
  pendingRange = null;
}

function onOverlayClick(ev) {
  if (ev.target.id === 'range-overlay') closeRangeDialog();
}

function pickRangeEnd(kind, k) {
  if (kind === 'rstart') pendingRange.start = k;
  else pendingRange.end = k;
  closeMenus();
  syncRangeDialog();
}

// 更新彈窗：兩個下拉標籤、勾選狀態、提示（長度上限）與確認鈕可用性
function syncRangeDialog() {
  document.getElementById('rstart-label').textContent = periodLabel(pendingRange.start, unit);
  document.getElementById('rend-label').textContent = periodLabel(pendingRange.end, unit);
  ['rstart', 'rend'].forEach(kind => {
    const sel = kind === 'rstart' ? pendingRange.start : pendingRange.end;
    document.querySelectorAll(`#mf-menu-${kind} .mfilter-opt`).forEach(opt =>
      opt.classList.toggle('active', Number(opt.dataset.value) === sel));
  });
  let s = pendingRange.start, e = pendingRange.end;
  if (s > e) [s, e] = [e, s];
  const len = e - s + 1;
  const hint = document.getElementById('range-hint');
  const unitLabel = unit === 'year' ? '年' : '個月';
  const tooLong = len > MAX_SPAN;
  hint.textContent = tooLong ? `最多只能選 ${MAX_SPAN} ${unitLabel}（目前 ${len}）` : `${len} ${unitLabel}`;
  hint.classList.toggle('error', tooLong);
  document.querySelector('.range-confirm').disabled = tooLong;
}

function confirmRange() {
  let s = pendingRange.start, e = pendingRange.end;
  if (s > e) [s, e] = [e, s];
  if (e - s + 1 > MAX_SPAN) return;
  customRange[unit] = { start: s, end: e };
  _NS.set('charts', 'range', customRange);
  closeRangeDialog();
  syncTimeCtrl();
  renderAll();
}

// ── Render ────────────────────────────────────────────────────────────────────

function renderAll() {
  const periods = visiblePeriods();
  syncTimeCtrl();
  document.getElementById('rank-scope').textContent = scopeText(periods);
  renderTrend(periods);
  renderRanking(periods);
}

// ── Swipe（向左滑 → 較近的視窗；向右滑 → 較遠的視窗） ─────────────────────────

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
    shiftWindow(dx < 0 ? 1 : -1);
  });
}

// ── Init ─────────────────────────────────────────────────────────────────────

buildMenus();
FILTER_KINDS.forEach(syncMenuUI);
syncTimeCtrl();
switchTab(currentTab);
