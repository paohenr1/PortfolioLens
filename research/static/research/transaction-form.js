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
  const notes = {
    DEPOSIT: 'Add cash you contributed. A deposit is not an investment gain.',
    WITHDRAWAL: 'Record cash taken out of this portfolio.',
    FEE: 'Record a standalone fee. Fees attached to a buy or sell belong on that trade.',
    BUY: 'Enter completed shares and your actual execution price. Record funding before the buy.',
    SELL: 'Enter completed shares sold and your actual execution price. Holdings cannot go negative.',
    DIVIDEND: 'Enter the net cash received on the payment date.',
    SPLIT: 'Enter new-for-old terms on the effective date. A 2-for-1 split uses 2 new and 1 old.'
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
    document.getElementById('transaction-guidance').textContent = notes[kind.value] || '';
  };
  kind.addEventListener('change', update);
  update();
})();
