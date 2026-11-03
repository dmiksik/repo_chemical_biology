// Previewer of mzML files: paged list of spectra and a stick plot of the
// selected spectrum, loaded from the spectra API (common/spectra/views.py).
//
// Deep link: ?spectrum=scan:95 (or index:94) in the URL of the previewer or of
// the record page that embeds it.

import "./mzml-previewer.css";

const PAGE_SIZE = 50;
const LABELLED_PEAKS = 8;
// approximate size of a peak label in plot units
const LABEL_WIDTH = 56;
const LABEL_HEIGHT = 14;
const RETRY_MS = 5000;

const SVG_NS = "http://www.w3.org/2000/svg";
const PLOT = { width: 900, height: 320, left: 64, right: 16, top: 16, bottom: 40 };

function el(tag, attrs = {}, text = null) {
  const node = tag.startsWith("svg:")
    ? document.createElementNS(SVG_NS, tag.slice(4))
    : document.createElement(tag);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
  if (text !== null) node.textContent = text;
  return node;
}

function formatNumber(value, digits) {
  return value === null || value === undefined ? "" : Number(value).toFixed(digits);
}

// "Nice" axis ticks covering [min, max]
function ticks(min, max, count = 6) {
  const span = max - min || 1;
  const step0 = span / count;
  const magnitude = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 5, 10].map((m) => m * magnitude).find((s) => s >= step0);
  const result = [];
  for (let t = Math.ceil(min / step) * step; t <= max; t += step) result.push(t);
  return result;
}

function readDeepLink() {
  const sources = [window.location.search];
  try {
    // the previewer is embedded in an iframe of the record page (same origin)
    if (window.parent !== window) sources.push(window.parent.location.search);
  } catch (e) {
    // cross-origin parent, ignore
  }
  for (const search of sources) {
    const value = new URLSearchParams(search).get("spectrum");
    const match = value && value.match(/^(scan|index|nativeId):(.+)$/);
    if (match) return { indexType: match[1], value: match[2] };
  }
  return null;
}

class SpectraPreviewer {
  constructor(root) {
    this.root = root;
    this.api = root.dataset.api.replace(/\/$/, "");
    this.baseUrl =
      `${this.api}/dataset/${encodeURIComponent(root.dataset.record)}` +
      `/files/${encodeURIComponent(root.dataset.file)}/spectra`;
    this.page = 1;
    this.total = 0;
    this.hits = [];
    this.current = null;

    this.q = (selector) => root.querySelector(selector);
    this.message = this.q(".spectra-message");
    this.list = this.q(".spectra-list");
    this.detail = this.q(".spectra-detail");
    this.msLevel = this.q(".spectra-ms-level");

    this.msLevel.addEventListener("change", () => {
      this.page = 1;
      this.loadPage();
    });
    this.q(".spectra-page-prev").addEventListener("click", () => this.changePage(-1));
    this.q(".spectra-page-next").addEventListener("click", () => this.changePage(1));
    this.q(".spectra-prev").addEventListener("click", () => this.step(-1));
    this.q(".spectra-next").addEventListener("click", () => this.step(1));
    this.q(".spectra-copy-usi").addEventListener("click", () => this.copyUsi());
  }

  async start() {
    if (this.root.dataset.draft === "true") {
      this.showMessage("info", "Spectra are indexed when the record is published.");
      return;
    }
    const link = readDeepLink();
    if (link) {
      // show all MS levels so that the linked spectrum is in the list
      this.msLevel.value = "";
      await this.showSpectrum(link.indexType, link.value);
    }
    await this.loadPage();
  }

  async fetchJson(url) {
    const response = await fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(body.title || body.message || response.statusText);
      error.status = response.status;
      error.body = body;
      throw error;
    }
    return body;
  }

  handleError(error) {
    if (error.status === 409 && error.body.indexing_status === "PENDING") {
      this.showMessage("info", "Spectra of this file are being indexed, please wait...");
      setTimeout(() => this.loadPage(), RETRY_MS);
    } else if (error.status === 409) {
      this.showMessage("warning", `Spectra of this file are not available: ${error.body.detail || error.message}`);
    } else if (error.status === 403) {
      this.showMessage("warning", "You do not have access to the files of this record.");
    } else {
      this.showMessage("negative", error.message);
    }
  }

  showMessage(kind, text) {
    this.message.className = `spectra-message ui message ${kind}`;
    this.message.textContent = text;
  }

  hideMessage() {
    this.message.className = "spectra-message ui message hidden";
  }

  async loadPage() {
    const params = new URLSearchParams({ page: this.page, size: PAGE_SIZE });
    if (this.msLevel.value) params.set("ms_level", this.msLevel.value);
    let result;
    try {
      result = await this.fetchJson(`${this.baseUrl}?${params}`);
    } catch (error) {
      this.handleError(error);
      return;
    }
    this.hideMessage();
    this.total = result.total;
    this.hits = result.hits;
    this.renderList();
    if (!this.current && this.hits.length) {
      this.showSpectrum("index", this.hits[0].index);
    }
  }

  changePage(delta) {
    const pages = Math.max(1, Math.ceil(this.total / PAGE_SIZE));
    const page = Math.min(pages, Math.max(1, this.page + delta));
    if (page !== this.page) {
      this.page = page;
      this.loadPage();
    }
  }

  renderList() {
    const tbody = this.q(".spectra-table tbody");
    tbody.replaceChildren(
      ...this.hits.map((hit) => {
        const row = el("tr", { tabindex: "0", "data-index": hit.index });
        if (this.current && this.current.index === hit.index) row.classList.add("active");
        [
          hit.scan ?? hit.native_id,
          hit.ms_level,
          formatNumber(hit.rt === null ? null : hit.rt / 60, 3),
          formatNumber(hit.precursor_mz, 4),
          hit.charge ?? "",
        ].forEach((value) => row.appendChild(el("td", {}, String(value ?? ""))));
        const select = () => this.showSpectrum("index", hit.index);
        row.addEventListener("click", select);
        row.addEventListener("keydown", (event) => event.key === "Enter" && select());
        return row;
      })
    );
    const pages = Math.max(1, Math.ceil(this.total / PAGE_SIZE));
    this.q(".spectra-total").textContent = `${this.total} spectra`;
    this.q(".spectra-page").textContent = `${this.page} / ${pages}`;
    this.list.classList.remove("hidden");
  }

  async showSpectrum(indexType, value) {
    let spectrum;
    const url = `${this.baseUrl}/${indexType}/${encodeURIComponent(value)}`;
    try {
      spectrum = await this.fetchJson(url);
    } catch (error) {
      this.handleError(error);
      return;
    }
    const attributes = Object.fromEntries(spectrum.attributes.map((a) => [a.accession, a.value]));
    // spectrum.index is the position in the file, used for previous/next navigation
    this.current = { ...spectrum, url };

    const title = [`MS${attributes["MS:1000511"] || "?"}`];
    if (attributes["MS:1000744"]) title.push(`precursor m/z ${formatNumber(attributes["MS:1000744"], 4)}`);
    if (attributes["MS:1000041"]) title.push(`charge ${attributes["MS:1000041"]}+`);
    title.push(`${spectrum.mzs.length} peaks`);
    this.q(".spectra-title").textContent = title.join(" · ");
    this.q(".spectra-usi").textContent = spectrum.usi;
    this.q(".spectra-json").href = `${this.api}/proxi/v0.1/spectra?usi=${encodeURIComponent(spectrum.usi)}`;

    this.renderPlot(spectrum.mzs, spectrum.intensities);
    this.renderAttributes(spectrum.attributes);
    this.detail.classList.remove("hidden");
    this.q(".spectra-table tbody")
      .querySelectorAll("tr")
      .forEach((row) => row.classList.toggle("active", Number(row.dataset.index) === this.current.index));
  }

  step(delta) {
    if (!this.current) return;
    const position = this.hits.findIndex((h) => h.index === this.current.index);
    if (position >= 0 && this.hits[position + delta]) {
      this.showSpectrum("index", this.hits[position + delta].index);
    } else {
      // outside of the listed page: step in the file regardless of MS level
      this.showSpectrum("index", Math.max(0, this.current.index + delta));
    }
  }

  async copyUsi() {
    const usi = this.current && this.current.usi;
    if (!usi) return;
    const button = this.q(".spectra-copy-usi");
    try {
      await navigator.clipboard.writeText(usi);
    } catch (e) {
      const range = document.createRange();
      range.selectNodeContents(this.q(".spectra-usi"));
      window.getSelection().removeAllRanges();
      window.getSelection().addRange(range);
      document.execCommand("copy");
    }
    button.classList.add("positive");
    setTimeout(() => button.classList.remove("positive"), 1500);
  }

  renderPlot(mzs, intensities) {
    const container = this.q(".spectra-plot");
    const { width, height, left, right, top, bottom } = PLOT;
    const svg = el("svg:svg", { viewBox: `0 0 ${width} ${height}`, role: "img", class: "spectra-svg" });
    if (!mzs.length) {
      container.replaceChildren(el("p", {}, "The spectrum has no peaks."));
      return;
    }

    const maxIntensity = Math.max(...intensities) || 1;
    const minMz = Math.min(...mzs);
    const maxMz = Math.max(...mzs);
    const pad = (maxMz - minMz) * 0.03 || 1;
    const x0 = minMz - pad;
    const x1 = maxMz + pad;
    const x = (mz) => left + ((mz - x0) / (x1 - x0)) * (width - left - right);
    const y = (relative) => height - bottom - (relative / 100) * (height - top - bottom);

    // axes and ticks
    svg.appendChild(el("svg:line", { x1: left, y1: y(0), x2: width - right, y2: y(0), class: "axis" }));
    svg.appendChild(el("svg:line", { x1: left, y1: y(0), x2: left, y2: y(100), class: "axis" }));
    ticks(x0, x1).forEach((t) => {
      svg.appendChild(el("svg:line", { x1: x(t), y1: y(0), x2: x(t), y2: y(0) + 4, class: "axis" }));
      svg.appendChild(el("svg:text", { x: x(t), y: y(0) + 16, class: "tick", "text-anchor": "middle" }, String(+t.toFixed(4))));
    });
    [0, 25, 50, 75, 100].forEach((t) => {
      svg.appendChild(el("svg:line", { x1: left - 4, y1: y(t), x2: left, y2: y(t), class: "axis" }));
      svg.appendChild(el("svg:text", { x: left - 8, y: y(t) + 4, class: "tick", "text-anchor": "end" }, `${t}`));
    });
    svg.appendChild(el("svg:text", { x: (left + width - right) / 2, y: height - 4, class: "label", "text-anchor": "middle" }, "m/z"));
    svg.appendChild(
      el("svg:text", { x: 14, y: (top + height - bottom) / 2, class: "label", "text-anchor": "middle", transform: `rotate(-90 14 ${(top + height - bottom) / 2})` }, "Relative intensity (%)")
    );

    // peaks
    const peaks = mzs.map((mz, i) => ({ mz, relative: (intensities[i] / maxIntensity) * 100, intensity: intensities[i] }));
    peaks.forEach((peak) => {
      const line = el("svg:line", { x1: x(peak.mz), y1: y(0), x2: x(peak.mz), y2: y(peak.relative), class: "peak" });
      line.appendChild(el("svg:title", {}, `m/z ${peak.mz.toFixed(4)}\nintensity ${peak.intensity.toExponential(3)} (${peak.relative.toFixed(1)} %)`));
      svg.appendChild(line);
    });
    // label the most intense peaks, skipping labels that would overlap a stronger one
    const placed = [];
    [...peaks]
      .sort((a, b) => b.intensity - a.intensity)
      .forEach((peak) => {
        if (placed.length >= LABELLED_PEAKS) return;
        const px = x(peak.mz);
        const py = y(peak.relative) - 4;
        const overlaps = placed.some((p) => Math.abs(p.x - px) < LABEL_WIDTH && Math.abs(p.y - py) < LABEL_HEIGHT);
        if (overlaps) return;
        placed.push({ x: px, y: py });
        svg.appendChild(el("svg:text", { x: px, y: py, class: "peak-label", "text-anchor": "middle" }, peak.mz.toFixed(4)));
      });
    container.replaceChildren(svg);
  }

  renderAttributes(attributes) {
    const details = el("details");
    details.appendChild(el("summary", {}, `Attributes (${attributes.length})`));
    const table = el("table", { class: "ui very compact basic table" });
    const tbody = el("tbody");
    attributes.forEach((a) => {
      const row = el("tr");
      row.appendChild(el("td", {}, a.accession));
      row.appendChild(el("td", {}, a.name));
      row.appendChild(el("td", {}, a.value ?? ""));
      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    details.appendChild(table);
    this.q(".spectra-attributes").replaceChildren(details);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const root = document.getElementById("spectra-previewer");
  if (root) new SpectraPreviewer(root).start();
});
