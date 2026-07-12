---
name: design-style
description: 記錄此 expense_tracker (Gutamon Finance Tracker) 的 UI 設計風格與規範，新增或修改頁面時必須遵循
---

# Gutamon Finance Tracker — 設計風格指南

Gutamon 是自學程式開發者的個人品牌，重視**簡潔、實用、以 UX 為核心**的產品設計，而非華麗動畫或過度裝飾。本指南是所有頁面 UI 的唯一依據。

## 設計定調

安靜、低眩光、適合長時間閱讀財務資料的介面。以留白、排版與色彩建立層次，**不依賴漸層、插畫或裝飾性背景**。像自學工程師打造給自己使用的工具。

支援淺色 / 深色主題，透過 `<html data-theme="light|dark">` 切換（深色為預設）。

---

## 色彩 (Color)

- **Primary（藍）**：主要互動色彩，用於 CTA、active、連結、focus。
- **Positive（亮綠）**：第二品牌色，用於收益、正值、已繳清等正向財務狀態。
- **Negative（紅）**：支出、負值、刪除、危險。
- 帳戶 / 分類 / 圖表使用固定 8 色色票，確保三處配色一致。

### Design Tokens（節錄；完整值以此為準）

```css
:root {
  /* 品牌 / 語意色（跨主題一致） */
  --accent: #3b82f6;            /* blue-500，primary */
  --accent-hover: #60a5fa;
  --accent-pressed: #2563eb;
  --accent-subtle: rgba(59,130,246,0.14);

  --positive: #22c55e;   --positive-subtle: rgba(34,197,94,0.14);
  --negative: #ef4444;   --negative-subtle: rgba(239,68,68,0.14);
  --warning:  #f59e0b;   --warning-subtle:  rgba(245,158,11,0.14);

  /* 深色主題（預設） */
  --surface-base: #17181a;     /* 頁面底 */
  --surface-sunken: #101112;   /* input / 更深區塊 */
  --surface-card: #1e2022;     /* 卡片 */
  --surface-hover: #262829;
  --border-subtle: rgba(255,255,255,0.06);
  --border-default: rgba(255,255,255,0.10);
  --border-strong: rgba(255,255,255,0.18);
  --border-focus: #60a5fa;
  --text-primary: #f4f6f8;
  --text-secondary: #c2c4c8;
  --text-tertiary: #9a9da2;

  /* 固定分類色票 */
  --cat-1:#60a5fa; --cat-2:#4ade80; --cat-3:#fbbf24; --cat-4:#f472b6;
  --cat-5:#a78bfa; --cat-6:#2dd4bf; --cat-7:#fb923c; --cat-8:#94a3b8;
}

/* 淺色主題：溫暖米白 paper，非純白 */
[data-theme='light'] {
  --surface-base: #faf9f6;     /* 溫暖米白 */
  --surface-sunken: #eae7de;
  --surface-card: #ffffff;
  --surface-hover: #f2f0ea;
  --border-default: rgba(23,24,26,0.12);
  --border-focus: #3b82f6;
  --text-primary: #17181a;
  --text-secondary: #44464b;
  --text-tertiary: #75787d;
}
```

---

## 字型 (Typography)

- **介面主字**：Figtree + Noto Sans TC（拉丁 + 繁中）。
- **數字**：金額、百分比、股票代碼一律用 **JetBrains Mono**（tabular figures，數字對齊）。

```css
--font-sans: 'Figtree','Noto Sans TC','PingFang TC','Microsoft JhengHei',sans-serif;
--font-mono: 'JetBrains Mono','Noto Sans TC',ui-monospace,monospace;
```

尺寸級距（px）：`12 / 13 / 15(base) / 17 / 20 / 24 / 30 / 38 / 48`
行高：tight `1.2`、snug `1.35`、normal `1.55`、relaxed `1.7`
字重：regular 400 / medium 500 / semibold 600 / bold 700 / black 800

---

## 版型 (Layout)

- 內容最大寬度：`1120px`；側欄 `240px`；頁面 gutter `24px`。
- Spacing 以 **4px** 為基本單位（4/8/12/16/20/24/32/40/48/64…）。
- 分隔用 border（`--border-*`），不用 `<hr>`。

---

## 視覺語言 (Visual Language)

- **圓角**：柔和圓角 `--radius-md:10px` ~ `--radius-lg:14px`；pill 用 `999px`；焦點 ring `4px`。
- **邊框**：低對比 hairline `1px`（`--border-default`）。
- **陰影**：輕量環境陰影，非硬式投影。深色 `--shadow-md: 0 4px 12px rgba(0,0,0,.35)`；淺色更淡。
- **Hover**：僅微幅提亮（`--surface-hover` / `--accent-hover`）。
- **Press**：輕微縮放 `scale(0.98)`。
- **Focus Ring**：清楚但不突兀 `0 0 0 3px var(--accent-subtle)`。

---

## 動態效果 (Motion)

動畫僅作為必要的狀態回饋。

- 時長 **100–240ms**（`--duration-fast/base/slow`）。
- Easing：`cubic-bezier(0.2,0,0,1)`，**無彈跳 (No Bounce)**。
- **不使用**頁面轉場或大型進場動畫。

---

## 圖示 (Iconography)

採用 **Lucide** 線條圖示系統，維持一致、乾淨、易辨識。

**禁止**：Emoji、Icon Font、以 Unicode 符號當圖示。

---

## 文案語氣 (Tone of Voice)

第一人稱、直接、自然，像工程師寫給自己看。

- 文字簡短明確，不用誇張行銷語言或過多驚嘆號。
- 錯誤訊息：說明原因並提供下一步建議。
- 成功提示：簡潔，例如「已儲存交易」。

---

## 反模式（請避免）

- ❌ 漸層、插畫、裝飾性背景。
- ❌ 彈跳動畫、頁面轉場、大型進場動畫。
- ❌ Emoji / Icon Font / Unicode 當圖示。
- ❌ 數字金額用主體字型（一律 JetBrains Mono）。
- ❌ 高對比硬投影取代環境陰影與 border。
- ❌ 淺色主題用純白背景（應為溫暖米白 `--surface-base`）。

---

## 專案硬性規範（沿用 CLAUDE.md，不可違反）

- 禁止原生對話框 `alert()/confirm()/prompt()`，一律自製符合主題的 HTML/CSS 彈窗。
- 禁止使用者縮放：viewport meta 需含 `user-scalable=no, maximum-scale=1.0`，且保留 `base.html` 的兩個 JS 觸控監聽（pinch / double-tap）。
- 隱藏所有捲軸（`scrollbar-width:none` 等），但保留捲動行為。
- 編輯 / 刪除按鈕使用 icon 樣式（Lucide）。
