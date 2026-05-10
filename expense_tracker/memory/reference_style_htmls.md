---
name: Style reference HTML files in .claude/skills/
description: Standalone HTML mockups in .claude/skills/ serve as canonical visual references for specific UI components; always check before styling that component
type: reference
---

Style reference HTML files live in `.claude/skills/*.html`. Each file is a self-contained, runnable HTML demo of a specific component's target look.

**Current files:**
- `.claude/skills/expense-list-style.html` — canonical style for `.expense-item` rows (expense list in index.html)

**How to apply:**
1. Read the reference HTML first to extract CSS rules and HTML structure
2. Extract: class names, font-weights, spacing, mobile grid/flex layout, hover effects
3. Sync those into the template — replace inline styles with proper classes, update CSS rules to match
4. Preserve Jinja2 template logic; only update visual structure and CSS
