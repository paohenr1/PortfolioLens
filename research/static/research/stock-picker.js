/* Select stable instrument identities in-place; requests only on search or holdings actions. */
(() => {
  const picker = document.querySelector('.stock-picker');
  const identity = document.getElementById('id_security_id');
  if (!picker || !identity || identity.type === 'hidden') return;
  const form = identity.form;
  const kind = document.getElementById('id_kind');
  const date = document.getElementById('id_event_date');
  const query = document.getElementById('stock-query');
  const search = document.getElementById('stock-search');
  const status = document.getElementById('stock-selection');
  const results = document.getElementById('stock-results');
  const venue = (code) => ({ XNYS: 'NYSE', XNAS: 'Nasdaq', XNMS: 'Nasdaq',
    XNGS: 'Nasdaq', XNCM: 'Nasdaq', ARCX: 'NYSE Arca', XASE: 'NYSE American',
    IEXG: 'IEX', BATS: 'Cboe BZX', EDGX: 'Cboe EDGX', EDGA: 'Cboe EDGA' }[code] || code);
  let version = 0;
  identity.closest('div').hidden = true;
  picker.hidden = false;
  if (identity.value) status.textContent = query.value ? 'Selected stock: ' + query.value : 'Stock selected. Search to change it.';
  const clear = () => { identity.value = ''; status.textContent = ''; };
  query.addEventListener('input', () => { version += 1; clear(); results.replaceChildren(); });
  const load = async (holdings = false) => {
    const current = ++version;
    if (!holdings && !query.value.trim()) {
      status.textContent = 'Enter a ticker or company name.'; query.focus(); return;
    }
    status.textContent = holdings ? 'Loading your holdings…' : 'Searching…';
    results.replaceChildren();
    const body = new URLSearchParams(holdings ? { as_of: date.value } : { q: query.value.trim() });
    try {
      const response = await fetch(holdings ? picker.dataset.heldUrl : picker.dataset.searchUrl, {
        method: 'POST', credentials: 'same-origin', body,
        headers: { 'X-CSRFToken': form.elements.csrfmiddlewaretoken.value, 'Accept': 'application/json' }
      });
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Unavailable');
      const data = await response.json();
      if (current !== version) return;
      if (!response.ok) {
        status.textContent = (data.error || 'Stock selection is unavailable.') +
          (data.retry_after ? ' Try again in ' + data.retry_after + ' seconds.' : '');
        return;
      }
      status.textContent = holdings ?
        'Your holdings on ' + data.as_of + ' · Recorded cash: ' + data.cash + ' USD' :
        (data.results.length ? 'Choose the matching listing.' : 'No supported USD listings found. Try another search.');
      if (holdings && !data.results.length) status.textContent += ' · No open holdings on this date.';
      data.results.forEach((item) => {
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'stock-result'; button.dataset.securityId = item.id;
        const title = document.createElement('strong');
        title.textContent = item.ticker + ' · ' + item.name;
        const detail = document.createElement('span');
        const shares = item.quantity?.replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '');
        detail.textContent = venue(item.exchange) + ' · ' + item.currency + (shares ? ' · ' + shares + ' shares' : '');
        button.append(title, detail);
        button.addEventListener('click', () => {
          identity.value = item.id; query.value = item.ticker;
          version += 1;
          status.textContent = 'Selected: ' + item.ticker + ' · ' + item.name + ' · ' + venue(item.exchange) + ' · ' + item.currency;
          results.replaceChildren();
          document.getElementById('id_quantity').focus();
        });
        results.append(button);
      });
      if (data.truncated) status.textContent += ' · First 20 holdings shown; search for another stock.';
    } catch {
      if (current === version) status.textContent = 'Stock selection is unavailable. Your transaction details have been kept. Try again.';
    }
  };
  search.addEventListener('click', () => load());
  query.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); load(); }
  });
  kind.addEventListener('change', () => {
    version += 1; clear(); results.replaceChildren();
    if (kind.value === 'SELL') load(true);
  });
  date.addEventListener('change', () => {
    if (kind.value === 'SELL') { clear(); load(true); }
  });
  form.addEventListener('submit', (event) => {
    if (!identity.value) {
      event.preventDefault(); status.textContent = 'Choose a stock before recording the trade.'; query.focus();
    }
  });
  if (kind.value === 'SELL') load(true);
})();
