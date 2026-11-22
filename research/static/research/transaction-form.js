/* Progressive enhancement only; server validation and submission identity stay authoritative. */
(() => {
  const kind = document.getElementById('id_kind');
  if (!kind) return;
  const fields = {
    amount: ['DEPOSIT', 'WITHDRAWAL', 'FEE', 'DIVIDEND'],
    security_id: ['BUY', 'SELL', 'DIVIDEND', 'SPLIT'],
    quantity: ['BUY', 'SELL'], unit_price: ['BUY', 'SELL'], fees: ['BUY', 'SELL'],
    split_new: ['SPLIT'], split_old: ['SPLIT']
  };
  const update = () => {
    Object.entries(fields).forEach(([name, kinds]) => {
      const input = document.getElementById('id_' + name);
      if (!input || input.type === 'hidden') return;
      const wrapper = input.closest('div');
      // Keep field-specific server errors visible and editable after validation.
      const visible = kinds.includes(kind.value) || Boolean(wrapper.querySelector('.errorlist'));
      wrapper.hidden = !visible;
      input.disabled = !visible;
    });
  };
  kind.addEventListener('change', update);
  update();
})();
