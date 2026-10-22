/* Browser-local appearance and watchbar preferences. No network requests. */
(() => {
  const getPreference = (key) => { try { return localStorage.getItem(key); } catch { return null; } };
  const setPreference = (key, value) => { try { localStorage.setItem(key, value); } catch { /* Storage may be unavailable. */ } };
  const dialog = document.getElementById('watch-dialog');
  const customize = document.getElementById('customize-watch');
  const checkboxes = [...dialog.querySelectorAll('input[name="watch"]')];
  const keys = checkboxes.map((checkbox) => checkbox.value);
  let selected = keys;
  try {
    const stored = JSON.parse(getPreference('portfoliolens-watch'));
    if (Array.isArray(stored) && stored.length && stored.every((key) => keys.includes(key))) selected = stored;
  } catch { /* Ignore invalid saved preferences. */ }
  const applyWatch = () => document.querySelectorAll('[data-watch]').forEach((item) => { item.hidden = !selected.includes(item.dataset.watch); });
  applyWatch();
  if (typeof dialog.showModal === 'function') {
    customize.hidden = false;
    customize.addEventListener('click', () => {
      checkboxes.forEach((checkbox) => { checkbox.checked = selected.includes(checkbox.value); });
      checkboxes[0].setCustomValidity('');
      dialog.returnValue = ''; dialog.showModal();
    });
    dialog.querySelector('form').addEventListener('submit', (event) => {
      checkboxes[0].setCustomValidity('');
      if (event.submitter?.value !== 'save') return;
      const chosen = checkboxes.filter((checkbox) => checkbox.checked).map((checkbox) => checkbox.value);
      if (!chosen.length) {
        event.preventDefault(); checkboxes[0].setCustomValidity('Choose at least one market.'); checkboxes[0].reportValidity();
        return;
      }
      event.preventDefault();
      selected = chosen;
      applyWatch(); setPreference('portfoliolens-watch', JSON.stringify(selected));
      dialog.close('save');
    });
    checkboxes.forEach((checkbox) => checkbox.addEventListener('change', () => checkboxes[0].setCustomValidity('')));
    dialog.addEventListener('close', () => {
      customize.focus();
    });
  }
})();
