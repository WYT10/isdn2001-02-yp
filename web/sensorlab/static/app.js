"use strict";
(function () {
  const $ = (id) => document.getElementById(id);
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const state = { data: null, metric: "frequency_hz", busy: false, timer: null };
  const format = (value, digits = 2) => Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: digits }) : "\u2014";
  const time = (value) => value ? new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "\u2014";
  const set = (id, value) => { $(id).textContent = value; };
  function parameters() {
    const params = new URLSearchParams({ hours: $("window-select").value });
    if ($("device-select").value) params.set("device_id", $("device-select").value);
    return params;
  }
  async function api(url, options = {}) {
    const response = await fetch(url, { credentials: "same-origin", cache: "no-store", ...options });
    if (response.status === 401) { window.location.assign("/"); throw new Error("Please sign in again."); }
    const body = await response.json();
    if (!response.ok) throw new Error(body.message || body.error || "The request could not be completed.");
    return body;
  }
  function svgNode(name, attrs, text) {
    const element = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.entries(attrs || {}).forEach(([key, value]) => element.setAttribute(key, value));
    if (text !== undefined) element.textContent = text;
    return element;
  }
  function chart() {
    const svg = $("flow-chart");
    svg.replaceChildren();
    const data = state.data ? state.data.series : [];
    const points = data.filter((item) => Number.isFinite(item[state.metric]));
    const maximum = Math.max(1, ...points.map((item) => item[state.metric])) * 1.15;
    const width = Math.max(240, Math.round(svg.clientWidth || 960));
    const height = width < 520 ? 245 : 300;
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    const left = 42, right = width - 14, top = 20, bottom = height - 42;
    for (let i = 0; i <= 4; i++) {
      const y = top + (bottom - top) * i / 4;
      svg.append(svgNode("line", { x1: left, y1: y, x2: right, y2: y, class: "chart-grid" }));
      svg.append(svgNode("text", { x: left - 11, y: y + 4, "text-anchor": "end", class: "chart-label" }, (maximum > 1e6 ? format(maximum * (1 - i / 4) / 1e6, 1) + "M" : maximum > 1000 ? format(maximum * (1 - i / 4) / 1000, 1) + "k" : format(maximum * (1 - i / 4), 1))));
    }
    const empty = !points.length;
    $("chart-empty").hidden = !empty;
    if (empty) {
      $("chart-empty").querySelector("h3").textContent = data.length && state.metric === "flow_lpm" ? "Calibration is still needed" : "Your stream starts here";
      $("chart-empty").querySelector("p").textContent = data.length && state.metric === "flow_lpm" ? "Raw frequency is available. Flow values have not been supplied." : "Connect a device and send readings to see the signal.";
      return;
    }
    // Anchor each boot to its latest receipt, preserving sample spacing across HTTP batches.
    const anchors = new Map();
    data.forEach(item => anchors.set(item.boot_id, item));
    const stamp = item => {
      const anchor = anchors.get(item.boot_id);
      return new Date(anchor.received_at).getTime() + (item.uptime_us - anchor.uptime_us) / 1000;
    };
    const first = Math.min(...data.map(stamp)), last = Math.max(...data.map(stamp));
    const x = item => last === first ? (left + right) / 2 : left + (stamp(item) - first) / (last - first) * (right - left);
    const y = (item) => bottom - item[state.metric] / maximum * (bottom - top);
    let path = "", drawing = false, previous = null, gaps = false;
    data.forEach((item) => {
      if (previous && (item.boot_id !== previous.boot_id || item.seq !== previous.seq + 1)) {
        drawing = false; gaps = true;
      }
      previous = item;
      if (!Number.isFinite(item[state.metric])) { drawing = false; gaps = true; return; }
      path += (drawing ? " L " : " M ") + x(item).toFixed(2) + " " + y(item).toFixed(2);
      drawing = true;
    });
    if (points.length > 1 && points.length === data.length && !gaps) {
      const area = path + " L " + x(points[points.length - 1]) + " " + bottom + " L " + x(points[0]) + " " + bottom + " Z";
      svg.append(svgNode("path", { d: area, class: "chart-area" }));
    }
    svg.append(svgNode("path", { d: path, class: "chart-line" }));
    const current = points[points.length - 1];
    svg.append(svgNode("circle", { cx: x(current), cy: y(current), r: 4, fill: "#087f75", stroke: "white", "stroke-width": 2 }));
    const indices = [...new Set(width < 520 ? [0, data.length - 1] : [0, Math.floor((data.length - 1) / 2), data.length - 1])];
    indices.forEach((index) => svg.append(svgNode("text", { x: x(data[index]), y: height - 12, "text-anchor": index === 0 ? "start" : index === data.length - 1 ? "end" : "middle", class: "chart-label" }, time(stamp(data[index])))));
    svg.setAttribute("aria-label", (state.metric === "frequency_hz" ? "Frequency in hertz" : "Flow in litres per minute") + ", " + points.length + " samples plotted by device elapsed time, anchored to server receipt");
    set("chart-caption", data.length + " latest samples \u00b7 device timing / receipt anchor");
  }
  function render(data) {
    state.data = data;
    const select = $("device-select");
    select.replaceChildren();
    if (!data.devices.length) select.add(new Option("No devices yet", ""));
    data.devices.forEach((device) => select.add(new Option(device.label, device.device_id)));
    select.value = data.selected_device || "";
    const device = data.devices.find((item) => item.device_id === data.selected_device);
    $("demo-banner").hidden = !(device && device.is_demo);
    const latest = data.latest;
    const summary = data.summary;
    const meta = latest && latest.metadata || {};
    const gaps = data.series.reduce((sum, item, i, all) => i && item.boot_id === all[i-1].boot_id ? sum + Math.max(0, item.seq - all[i-1].seq - 1) : sum, 0);
    set("board-value", meta.board || "Board information pending");
    set("gpio-value", Number.isInteger(meta.gpio) ? "GPIO" + meta.gpio : "\u2014");
    set("report-value", meta.report_ms ? format(1000 / meta.report_ms, 1) + "/s \u00b7 " + meta.report_ms + " ms" : "\u2014");
    set("dropped-value", format(meta.upload_dropped, 0));
    set("gaps-value", format(gaps, 0));
    set("capture-state", latest ? format(latest.total_pulses, 0) + " pulses this boot" : "Waiting for device");
    set("capture-detail", meta.board ? meta.board + " \u00b7 GPIO" + meta.gpio : "Hardware pulse counter");
    set("delivery-detail", Number.isInteger(meta.upload_dropped) ? format(meta.upload_dropped, 0) + " dropped / boot \u00b7 " + format(meta.queue_depth, 0) + " queued at capture" : "Authenticated HTTPS batches");
    set("device-name", device ? device.label : "No device connected");
    set("flow-value", format(latest && latest.flow_lpm));
    set("frequency-value", format(latest && latest.frequency_hz));
    set("volume-value", format(latest && latest.total_l, 3));
    set("sample-count", format(summary.sample_count || 0, 0));
    set("sample-note", "Selected window: " + data.window_hours + " hours");
    const calibrated = latest && latest.flow_lpm !== null;
    set("calibration-note", calibrated ? "Flow reported by device" : "Calibration required");
    set("calibration-value", calibrated ? "Flow supplied" : "Unknown");
    set("pulse-total", latest ? format(latest.total_pulses, 0) + " cumulative pulses this boot" : "No pulse count available");
    set("mean-hz", format(summary.mean_hz)); set("peak-hz", format(summary.peak_hz));
    set("calibrated-count", format(summary.calibrated_samples || 0, 0));
    const pulse = latest && latest.pulse;
    set("duty-value", pulse ? format(pulse.duty_pct, 1) + "%" : "\u2014");
    set("timing-value", pulse ? format(pulse.high_us, 1) + " / " + format(pulse.low_us, 1) + " \u00b5s" : "\u2014");
    set("uptime-value", latest ? format(latest.uptime_us / 1e6, 1) + " s" : "\u2014");
    const age = latest ? Math.max(0, (new Date(data.server_time) - new Date(latest.received_at)) / 1000) : null;
    const demo = device && device.is_demo;
    const status = $("stream-status");
    status.className = "status-pill" + (!demo && age !== null && age <= 15 ? " live" : age !== null ? " stale" : "");
    status.textContent = demo ? "Simulation" : age === null ? "Waiting for data" : age <= 15 ? "Receiving data" : "Device quiet";
    set("last-updated", age === null ? "No measurements received" : "Last received " + (age < 60 ? Math.floor(age) + "s ago" : format(age / 60, 0) + "m ago"));
    set("delivery-state", demo ? "Simulation" : age === null ? "No uploads yet" : age <= 15 ? "Uploads arriving" : "No recent delivery");
    set("release-value", data.release.slice(0, 10));
    const rows = data.series.slice(-8).reverse();
    const body = $("readings-body"); body.replaceChildren();
    if (!rows.length) { const tr = document.createElement("tr"), td = document.createElement("td"); td.colSpan = 5; td.className = "empty-row"; td.textContent = "No measurements in this window."; tr.append(td); body.append(tr); }
    rows.forEach((item) => {
      const tr = document.createElement("tr");
      [time(item.received_at), format(item.frequency_hz) + " Hz", item.flow_lpm === null ? "\u2014" : format(item.flow_lpm) + " L/min", format(item.pulses, 0), "#" + item.seq].forEach((text) => { const td = document.createElement("td"); td.textContent = text; tr.append(td); });
      body.append(tr);
    });
    const params = new URLSearchParams();
    if (data.selected_device) params.set("device_id", data.selected_device);
    params.set("since", new Date(new Date(data.server_time).getTime() - data.window_hours * 3600000).toISOString());
    $("export-link").href = "/api/v1/readings.csv?" + params;
    chart();
  }
  async function refresh() {
    if (state.busy) return;
    state.busy = true; $("refresh-button").disabled = true;
    try {
      render(await api("/api/v1/dashboard?" + parameters()));
      $("connection-alert").hidden = true;
      const ready = await api("/readyz");
      set("storage-state", ready.status === "ok" ? "Database ready" : "Needs attention");
      set("system-health", ready.status === "ok" ? "Service healthy \u00b7 database ready" : "Service needs attention");
    } catch (error) {
      $("connection-alert").textContent = "Refresh unavailable. " + error.message;
      $("connection-alert").hidden = false;
      set("storage-state", "Check unavailable");
      set("delivery-state", "Check unavailable");
      set("system-health", "Connection unavailable");
      $("stream-status").className = "status-pill stale";
      set("stream-status", "Connection unavailable");
    } finally { state.busy = false; $("refresh-button").disabled = false; }
  }
  $("device-select").addEventListener("change", refresh);
  $("window-select").addEventListener("change", refresh);
  $("refresh-button").addEventListener("click", refresh);
  document.querySelectorAll("[data-metric]").forEach((button) => button.addEventListener("click", () => {
    state.metric = button.dataset.metric;
    document.querySelectorAll("[data-metric]").forEach((item) => { item.classList.toggle("selected", item === button); item.setAttribute("aria-pressed", String(item === button)); });
    chart();
  }));
  $("feedback-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.currentTarget.querySelector("button[type='submit']"); button.disabled = true;
    set("feedback-status", "Saving\u2026");
    try {
      const rating = $("feedback-rating").value;
      const result = await api("/api/v1/feedback", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify({ category: $("feedback-category").value, message: $("feedback-message").value, rating: rating ? Number(rating) : null, device_id: state.data ? state.data.selected_device : null, reading_id: state.data && state.data.latest ? state.data.latest.id : null }) });
      $("feedback-message").value = ""; set("feedback-status", "Saved observation #" + result.id);
    } catch (error) { set("feedback-status", error.message); }
    finally { button.disabled = false; }
  });
  window.addEventListener("resize", () => window.requestAnimationFrame(chart));
  refresh();
  state.timer = window.setInterval(() => { if (!document.hidden) refresh(); }, 3000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
}());
