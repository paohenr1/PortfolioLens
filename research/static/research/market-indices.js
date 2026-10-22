/* Open detailed charts using already-loaded levels; no provider requests. */
document.querySelectorAll('[data-index-dialog]').forEach((button) => {
  const dialog = document.getElementById(button.dataset.indexDialog);
  if (!dialog || typeof dialog.showModal !== 'function') return;
  button.hidden = false;
  button.addEventListener('click', () => dialog.showModal());
  dialog.addEventListener('close', () => button.focus());
});
