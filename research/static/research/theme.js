/* Apply the saved theme before paint, then connect the page control. */
(() => {
  let theme = 'dark';
  try {
    const saved = localStorage.getItem('portfoliolens-theme');
    if (saved === 'light' || saved === 'dark') theme = saved;
    if (saved === 'system') {
      theme = matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
      localStorage.setItem('portfoliolens-theme', theme);
    }
  } catch { /* Use the default when storage is unavailable. */ }
  document.documentElement.dataset.theme = theme;
  document.addEventListener('DOMContentLoaded', () => {
    const select = document.getElementById('theme-select');
    if (!select) return;
    select.value = theme;
    select.addEventListener('change', () => {
      document.documentElement.dataset.theme = select.value;
      try { localStorage.setItem('portfoliolens-theme', select.value); } catch { /* Optional storage. */ }
    });
  });
})();
