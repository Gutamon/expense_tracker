/**
 * chart_logic.js
 * 負責從 API 取得資料並渲染 Chart.js 圖表。
 */

const PALETTE = [
  "#c8f04a", "#4af0c8", "#f04a4a", "#f0c84a",
  "#4a8af0", "#c84af0", "#4af04a", "#f08c4a",
];

const INCOME_COLOR = "#c8f04a";
const EXPENSE_COLOR = "#ff5f5f";

Chart.defaults.color = "#6b6b78";
Chart.defaults.borderColor = "#2a2a30";
Chart.defaults.font.family = "'Noto Sans TC', sans-serif";

let monthlyChartInstance = null;
let categoryChartInstance = null;
let rawMonthlyData = [];
// NavState accessor (defined in base.html; inline fallback for safety)
var _NS = window.NavState || {
  get: function(ns, k, d) { try { var v = sessionStorage.getItem('navstate_'+ns+'_'+k); return v !== null ? JSON.parse(v) : d; } catch(e) { return d; } },
  set: function(ns, k, v) { try { sessionStorage.setItem('navstate_'+ns+'_'+k, JSON.stringify(v)); } catch(e) {} }
};

let currentTab = _NS.get('charts', 'tab', 'balance'); // balance, expense, income

// ── Time filter state ─────────────────────────────────────────────────────────
let timeMode = _NS.get('charts', 'time_mode', 'all'); // 'all' | 'year' | 'month'

function getAvailableYears() {
  const years = [...new Set(rawMonthlyData.map(d => d.year))].sort((a, b) => b - a);
  if (!years.length) {
    const y = new Date().getFullYear();
    return [y];
  }
  return years;
}

function populateYearSelects() {
  const years = getAvailableYears();
  const nowYear = new Date().getFullYear();
  const nowMonth = new Date().getMonth() + 1;

  ['time-year-select', 'time-month-year-select'].forEach(id => {
    const sel = document.getElementById(id);
    if (!sel) return;
    const prev = sel.value;
    sel.innerHTML = years.map(y => `<option value="${y}">${y}年</option>`).join('');
    sel.value = years.includes(parseInt(prev)) ? prev : String(nowYear);
  });

  const mSel = document.getElementById('time-month-select');
  if (mSel && !mSel.value) mSel.value = String(nowMonth);
}

function setTimeFilter(mode) {
  timeMode = mode;
  _NS.set('charts', 'time_mode', mode);
  document.querySelectorAll('.time-btn').forEach(b => b.classList.remove('active'));
  document.querySelector(`.time-btn[onclick="setTimeFilter('${mode}')"]`).classList.add('active');
  document.getElementById('time-year-picker').style.display = mode === 'year' ? 'flex' : 'none';
  document.getElementById('time-month-picker').style.display = mode === 'month' ? 'flex' : 'none';
  applyTimeFilter();
}

function applyTimeFilter() {
  renderMonthly();
  fetchAndRenderCategory();
}

function getTimeParams() {
  if (timeMode === 'year') {
    const y = parseInt(document.getElementById('time-year-select').value);
    return { year: y, month: null };
  }
  if (timeMode === 'month') {
    const y = parseInt(document.getElementById('time-month-year-select').value);
    const m = parseInt(document.getElementById('time-month-select').value);
    return { year: y, month: m };
  }
  return { year: null, month: null };
}

// ── Fetch ─────────────────────────────────────────────────────────────────────


async function fetchAndRenderCategory() {
  const { year, month } = getTimeParams();
  let url = "/api/charts/category";
  const params = [];
  if (year) params.push(`year=${year}`);
  if (month) params.push(`month=${month}`);
  if (params.length) url += '?' + params.join('&');
  const res = await fetch(url);
  const data = await res.json();
  renderCategory(data);
}

function switchTab(tab) {
  currentTab = tab;
  _NS.set('charts', 'tab', tab);
  document.querySelectorAll('.page-tab').forEach(t => t.classList.remove('active'));
  document.querySelector(`.page-tab[onclick="switchTab('${tab}')"]`).classList.add('active');

  const titleCategory = document.getElementById('chart-title-category');
  if (tab === 'balance') {
    titleCategory.textContent = '收支佔比 (資產)';
  } else if (tab === 'expense') {
    titleCategory.textContent = '支出類別佔比';
  } else {
    titleCategory.textContent = '收入來源佔比';
  }

  renderMonthly();
  fetchAndRenderCategory();
}

// ── Monthly Chart ─────────────────────────────────────────────────────────────

function renderMonthly() {
  const { year, month } = getTimeParams();

  // Filter raw data by time selection
  let filtered = rawMonthlyData;
  if (year !== null) filtered = filtered.filter(d => d.year === year);
  if (month !== null) filtered = filtered.filter(d => d.month === month);

  const map = new Map();
  filtered.forEach(d => {
    const key = `${d.year}/${String(d.month).padStart(2, "0")}`;
    if (!map.has(key)) map.set(key, { expense: 0, income: 0 });
    const entry = map.get(key);
    if (d.type === 'expense') entry.expense += d.total;
    if (d.type === 'income') entry.income += d.total;
  });

  const labels = Array.from(map.keys()).sort();
  const datasets = [];

  if (currentTab === 'balance' || currentTab === 'expense') {
    datasets.push({
      label: "支出 (NT$)",
      data: labels.map(l => map.get(l).expense),
      backgroundColor: "rgba(255,95,95,0.18)",
      borderColor: EXPENSE_COLOR,
      borderWidth: 2,
      borderRadius: 6,
    });
  }

  if (currentTab === 'balance' || currentTab === 'income') {
    datasets.push({
      label: "收入 (NT$)",
      data: labels.map(l => map.get(l).income),
      backgroundColor: "rgba(200,240,74,0.18)",
      borderColor: INCOME_COLOR,
      borderWidth: 2,
      borderRadius: 6,
    });
  }

  const ctx = document.getElementById("monthly-chart").getContext("2d");
  if (monthlyChartInstance) monthlyChartInstance.destroy();

  monthlyChartInstance = new Chart(ctx, {
    type: "bar",
    data: { labels, datasets },
    options: {
      responsive: true,
      plugins: {
        legend: { display: currentTab === 'balance' },
        tooltip: {
          callbacks: { label: ctx => ` NT$ ${ctx.parsed.y.toLocaleString()}` },
        },
      },
      scales: {
        x: { grid: { display: false } },
        y: { ticks: { callback: v => `$${(v / 1000).toFixed(0)}k` } },
      },
    },
  });
}

// ── Category Donut Chart ──────────────────────────────────────────────────────

function renderCategory(rawCategoryData) {
  let filteredData = [];

  if (currentTab === 'balance') {
    let totalInc = 0, totalExp = 0;
    rawCategoryData.forEach(d => {
      if (d.type === 'income') totalInc += d.total;
      else totalExp += d.total;
    });
    if (totalInc > 0 || totalExp > 0) {
      filteredData = [
        { category: '總收入', total: totalInc, color: INCOME_COLOR },
        { category: '總支出', total: totalExp, color: EXPENSE_COLOR }
      ];
    }
  } else {
    filteredData = rawCategoryData
      .filter(d => d.type === currentTab)
      .map((d, i) => ({ ...d, color: PALETTE[i % PALETTE.length] }));
  }

  const labels = filteredData.map(d => d.category);
  const values = filteredData.map(d => d.total);
  const colors = filteredData.map(d => d.color);
  const total = values.reduce((a, b) => a + b, 0);

  const ctx = document.getElementById("category-chart").getContext("2d");
  if (categoryChartInstance) categoryChartInstance.destroy();

  categoryChartInstance = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: colors,
        borderColor: "#18181c",
        borderWidth: 3,
        hoverOffset: 8,
      }],
    },
    options: {
      responsive: true,
      cutout: "62%",
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => {
              const val = ctx.parsed || 0;
              const pct = total ? ((val / total) * 100).toFixed(1) : 0;
              return ` NT$ ${val.toLocaleString()} (${pct}%)`;
            },
          },
        },
      },
    },
  });

  const tbody = document.getElementById("cat-tbody");
  tbody.innerHTML = '';
  filteredData.forEach(d => {
    const pct = total ? ((d.total / total) * 100).toFixed(1) : 0;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><span class="dot" style="background:${d.color}"></span>${d.category}</td>
      <td class="amount">NT$ ${d.total.toLocaleString()}</td>
      <td>${pct}%</td>
    `;
    tbody.appendChild(tr);
  });
}

// ── Init ─────────────────────────────────────────────────────────────────────

async function initCharts() {
  const resM = await fetch("/api/charts/monthly");
  rawMonthlyData = await resM.json();
  populateYearSelects();

  // Restore saved tab (calls renderMonthly + fetchAndRenderCategory)
  switchTab(currentTab);

  // Restore saved time mode (re-renders after tab is set)
  if (timeMode !== 'all') {
    setTimeFilter(timeMode);
  }
}

initCharts();
