"use strict";

const printReview = document.getElementById("print-snapshot-review");
if (printReview) {
  printReview.addEventListener("click", () => window.print());
  printReview.hidden = false;
}
