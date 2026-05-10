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
let rawCategoryData = [];
let currentTab = 'balance'; // balance, expense, income

async function fetchChartData() {
  const [resM, resC] = await Promise.all([
    fetch("/api/charts/monthly"),
    fetch("/api/charts/category")
  ]);
  rawMonthlyData = await resM.json();
  rawCategoryData = await resC.json();
  
  renderCharts();
}

function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelector(`.tab[onclick="switchTab('${tab}')"]`).classList.add('active');
  
  const titleCategory = document.getElementById('chart-title-category');
  if (tab === 'balance') {
    titleCategory.textContent = '收支佔比 (資產)';
    document.getElementById('card-category').style.display = 'block';
    document.getElementById('card-table').style.display = 'block';
  } else if (tab === 'expense') {
    titleCategory.textContent = '支出類別佔比';
    document.getElementById('card-category').style.display = 'block';
    document.getElementById('card-table').style.display = 'block';
  } else {
    titleCategory.textContent = '收入來源佔比';
    document.getElementById('card-category').style.display = 'block';
    document.getElementById('card-table').style.display = 'block';
  }

  renderCharts();
}

function renderCharts() {
  renderMonthly();
  renderCategory();
}

// ── Monthly Chart ─────────────────────────────────────────────────────────────

function renderMonthly() {
  // Aggregate data by month
  const map = new Map();
  rawMonthlyData.forEach(d => {
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

function renderCategory() {
  let filteredData = [];
  
  if (currentTab === 'balance') {
    // For balance, just show total Income vs total Expense
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

  // Donut chart
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

  // Table
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

fetchChartData();
