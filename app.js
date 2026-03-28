const currency = new Intl.NumberFormat("en-ZA", {
  style: "currency",
  currency: "ZAR",
});

const state = {
  apiBaseUrl: "",
  summary: null,
};

const elements = {
  apiStatus: document.querySelector("#api-status"),
  apiUrl: document.querySelector("#api-url"),
  flash: document.querySelector("#flash"),
  refreshButton: document.querySelector("#refresh-button"),
  entryForm: document.querySelector("#entry-form"),
  receiptForm: document.querySelector("#receipt-form"),
  entryStore: document.querySelector("#entry-store"),
  entryStoreCustomWrap: document.querySelector("#entry-store-custom-wrap"),
  entryStoreCustom: document.querySelector("#entry-store-custom"),
  receiptStore: document.querySelector("#receipt-store"),
  receiptStoreCustomWrap: document.querySelector("#receipt-store-custom-wrap"),
  receiptStoreCustom: document.querySelector("#receipt-store-custom"),
  claimedWrap: document.querySelector("#claimed-price-wrap"),
  isSpecial: document.querySelector("#is-special"),
  monthlySpend: document.querySelector("#monthly-spend"),
  monthlyDelta: document.querySelector("#monthly-delta"),
  uniqueItems: document.querySelector("#unique-items"),
  fakeSpecials: document.querySelector("#fake-specials"),
  storeBreakdown: document.querySelector("#store-breakdown"),
  recentEntries: document.querySelector("#recent-entries"),
  specialsList: document.querySelector("#specials-list"),
  photoScanButton: document.querySelector("#photo-scan-button"),
};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  setTodayDefaults();
  wireEvents();

  try {
    state.apiBaseUrl = await loadApiBaseUrl();
    elements.apiStatus.textContent = "Connected";
    elements.apiUrl.textContent = state.apiBaseUrl;
    await refreshDashboard();
  } catch (error) {
    console.error(error);
    elements.apiStatus.textContent = "Missing backend URL";
    elements.apiUrl.textContent =
      "Set GROCERY_API_BASE_URL in Vercel so the frontend can reach AWS.";
    showFlash(error.message || "Unable to connect to the backend.");
  }
}

function wireEvents() {
  elements.isSpecial.addEventListener("change", () => {
    elements.claimedWrap.classList.toggle("hidden", !elements.isSpecial.checked);
  });

  elements.entryStore.addEventListener("change", () => {
    toggleCustomStore(elements.entryStore, elements.entryStoreCustomWrap, elements.entryStoreCustom);
  });

  elements.receiptStore.addEventListener("change", () => {
    toggleCustomStore(
      elements.receiptStore,
      elements.receiptStoreCustomWrap,
      elements.receiptStoreCustom,
    );
  });

  elements.entryForm.addEventListener("submit", handleEntrySubmit);
  elements.receiptForm.addEventListener("submit", handleReceiptSubmit);
  elements.refreshButton.addEventListener("click", refreshDashboard);
  elements.photoScanButton.addEventListener("click", handleUploadUrl);
}

async function loadApiBaseUrl() {
  const response = await fetch("/api/config");
  const data = await response.json();
  if (!response.ok || !data.apiBaseUrl) {
    throw new Error(data.error || "The Vercel config endpoint is not ready.");
  }
  return data.apiBaseUrl.replace(/\/$/, "");
}

async function refreshDashboard() {
  const summary = await apiFetch("/summary");
  state.summary = summary;
  renderSummary(summary);
}

async function handleEntrySubmit(event) {
  event.preventDefault();
  try {
    const formData = new FormData(elements.entryForm);
    const payload = {
      itemName: formData.get("itemName"),
      store: getSelectedStore(
        elements.entryStore,
        elements.entryStoreCustom,
        "Please choose a shop.",
      ),
      price: Number(formData.get("price")),
      purchasedOn: formData.get("purchasedOn"),
      notes: formData.get("notes"),
      isSpecial: elements.isSpecial.checked,
    };

    if (elements.isSpecial.checked && formData.get("claimedOriginalPrice")) {
      payload.claimedOriginalPrice = Number(formData.get("claimedOriginalPrice"));
    }

    const result = await apiFetch("/entries", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    elements.entryForm.reset();
    setTodayDefaults();
    elements.claimedWrap.classList.add("hidden");
    toggleCustomStore(elements.entryStore, elements.entryStoreCustomWrap, elements.entryStoreCustom);
    showFlash(`Saved ${result.entry.itemName}.`);
    await refreshDashboard();
  } catch (error) {
    showFlash(error.message || "Unable to save the item.");
  }
}

async function handleReceiptSubmit(event) {
  event.preventDefault();
  try {
    const formData = new FormData(elements.receiptForm);
    const payload = {
      store: getSelectedStore(
        elements.receiptStore,
        elements.receiptStoreCustom,
        "Please choose a shop for the receipt import.",
      ),
      purchasedOn: formData.get("purchasedOn"),
      receiptText: formData.get("receiptText"),
    };

    const result = await apiFetch("/receipts/text", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    elements.receiptForm.reset();
    setTodayDefaults();
    toggleCustomStore(
      elements.receiptStore,
      elements.receiptStoreCustomWrap,
      elements.receiptStoreCustom,
    );
    showFlash(`Imported ${result.count} receipt lines.`);
    await refreshDashboard();
  } catch (error) {
    showFlash(error.message || "Unable to import the receipt.");
  }
}

async function handleUploadUrl() {
  const result = await apiFetch("/upload-url", {
    method: "POST",
    body: JSON.stringify({
      fileName: "receipt-photo.jpg",
      fileType: "image/jpeg",
    }),
  });

  showFlash("Signed upload URL generated. Wire this into a file picker next.");
  elements.apiUrl.textContent = `${state.apiBaseUrl} | Upload key: ${result.objectKey}`;
}

async function apiFetch(path, options = {}) {
  const response = await fetch(`${state.apiBaseUrl}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Request failed.");
  }
  return data;
}

function renderSummary(summary) {
  elements.monthlySpend.textContent = formatMoney(summary.monthlySpend);

  const delta = Number(summary.monthOverMonthDelta || 0);
  const deltaLabel =
    delta === 0
      ? "Flat vs last month"
      : `${delta > 0 ? "+" : "-"}${formatMoney(Math.abs(delta))} vs last month`;
  elements.monthlyDelta.textContent = deltaLabel;

  elements.uniqueItems.textContent = summary.uniqueItemsTracked;
  elements.fakeSpecials.textContent = summary.fakeSpecialsCaught;

  renderStoreBreakdown(summary.storeBreakdown || []);
  renderRecentEntries(summary.recentEntries || []);
  renderSpecials(summary.specials || []);
}

function renderStoreBreakdown(items) {
  if (!items.length) {
    elements.storeBreakdown.className = "bars empty-state";
    elements.storeBreakdown.textContent = "No spend data yet.";
    return;
  }

  const maxSpend = Math.max(...items.map((item) => item.spend), 1);
  elements.storeBreakdown.className = "bars";
  elements.storeBreakdown.innerHTML = items
    .map(
      (item) => `
        <div class="bar-row">
          <div class="bar-meta">
            <span>${escapeHtml(item.store)}</span>
            <strong>${formatMoney(item.spend)}</strong>
          </div>
          <div class="bar-track">
            <div class="bar-fill" style="width:${(item.spend / maxSpend) * 100}%"></div>
          </div>
        </div>
      `
    )
    .join("");
}

function renderRecentEntries(items) {
  if (!items.length) {
    elements.recentEntries.className = "recent-list empty-state";
    elements.recentEntries.textContent = "No price entries yet.";
    return;
  }

  elements.recentEntries.className = "recent-list";
  elements.recentEntries.innerHTML = items
    .map((item) => {
      const change = item.priceChange || { direction: "new", difference: 0 };
      const trendLabel =
        change.direction === "up"
          ? `▲ ${formatMoney(Math.abs(change.difference))}`
          : change.direction === "down"
            ? `▼ ${formatMoney(Math.abs(change.difference))}`
            : change.direction === "flat"
              ? "• same price"
              : "• first entry";

      return `
        <div class="recent-row">
          <div>
            <strong>${escapeHtml(item.itemName)}</strong>
            <div class="muted">${escapeHtml(item.store)} • ${item.purchasedOn}</div>
          </div>
          <div>
            <strong>${formatMoney(item.price)}</strong>
            <div class="trend ${change.direction}">${trendLabel}</div>
          </div>
        </div>
      `;
    })
    .join("");
}

function renderSpecials(items) {
  if (!items.length) {
    elements.specialsList.className = "specials-list empty-state";
    elements.specialsList.textContent =
      "Special-marked items will appear here once you log them.";
    return;
  }

  elements.specialsList.className = "specials-list";
  elements.specialsList.innerHTML = items
    .map((item) => {
      const analysis = item.specialAnalysis;
      const details = [];
      if (analysis?.baselinePrice != null) {
        details.push(`Baseline ${formatMoney(analysis.baselinePrice)}`);
      }
      if (analysis?.actualDiscountPercent != null) {
        details.push(`Actual ${analysis.actualDiscountPercent}% off`);
      }
      if (analysis?.claimedDiscountPercent != null) {
        details.push(`Claimed ${analysis.claimedDiscountPercent}% off`);
      }

      return `
        <article class="special-card">
          <span class="badge ${analysis.verdict}">${analysis.label}</span>
          <strong>${escapeHtml(item.itemName)} • ${formatMoney(item.price)}</strong>
          <div class="muted">${escapeHtml(item.store)} • ${item.purchasedOn}</div>
          <p>${escapeHtml(analysis.message)}</p>
          <div class="muted">${escapeHtml(details.join(" • "))}</div>
        </article>
      `;
    })
    .join("");
}

function setTodayDefaults() {
  const today = new Date().toISOString().slice(0, 10);
  document.querySelectorAll('input[type="date"]').forEach((input) => {
    if (!input.value) {
      input.value = today;
    }
  });
}

function toggleCustomStore(selectElement, wrapElement, inputElement) {
  const showCustom = selectElement.value === "Other";
  wrapElement.classList.toggle("hidden", !showCustom);
  inputElement.required = showCustom;
  if (!showCustom) {
    inputElement.value = "";
  }
}

function getSelectedStore(selectElement, inputElement, emptyMessage) {
  if (!selectElement.value) {
    throw new Error(emptyMessage);
  }

  if (selectElement.value !== "Other") {
    return selectElement.value;
  }

  const customValue = inputElement.value.trim();
  if (!customValue) {
    throw new Error("Please enter the custom shop name.");
  }

  return customValue;
}

function formatMoney(value) {
  return currency.format(Number(value || 0));
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function showFlash(message) {
  elements.flash.textContent = message;
  elements.flash.classList.remove("hidden");
  window.clearTimeout(showFlash.timer);
  showFlash.timer = window.setTimeout(() => {
    elements.flash.classList.add("hidden");
  }, 3200);
}
