const fmtEUR = (n) => n === null || n === undefined
  ? "—"
  : n.toLocaleString("es-ES", { style: "currency", currency: "EUR", maximumFractionDigits: 2 });

const fmtQty = (n) => n.toLocaleString("es-ES", { maximumFractionDigits: 8 });

// Mirrors backend/calculations.py:solve_target_average so the calculator
// updates instantly as you type, no network round-trip needed.
function solveTargetAverage(currentQty, currentAvgCost, buyPrice, targetAvg) {
  if (!(currentQty > 0)) return { reachable: false, message: "You don't hold any of this asset yet." };
  if (!(buyPrice > 0) || !(targetAvg > 0)) return { reachable: false, message: "Enter positive numbers." };
  if (targetAvg === buyPrice) return { reachable: false, message: "Target average equals the buy price — only reachable with an infinite purchase." };

  const lo = Math.min(buyPrice, currentAvgCost);
  const hi = Math.max(buyPrice, currentAvgCost);
  if (!(targetAvg > lo && targetAvg < hi)) {
    if (currentAvgCost === targetAvg) {
      return { reachable: false, message: "That's already your current average — no purchase needed." };
    }
    return {
      reachable: false,
      message: `Not reachable: target must sit strictly between the buy price (${fmtEUR(buyPrice)}) and your current average (${fmtEUR(currentAvgCost)}).`,
    };
  }

  const x = currentQty * (currentAvgCost - targetAvg) / (targetAvg - buyPrice);
  const requiredEur = x * buyPrice;
  const direction = targetAvg < currentAvgCost ? "down" : "up";
  return {
    reachable: true,
    message: `Buy ${fmtQty(x)} units at ${fmtEUR(buyPrice)} (${fmtEUR(requiredEur)} total) to move your average ${direction} to ${fmtEUR(targetAvg)}.`,
    requiredQuantity: x,
    requiredEur,
  };
}

async function loadHoldings() {
  const res = await fetch("/assets");
  const holdings = await res.json();

  const list = document.getElementById("holdings-list");
  const empty = document.getElementById("holdings-empty");
  list.innerHTML = "";

  if (!holdings.length) {
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  const template = document.getElementById("holding-template");

  for (const h of holdings) {
    const node = template.content.cloneNode(true);
    node.querySelector(".symbol").textContent = h.symbol;
    node.querySelector(".quantity").textContent = `${fmtQty(h.quantity)} ${h.symbol}`;
    node.querySelector(".avg-cost").textContent = fmtEUR(h.avg_cost_eur);
    node.querySelector(".current-price").textContent = h.current_price_eur !== null ? fmtEUR(h.current_price_eur) : "unknown";
    node.querySelector(".total-cost").textContent = fmtEUR(h.total_cost_eur);

    const plEl = node.querySelector(".unrealized-pl");
    if (h.unrealized_pl_eur !== null && h.unrealized_pl_eur !== undefined) {
      const pct = h.unrealized_pl_pct !== null ? ` (${h.unrealized_pl_pct.toFixed(1)}%)` : "";
      plEl.textContent = `${fmtEUR(h.unrealized_pl_eur)}${pct}`;
      plEl.classList.add(h.unrealized_pl_eur >= 0 ? "positive" : "negative");
    } else {
      plEl.textContent = "unknown (no current price)";
    }

    const targetInput = node.querySelector(".calc-target");
    const priceInput = node.querySelector(".calc-price");
    const resultEl = node.querySelector(".calc-result");

    // Pre-fill buy price with current market price if we have one, as a sane starting point.
    if (h.current_price_eur) priceInput.value = h.current_price_eur.toFixed(4);

    const update = () => {
      const target = parseFloat(targetInput.value);
      const price = parseFloat(priceInput.value);
      resultEl.classList.remove("reachable", "unreachable");
      if (isNaN(target) || isNaN(price)) {
        resultEl.textContent = "";
        return;
      }
      const result = solveTargetAverage(h.quantity, h.avg_cost_eur, price, target);
      resultEl.textContent = result.message;
      resultEl.classList.add(result.reachable ? "reachable" : "unreachable");
    };
    targetInput.addEventListener("input", update);
    priceInput.addEventListener("input", update);

    list.appendChild(node);
  }
}

document.getElementById("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const resultEl = document.getElementById("upload-result");
  resultEl.className = "";
  resultEl.textContent = "Uploading…";

  const formData = new FormData(form);
  try {
    const res = await fetch("/upload", { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Upload failed");

    resultEl.className = "success";
    resultEl.textContent = `Parsed ${data.parsed} row(s) from ${data.filename}: imported ${data.imported}, ${data.duplicates_skipped} duplicate(s) skipped.`;
    form.reset();
    await loadHoldings();
  } catch (err) {
    resultEl.className = "error";
    resultEl.textContent = err.message;
  }
});

loadHoldings();
