(() => {
  const form = document.querySelector("[data-automatic-valuation]");
  const result = document.getElementById("automatic-valuation-result");
  if (!form || !result) return;

  async function loadValuation() {
    result.querySelector("[data-valuation-status]").textContent = "· Loading…";
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
    } catch {
      result.textContent = "Closing valuation unavailable.";
    }
  }

  loadValuation();
})();
