(() => {
  const form = document.querySelector("[data-automatic-valuation]");
  const result = document.getElementById("automatic-valuation-result");
  if (!form || !result) return;

  async function loadValuation(canRetry) {
    const status = result.querySelector("[data-valuation-status]");
    if (status) status.textContent = "· Loading…";
    try {
      const response = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        mode: "same-origin",
        redirect: "error",
      });
      const doc = new DOMParser().parseFromString(await response.text(), "text/html");
      const content = doc.querySelector("[data-valuation-result]");
      if (!content) throw new Error("Missing valuation");
      result.replaceChildren(content);
      const retryAfter = Number(response.headers.get("Retry-After"));
      if (canRetry && response.status === 429 && retryAfter >= 1 && retryAfter <= 60) {
        const notice = document.createElement("p");
        notice.className = "muted";
        notice.textContent = `Automatic figures will retry once in ${retryAfter} seconds.`;
        result.append(notice);
        window.setTimeout(() => loadValuation(false), (retryAfter + 1) * 1000);
      }
    } catch {
      result.textContent = "Closing valuation unavailable.";
    }
  }

  loadValuation(form.hasAttribute("data-retry-performance"));
})();
