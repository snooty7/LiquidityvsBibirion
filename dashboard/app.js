const chartDefs = [
  { tf: "M1", elementId: "chartM1", metaId: "metaM1" },
  { tf: "M5", elementId: "chartM5", metaId: "metaM5" },
  { tf: "M15", elementId: "chartM15", metaId: "metaM15" },
  { tf: "M30", elementId: "chartM30", metaId: "metaM30" },
];

const dashboardConfig = window.DASHBOARD_CONFIG || {};
const snapshotMode = dashboardConfig.snapshotMode || "api";
const dataBasePath = (dashboardConfig.dataBasePath || "data").replace(/\/+$/, "");
const charts = new Map();
const symbolSelect = document.getElementById("symbolSelect");
const refreshBtn = document.getElementById("refreshBtn");
const statusText = document.getElementById("statusText");
const generatedAt = document.getElementById("generatedAt");
const signalCards = document.getElementById("signalCards");
let staticManifest = null;

function createChart(container) {
  const chart = LightweightCharts.createChart(container, {
    layout: {
      background: { color: "#0b141d" },
      textColor: "#d8e6f0",
    },
    grid: {
      vertLines: { color: "rgba(41, 64, 84, 0.5)" },
      horzLines: { color: "rgba(41, 64, 84, 0.5)" },
    },
    rightPriceScale: {
      borderColor: "rgba(138, 160, 181, 0.15)",
    },
    timeScale: {
      borderColor: "rgba(138, 160, 181, 0.15)",
      timeVisible: true,
      secondsVisible: false,
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
    },
  });

  const series = chart.addCandlestickSeries({
    upColor: "#f4f7fb",
    downColor: "#5ca6ff",
    wickUpColor: "#f4f7fb",
    wickDownColor: "#5ca6ff",
    borderVisible: false,
    priceFormat: {
      type: "price",
      precision: 5,
      minMove: 0.00001,
    },
  });

  return { chart, series, priceLines: [], hasInitialFit: false, userRange: null };
}

function ensureCharts() {
  for (const def of chartDefs) {
    if (charts.has(def.tf)) continue;
    const container = document.getElementById(def.elementId);
    const bundle = createChart(container);
    bundle.chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) {
        bundle.userRange = range;
      }
    });
    charts.set(def.tf, bundle);
  }
}

function setStatus(text) {
  statusText.textContent = text;
}

function clearPriceLines(bundle) {
  for (const line of bundle.priceLines) {
    bundle.series.removePriceLine(line);
  }
  bundle.priceLines = [];
}

function restoreRange(bundle) {
  if (bundle.userRange) {
    bundle.chart.timeScale().setVisibleLogicalRange(bundle.userRange);
    return;
  }
  if (!bundle.hasInitialFit) {
    bundle.chart.timeScale().fitContent();
    bundle.hasInitialFit = true;
  }
}

function applyMarkers(bundle, markers) {
  bundle.series.setMarkers(
    markers.map((marker) => ({
      time: marker.time,
      position: marker.position,
      shape: marker.shape,
      color: marker.color,
      text: marker.text,
      size: marker.size || 0.7,
    })),
  );
}

function lineStyleValue(lineStyle) {
  if (lineStyle === "solid") return LightweightCharts.LineStyle.Solid;
  if (lineStyle === "dashed") return LightweightCharts.LineStyle.Dashed;
  return LightweightCharts.LineStyle.Dotted;
}

function applyLevels(bundle, levels) {
  clearPriceLines(bundle);
  for (const level of levels || []) {
    if (level.price == null) continue;
    const line = bundle.series.createPriceLine({
      price: level.price,
      color: level.color,
      lineWidth: 1,
      lineStyle: lineStyleValue(level.lineStyle),
      axisLabelVisible: true,
      axisLabelColor: level.color,
      axisLabelTextColor: "#071018",
      title: level.label,
    });
    bundle.priceLines.push(line);
  }
}

function renderSignals(items) {
  signalCards.innerHTML = "";
  if (!items.length) {
    signalCards.innerHTML = `<div class="signal-card"><div class="title">No recent signal events</div></div>`;
    return;
  }

  for (const item of items) {
    const card = document.createElement("article");
    card.className = "signal-card";
    card.style.borderLeftColor = item.color;
    const ts = new Date(item.ts).toLocaleString();
    card.innerHTML = `
      <div class="row">
        <div class="title">${item.symbol} ${item.timeframe || "-"}</div>
        <div>${item.event}</div>
      </div>
      <div class="meta">${ts} | ${item.side || "-"} | level=${item.level || "-"}</div>
      <div class="message">${item.message || ""}</div>
    `;
    signalCards.appendChild(card);
  }
}

async function loadStaticManifest() {
  if (snapshotMode !== "static") {
    return null;
  }
  if (staticManifest) {
    return staticManifest;
  }

  const response = await fetch(`${dataBasePath}/index.json?ts=${Date.now()}`);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Static manifest failed");
  }
  staticManifest = data;
  return data;
}

function ensureSymbolOptions(symbols, preferredSymbol) {
  if (!Array.isArray(symbols) || symbols.length === 0) {
    return preferredSymbol || "EURUSD";
  }
  if (!symbolSelect.options.length) {
    for (const item of symbols) {
      const option = document.createElement("option");
      option.value = item;
      option.textContent = item;
      symbolSelect.appendChild(option);
    }
  }
  const target = preferredSymbol && symbols.includes(preferredSymbol) ? preferredSymbol : symbols[0];
  symbolSelect.value = target;
  return target;
}

async function loadSnapshot() {
  let symbol = symbolSelect.value || "EURUSD";
  let response;

  if (snapshotMode === "static") {
    const manifest = await loadStaticManifest();
    symbol = ensureSymbolOptions(manifest?.symbols || [], symbol);
    setStatus(`loading ${symbol}`);
    response = await fetch(`${dataBasePath}/snapshot-${encodeURIComponent(symbol)}.json?ts=${Date.now()}`);
  } else {
    setStatus(`loading ${symbol}`);
    response = await fetch(`api/snapshot?symbol=${encodeURIComponent(symbol)}`);
  }

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.error || "Snapshot failed");
  }

  if (snapshotMode === "api") {
    symbol = ensureSymbolOptions(data.symbols || [], symbol);
  }

  generatedAt.textContent = `updated ${new Date(data.generated_at_utc).toLocaleString()}`;
  renderSignals(data.recentSignals || []);

  for (const def of chartDefs) {
    const bundle = charts.get(def.tf);
    const tfData = data.timeframes[def.tf];
    if (!bundle || !tfData) continue;
    bundle.series.setData(tfData.candles || []);
    applyMarkers(bundle, tfData.markers || []);
    applyLevels(bundle, tfData.levels || []);
    restoreRange(bundle);
    document.getElementById(def.metaId).textContent = `${tfData.candles.length} candles | ${tfData.markers.length} signals | ${((tfData.levels || []).length)} liquidity`;
  }

  setStatus(`live ${symbol}`);
}

async function refresh() {
  try {
    await loadSnapshot();
  } catch (error) {
    setStatus(String(error.message || error));
  }
}

function onResize() {
  for (const def of chartDefs) {
    const bundle = charts.get(def.tf);
    const container = document.getElementById(def.elementId);
    if (!bundle || !container) continue;
    bundle.chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
  }
}

ensureCharts();
window.addEventListener("resize", onResize);
refreshBtn.addEventListener("click", refresh);
symbolSelect.addEventListener("change", refresh);

setInterval(refresh, 15000);
refresh();
setTimeout(onResize, 50);
