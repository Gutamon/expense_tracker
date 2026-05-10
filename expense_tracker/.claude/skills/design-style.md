---
name: design-style
description: 記錄此 expense_tracker 專案的 UI 設計風格與規範，當新增或修改頁面時使用
---

# Expense Tracker 設計風格指南

## 設計定調

深色系、極簡、財務工具感。用色剋制，以螢光黃綠為唯一強調色，紅色僅用於負面情境（支出、刪除）。

---

## CSS 變數（Design Tokens）

```css
:root {
  --bg: #0f0f11;          /* 頁面底色，最深 */
  --surface: #18181c;     /* 卡片/面板底色 */
  --border: #2a2a30;      /* 所有邊框 */
  --accent: #c8f04a;      /* 主要強調色：螢光黃綠，用於 income、active、CTA */
  --accent-dim: rgba(200, 240, 74, 0.12);  /* accent 淡底，用於 badge 背景 */
  --text: #e8e8ec;        /* 主要文字 */
  --muted: #6b6b78;       /* 次要文字：label、placeholder */
  --danger: #ff5f5f;      /* 危險/支出/刪除 */
  --danger-dim: rgba(255, 95, 95, 0.12);  /* danger 淡底 */
  --radius: 12px;         /* 標準圓角 */
}
```

---

## 字型

| 用途 | 字型 | 備註 |
|------|------|------|
| 主體文字 | `'Noto Sans TC', sans-serif` | 中文優先，`font-weight: 300` 為預設 |
| 金額數字 | `'DM Mono', monospace` | 所有金額一律用 monospace |
| 大標籤文字 | 同主體，`font-weight: 500` | |

**標籤字 (section heading / card h2)**：
```css
font-size: .9rem;
font-weight: 500;
letter-spacing: .06em;
text-transform: uppercase;
color: var(--muted);
```

**欄位標籤 (field label)**：
```css
font-size: .78rem;
color: var(--muted);
letter-spacing: .05em;
```

---

## 版型 (Layout)

- 頁面最大寬度：`960px`，置中，padding `2.5rem 1.5rem`
- 主要內容用 CSS Grid，形成「左欄表單 + 右欄列表」格局
- 分隔線用 `border: 1px solid var(--border)`，不用 `<hr>` 或陰影

```css
/* 常見兩欄格局 */
.grid {
  display: grid;
  grid-template-columns: 340px 1fr;
  gap: 24px;
}

/* 統計數字卡片列 */
.stats {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}
```

### RWD breakpoint：`768px`

手機版統一改為單欄，表單在上、列表在下。規則：
- 避免在直向螢幕做大區塊左右並排
- 小型資訊區塊優先水平排列（節省垂直空間）

---

## 元件規範

### 卡片 (Card)
```css
background: var(--surface);
border: 1px solid var(--border);
border-radius: var(--radius);   /* 12px */
padding: 28px;
```

### 輸入框 / Select
```css
width: 100%;
background: var(--bg);
border: 1px solid var(--border);
border-radius: 8px;
color: var(--text);
font-family: inherit;
font-size: .9rem;
padding: 10px 14px;
outline: none;
transition: border-color .2s;
/* focus: border-color 改為 var(--accent) */
```

### 主要按鈕 (btn-primary)
```css
padding: 12px;
border: none;
border-radius: 8px;
background: var(--accent);
color: #111;          /* 深色文字配亮底 */
font-weight: 500;
font-size: .9rem;
cursor: pointer;
transition: opacity .2s, transform .1s;
/* hover: opacity .88 */
/* active: transform scale(.98) */
```

### 幽靈按鈕 (btn-ghost)
```css
padding: 10px;
border: 1px solid var(--border);
background: none;
color: var(--text);
border-radius: 8px;
/* hover: border-color 改為 var(--accent) */
```

### 圖示按鈕 (icon-btn)
```css
background: none;
border: 1px solid var(--border);
color: var(--muted);
border-radius: 6px;
width: 30px; height: 30px;
font-size: .8rem;
/* hover: border/color → var(--accent) */
/* .del hover: border/color → var(--danger) */
```

### Segmented Control (分段選擇器)
用於「支出 / 收入 / 轉帳」切換：
```css
/* 外框 */
background: #0f0f11;  /* 比 --surface 更深 */
border: 1px solid var(--border);
border-radius: 8px;
padding: 4px;
/* label */
border-radius: 6px;
font-size: .85rem;
color: var(--muted);
/* checked */
background: var(--surface);
color: var(--text);
box-shadow: 0 1px 3px rgba(0,0,0,0.5);
/* income checked: color: var(--accent) */
/* expense checked: color: var(--danger) */
/* transfer checked: color: #5bc0de */
```

### Badge (類別標籤)
```css
/* income (預設) */
background: var(--accent-dim);
color: var(--accent);
/* expense */
background: var(--danger-dim);
color: var(--danger);
/* transfer */
background: rgba(91,192,222,0.12);
color: #5bc0de;

border-radius: 6px;
font-size: .72rem;
font-weight: 500;
padding: 4px 10px;
letter-spacing: .04em;
```

### 篩選 Pill (btn-filter)
```css
background: var(--surface);
border: 1px solid var(--border);
color: var(--muted);
border-radius: 20px;
padding: 6px 14px;
font-size: .85rem;
/* .active */
background: var(--accent-dim);
border-color: var(--accent);
color: var(--accent);
```

### Modal
```css
/* overlay */
background: rgba(0,0,0,.7);
backdrop-filter: blur(4px);

/* modal 本體 */
background: var(--surface);
border: 1px solid var(--border);
border-radius: 16px;
padding: 32px;
max-width: 450px;
animation: pop .25s ease;

/* pop 動畫 */
@keyframes pop {
  from { opacity: 0; transform: scale(.94) }
  to   { opacity: 1; transform: scale(1) }
}
```

### Toast 通知
```css
position: fixed;
bottom: 24px; right: 24px;
background: var(--accent);
color: #111;
border-radius: 8px;
padding: 12px 20px;
font-size: .85rem;
font-weight: 500;
/* 出現: opacity 0→1，持續 2500ms 後淡出 */
```

---

## 動態效果原則

- 所有 transition 用 `.2s` 或 `.3s`，避免過長
- hover 主要改 `border-color`、`color`、`opacity`
- 按鈕按下 `transform: scale(.98)`
- Modal 出現用 `pop` keyframe（scale + opacity）
- Toast 用 `opacity` 控制顯示/隱藏

---

## 色彩語意對照

| 情境 | 顏色 |
|------|------|
| 收入、正值、成功、primary CTA | `var(--accent)` #c8f04a |
| 支出、負值、刪除、危險 | `var(--danger)` #ff5f5f |
| 轉帳 | `#5bc0de` (固定值) |
| 次要資訊、label、佔位 | `var(--muted)` #6b6b78 |

---

## 常見反模式（請避免）

- ❌ 不用白底或亮色背景
- ❌ 不用陰影取代邊框（邊框才是本設計的分隔方式）
- ❌ 數字金額不用主體字型，一律用 DM Mono
- ❌ 不加多餘的 `box-shadow` 製造層次，靠 `--surface` vs `--bg` 區分層級
- ❌ 不用圓角超過 `16px`（modal 最大）
