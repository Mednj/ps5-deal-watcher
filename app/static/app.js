document.querySelectorAll('form[data-confirm]').forEach(form => {
  form.addEventListener('submit', event => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});

document.querySelectorAll('[data-workflow-toggle]').forEach(button => {
  const details = document.getElementById(button.getAttribute('aria-controls'));
  if (!details) return;
  button.addEventListener('click', () => {
    const expanded = button.getAttribute('aria-expanded') === 'true';
    button.setAttribute('aria-expanded', String(!expanded));
    details.hidden = expanded;
    button.innerHTML = expanded ? 'Show details <span aria-hidden="true">⌄</span>' : 'Hide details <span aria-hidden="true">⌃</span>';
  });
});

document.querySelectorAll('[data-watch-form]').forEach(form => {
  const field = name => form.querySelector(`[name="${name}"]`);
  const text = (selector, value) => {
    const element = form.querySelector(selector);
    if (element) element.textContent = value;
  };
  const money = value => new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' }).format(value);
  const refresh = () => {
    const name = (field('name')?.value || '').trim();
    const rawBudget = (field('budget')?.value || '').trim().replace(',', '.');
    const budget = Number.parseFloat(rawBudget);
    const mode = field('qualification')?.value || 'name-price';
    const basis = field('basis')?.selectedOptions[0]?.textContent.trim() || 'all-in';
    const sources = [...form.querySelectorAll('[name="sources"]:checked')].map(input => input.value);
    const delivery = Boolean(field('delivery')?.checked);
    const pickup = Boolean(field('pickup')?.checked);
    const active = Boolean(field('active')?.checked);
    const telegram = document.querySelector('[data-telegram-ready]')?.dataset.telegramReady === 'true';
    const status = form.querySelector('[data-preview-status]');

    text('[data-preview-title]', name || 'Your alert plan');
    if (!Number.isFinite(budget) || budget < 0 || !sources.length) {
      text('[data-preview-summary]', !sources.length ? 'Select at least one source to monitor this game.' : 'Add a game and a valid budget to see what causes an alert.');
      if (status) { status.textContent = 'Needs setup'; status.className = 'status-chip warning'; }
      return;
    }

    const where = [delivery && 'delivery', pickup && 'pickup'].filter(Boolean).join(' + ') || 'no route selected';
    const timing = Number.parseInt(field('interval_minutes')?.value || '5', 10);
    const rule = mode === 'name-price'
      ? `Telegram alert when a listing matches “${name}” and its advertised item price is at or below ${money(budget)}. Shipping, platform, and disc details can still need your review.`
      : `Telegram alert only when “${name}” meets your detailed filters and ${basis.toLowerCase()} budget of ${money(budget)}. Offers missing required details stay as review candidates and are not queued.`;
    const prerequisites = `${sources.map(value => value[0].toUpperCase() + value.slice(1)).join(', ')} · ${where} · every ${Number.isFinite(timing) ? timing : 5} min (source minimums may be longer)`;
    const deliveryNote = !active ? ' This watch will be paused when saved.' : !telegram ? ' Connect Telegram in Settings before expecting phone alerts.' : '';
    text('[data-preview-summary]', `${rule} ${prerequisites}.${deliveryNote}`);
    if (status) {
      status.textContent = !active ? 'Paused on save' : !telegram ? 'Telegram not connected' : 'Ready to watch';
      status.className = `status-chip ${active && telegram ? 'good' : 'warning'}`;
    }
  };
  form.addEventListener('input', refresh);
  form.addEventListener('change', refresh);
  refresh();
});
