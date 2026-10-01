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

    wireManualAdjust(node, h.symbol);
    wireTxHistory(node, h.symbol);

    list.appendChild(node);
  }
}

function wireManualAdjust(node, symbol) {
  const details = node.querySelector(".manual-adjust");
  const submitBtn = details.querySelector(".manual-submit-btn");
  const resultEl = details.querySelector(".manual-result");
  // Captured now, while `node` (a DocumentFragment) still holds its
  // children - once it's appended into the page its children move into
  // the live DOM and the fragment itself is left permanently empty, so
  // any later `node.querySelector(...)` (e.g. inside this click handler,
  // which fires long after that append) would return null. These two
  // references stay valid because they point at the actual elements,
  // which keep existing (just relocated) after the append.
  const txList = node.querySelector(".tx-list");
  const txHistoryDetails = node.querySelector(".tx-history");

  submitBtn.addEventListener("click", async () => {
    const tx_type = details.querySelector(".manual-type").value;
    const quantity = parseFloat(details.querySelector(".manual-quantity").value);
    const priceRaw = details.querySelector(".manual-price").value;
    const price_eur = priceRaw === "" ? 0 : parseFloat(priceRaw);
    const dateRaw = details.querySelector(".manual-date").value;
    const notes = details.querySelector(".manual-notes").value || null;

    resultEl.className = "manual-result";
    if (isNaN(quantity) || quantity <= 0) {
      resultEl.classList.add("error");
      resultEl.textContent = "Enter a positive quantity.";
      return;
    }

    const body = { tx_type, quantity, price_eur, notes };
    if (dateRaw) body.timestamp = new Date(dateRaw + "T00:00:00").toISOString();

    try {
      const res = await fetch(`/assets/${symbol}/manual-transaction`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to add");

      resultEl.classList.add("success");
      resultEl.textContent = price_eur > 0
        ? "Added."
        : "Added with unknown cost (€0) — edit the notes or delete/re-add later if you learn the real value.";
      details.querySelectorAll("input").forEach((i) => (i.value = ""));

      if (txHistoryDetails.open) await loadTxHistory(txList, symbol);
      await loadHoldings();
    } catch (err) {
      resultEl.classList.add("error");
      resultEl.textContent = err.message;
    }
  });
}

function wireTxHistory(node, symbol) {
  const details = node.querySelector(".tx-history");
  const txList = node.querySelector(".tx-list"); // captured before append - see wireManualAdjust
  details.addEventListener("toggle", () => {
    if (details.open) loadTxHistory(txList, symbol);
  });
}

async function loadTxHistory(txList, symbol) {
  txList.innerHTML = "Loading…";

  const res = await fetch(`/assets/${symbol}/transactions`);
  const txs = await res.json();
  txList.innerHTML = "";

  if (!txs.length) {
    txList.innerHTML = '<div class="tx-empty">No transactions.</div>';
    return;
  }

  const rowTemplate = document.getElementById("tx-row-template");
  for (const t of txs.slice().reverse()) {
    const row = rowTemplate.content.cloneNode(true);
    row.querySelector(".tx-date").textContent = new Date(t.timestamp).toLocaleDateString("es-ES");
    row.querySelector(".tx-type").textContent = t.tx_type.toUpperCase();
    row.querySelector(".tx-qty").textContent = fmtQty(t.quantity);
    row.querySelector(".tx-price").textContent = t.price_eur > 0 ? fmtEUR(t.price_eur) : "unknown";
    row.querySelector(".tx-total").textContent = fmtEUR(t.total_eur);
    row.querySelector(".tx-exchange").textContent = t.exchange;
    row.querySelector(".tx-notes").textContent = t.notes || "";
    row.querySelector(".tx-notes").title = t.notes || "";

    const delBtn = row.querySelector(".tx-delete");
    delBtn.addEventListener("click", async () => {
      if (!confirm(`Delete this ${t.exchange} ${t.tx_type} of ${fmtQty(t.quantity)} ${symbol}?`)) return;
      await fetch(`/transactions/${t.id}`, { method: "DELETE" });
      await loadTxHistory(txList, symbol);
      await loadHoldings();
    });

    txList.appendChild(row);
  }
}

async function loadSettings() {
  const res = await fetch("/config");
  const cfg = await res.json();
  document.getElementById("tracked-symbols-input").value = cfg.tracked_symbols.join(", ");
}

document.getElementById("save-settings-btn").addEventListener("click", async () => {
  const raw = document.getElementById("tracked-symbols-input").value;
  const symbols = raw.split(",").map((s) => s.trim()).filter(Boolean);
  const resultEl = document.getElementById("settings-result");

  try {
    const res = await fetch("/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tracked_symbols: symbols }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to save");
    resultEl.className = "success";
    resultEl.textContent = symbols.length ? "Saved." : "Saved — showing all assets.";
    await loadHoldings();
  } catch (err) {
    resultEl.className = "error";
    resultEl.textContent = err.message;
  }
});

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

loadSettings();
loadHoldings();
