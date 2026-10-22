/* Explicitly synthetic UI: no market-data requests or background refresh. */
(() => {
  const periods = {
    '1D': {label: 'one-day', multiplier: 1, sp: ['28.36', '0.49'], dow: ['-68.42', '-0.16'], nasdaq: ['142.18', '0.77']},
    '1W': {label: 'one-week', multiplier: 3, sp: ['62.15', '1.08'], dow: ['218.40', '0.52'], nasdaq: ['275.62', '1.50']},
    '1M': {label: 'one-month', multiplier: 5, sp: ['-74.20', '-1.25'], dow: ['-304.62', '-0.71'], nasdaq: ['-221.80', '-1.18']},
    '1Y': {label: 'one-year', multiplier: 9, sp: ['841.10', '16.82'], dow: ['4210.45', '11.05'], nasdaq: ['2910.20', '18.52']},
  };
  const pointFormat = new Intl.NumberFormat('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: 'always'});
  const sampleNoise = [0, 4, -2, 2, -4, 1, -1, 4, -2, 0, -3, 2, 0, 4, -1, 1, -3, 2, 0, -2, 1, -1, 0];
  document.querySelectorAll('[data-period]').forEach((button) => {
    button.addEventListener('click', () => {
      const sample = periods[button.dataset.period];
      document.querySelectorAll('[data-period]').forEach((item) => item.setAttribute('aria-pressed', String(item === button)));
      document.querySelectorAll('[data-index]').forEach((card, index) => {
        const [points, percent] = sample[card.dataset.index].map(Number);
        const direction = points >= 0 ? 'positive' : 'negative';
        const text = card.querySelector('.index-change');
        text.classList.remove('positive', 'negative'); text.classList.add(direction);
        text.textContent = `${pointFormat.format(points)} (${pointFormat.format(percent)}%)`;
        const chart = card.querySelector('svg');
        chart.classList.remove('positive', 'negative'); chart.classList.add(direction);
        chart.setAttribute('aria-label', `${card.querySelector('.index-name').textContent} illustrative ${sample.label} chart`);
        const path = sampleNoise.map((n, i) => {
          const x = 2 + i * (196 / (sampleNoise.length - 1));
          const trend = direction === 'positive' ? 59 - i * 2.1 : 14 + i * 1.6;
          const y = Math.max(5, Math.min(67, trend + n * (1 + sample.multiplier / 8) + Math.sin(i + index) * 3));
          return `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`;
        }).join(' ');
        chart.querySelector('path').setAttribute('d', path);
      });
      document.getElementById('period-description').textContent = `Showing illustrative ${sample.label} index changes. Heatmap remains on the sample session.`;
    });
  });

  const map = document.querySelector('.heatmap-grid');
  document.querySelectorAll('[data-map]').forEach((button) => button.addEventListener('click', () => {
    map.classList.toggle('is-sector-view', button.dataset.map === 'sectors');
    document.querySelectorAll('[data-map]').forEach((item) => item.setAttribute('aria-pressed', String(item === button)));
  }));
  if (window.matchMedia('(max-width: 650px)').matches) {
    document.querySelector('[data-map="sectors"]').click();
  }
  const detail = document.getElementById('selection-detail');
  document.querySelectorAll('[data-symbol]').forEach((tile) => tile.addEventListener('click', () => {
    document.querySelectorAll('[data-symbol]').forEach((item) => item.setAttribute('aria-pressed', String(item === tile)));
    const data = tile.dataset;
    const name = detail.querySelector('.selection-name');
    name.replaceChildren(document.createTextNode(`${data.company} `));
    const symbol = document.createElement('span'); symbol.textContent = data.symbol; name.append(symbol);
    const price = detail.querySelector('.selection-price');
    price.replaceChildren(document.createTextNode(`$${data.price} `));
    const change = document.createElement('span'); change.className = data.direction; change.textContent = data.change; price.append(change);
    detail.querySelector('.selection-meta strong').textContent = `$${data.cap}`;
  }));

})();
