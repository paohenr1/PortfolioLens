/* Inspect already-rendered observations; this script makes no data requests. */
document.querySelectorAll(".chart-figure").forEach((figure) => {
  const chart = figure.querySelector("svg");
  const readout = figure.querySelector(".chart-readout");
  const points = Array.from(chart.querySelectorAll(".chart-point"));
  let selected;
  const select = (point) => {
    if (selected === point) return;
    if (selected) selected.classList.remove("selected");
    point.classList.add("selected");
    readout.textContent = point.dataset.label;
    selected = point;
  };
  const inspect = (event) => {
    const matrix = chart.getScreenCTM();
    if (!matrix || !points.length) return;
    const location = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
    const closest = points.reduce((best, point) =>
      Math.abs(Number(point.getAttribute("cx")) - location.x) <
      Math.abs(Number(best.getAttribute("cx")) - location.x) ? point : best
    );
    select(closest);
  };
  chart.addEventListener("pointermove", inspect);
  chart.addEventListener("pointerdown", inspect);
  chart.addEventListener("focusin", (event) => {
    if (points.includes(event.target)) select(event.target);
  });
  chart.addEventListener("keydown", (event) => {
    const index = points.indexOf(event.target);
    if (index < 0 || !event.target.hasAttribute("tabindex")) return;
    const next = event.key === "ArrowRight" ? Math.min(index + 1, points.length - 1) :
      event.key === "ArrowLeft" ? Math.max(index - 1, 0) :
      event.key === "Home" ? 0 : event.key === "End" ? points.length - 1 : null;
    if (next === null) return;
    event.preventDefault();
    event.target.setAttribute("tabindex", "-1");
    points[next].setAttribute("tabindex", "0");
    points[next].focus();
  });
});
