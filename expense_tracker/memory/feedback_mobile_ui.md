---
name: Mobile UI — info-first, modals for add actions
description: On portrait/mobile screens, show information lists first; move all "add" input forms into FAB/button-triggered modals
type: feedback
---

On mobile (≤768px), all "add input" sections should be hidden and replaced with a button/FAB that opens a modal overlay — not shown inline.

**Why:** Portrait screens are narrow; displaying long forms above content pushes the actual information (expense list, category list, account list) too far down. Info-first, action-secondary.

**How to apply:**
- Add `display: none` on mobile for any "add form" card (use a class like `settings-add-card` or an ID like `#add-form-card`)
- Add a visible "＋ 新增..." button (or FAB for the main expense page) that opens a modal
- Modal pattern: `.overlay` + `.modal` with cancel/submit actions, same style as the stocks page "新增倉位" modal
- Desktop layout is unchanged — the inline form card remains as-is
- Applied to: index.html (記帳專區 新增明細 → FAB), settings.html (新增類別/群組/帳戶 → 按鈕+modal)
