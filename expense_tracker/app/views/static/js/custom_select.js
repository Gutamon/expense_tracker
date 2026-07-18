// Wraps every <select> on the page with a styled button+menu UI (.cs), matching the
// chart-page filter dropdown look. The native <select> stays in the DOM as the source of
// truth — existing code that reads/sets `.value`/`.disabled`, rebuilds `innerHTML`, or
// listens for `change` keeps working untouched. New <select> elements inserted later
// (e.g. via innerHTML from a template string) are picked up automatically by the
// document-level MutationObserver at the bottom of this file — no manual calls needed.

(function () {
  function optionLabel(opt) {
    return opt.textContent.trim();
  }

  function buildMenu(cs, select) {
    const menu = cs.querySelector('.cs-menu');
    menu.innerHTML = '';
    Array.from(select.children).forEach(child => {
      if (child.tagName === 'OPTGROUP') {
        const label = document.createElement('div');
        label.className = 'cs-group-label';
        label.textContent = child.label;
        menu.appendChild(label);
        Array.from(child.children).forEach(opt => menu.appendChild(buildOpt(opt)));
      } else if (child.tagName === 'OPTION') {
        menu.appendChild(buildOpt(child));
      }
    });
  }

  function buildOpt(opt) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'cs-opt';
    btn.dataset.value = opt.value;
    if (opt.disabled) btn.disabled = true;
    if (opt.style.display === 'none') btn.style.display = 'none';
    btn.innerHTML = `<span></span><svg class="check" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>`;
    btn.querySelector('span').textContent = optionLabel(opt);
    btn.addEventListener('click', () => {
      const select = btn.closest('.cs').querySelector('select');
      select.value = opt.value;
      select.dispatchEvent(new Event('change', { bubbles: true }));
      syncButton(btn.closest('.cs'), select);
      closeMenu(btn.closest('.cs'));
    });
    return btn;
  }

  function syncButton(cs, select) {
    const label = cs.querySelector('.cs-btn span');
    const selected = select.options[select.selectedIndex];
    label.textContent = selected ? optionLabel(selected) : '';
    cs.querySelector('.cs-btn').disabled = select.disabled;
    cs.querySelectorAll('.cs-opt').forEach(o => {
      o.classList.toggle('active', o.dataset.value === select.value);
    });
  }

  function closeMenu(cs) {
    cs.classList.remove('open');
  }

  function toggleMenu(cs) {
    const wasOpen = cs.classList.contains('open');
    document.querySelectorAll('.cs.open').forEach(closeMenu);
    if (!wasOpen) cs.classList.add('open');
  }

  // Existing scripts commonly do `select.value = x` / `select.disabled = true` directly,
  // which sets the property without firing 'change' or touching any attribute a
  // MutationObserver could see — so intercept the properties themselves to stay in sync.
  function interceptProp(select, prop, onSet) {
    const proto = Object.getPrototypeOf(select);
    const desc = Object.getOwnPropertyDescriptor(proto, prop);
    Object.defineProperty(select, prop, {
      configurable: true,
      enumerable: true,
      get() { return desc.get.call(select); },
      set(v) {
        desc.set.call(select, v);
        onSet(v);
      }
    });
  }

  function enhanceOne(select) {
    if (select.closest('.cs') || select.dataset.csSkip !== undefined) return;
    const cs = document.createElement('div');
    cs.className = select.dataset.csCompact !== undefined ? 'cs cs-compact' : 'cs';
    select.parentNode.insertBefore(cs, select);
    cs.appendChild(select);

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'cs-btn';
    btn.innerHTML = '<span></span><svg viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg>';
    btn.addEventListener('click', (ev) => {
      ev.stopPropagation();
      if (select.disabled) return;
      toggleMenu(cs);
    });
    cs.appendChild(btn);

    const menu = document.createElement('div');
    menu.className = 'cs-menu';
    cs.appendChild(menu);

    buildMenu(cs, select);
    syncButton(cs, select);

    // Native select can still change via user interaction or dispatched 'change' events.
    select.addEventListener('change', () => syncButton(cs, select));

    interceptProp(select, 'value', () => syncButton(cs, select));
    interceptProp(select, 'disabled', () => syncButton(cs, select));

    // Watch for options being rebuilt via innerHTML from existing page scripts.
    const mo = new MutationObserver(() => {
      buildMenu(cs, select);
      syncButton(cs, select);
    });
    mo.observe(select, { childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'disabled'] });
  }

  function enhanceCustomSelects(root) {
    (root || document).querySelectorAll('select').forEach(enhanceOne);
  }

  function refreshCustomSelect(select) {
    const cs = select.closest('.cs');
    if (!cs) return;
    buildMenu(cs, select);
    syncButton(cs, select);
  }

  document.addEventListener('click', ev => {
    if (!ev.target.closest('.cs')) document.querySelectorAll('.cs.open').forEach(closeMenu);
  });

  window.enhanceCustomSelects = enhanceCustomSelects;
  window.refreshCustomSelect = refreshCustomSelect;

  document.addEventListener('DOMContentLoaded', () => {
    enhanceCustomSelects();
    // Pages that inject whole chunks of HTML (e.g. `wrap.innerHTML = cards.map(...)`)
    // create brand-new <select> elements after this point — catch those automatically.
    new MutationObserver(mutations => {
      for (const m of mutations) {
        for (const node of m.addedNodes) {
          if (node.nodeType !== 1) continue;
          if (node.tagName === 'SELECT') enhanceOne(node);
          else if (node.querySelectorAll) node.querySelectorAll('select').forEach(enhanceOne);
        }
      }
    }).observe(document.body, { childList: true, subtree: true });
  });
})();
