"use strict";
(function () {
  const DATA = JSON.parse(document.getElementById("portal-data").textContent);
  const SVGNS = "http://www.w3.org/2000/svg";

  const COLORS = {
    System: "#38bdf8", Module: "#a7f3d0", Technology: "#fde68a", APIEndpoint: "#fca5a5",
    DataModel: "#c4b5fd", Database: "#93c5fd", DataStore: "#93c5fd", DeploymentUnit: "#fdba74",
    Config: "#f9a8d4", ExternalService: "#fcd34d", File: "#bae6fd", Class: "#ddd6fe",
    Function: "#fecaca", Concept: "#94a3b8", BusinessEntity: "#86efac", Match: "#38bdf8",
    Team: "#a7f3d0", League: "#facc15", Player: "#fda4af", Prediction: "#c4b5fd",
    Market: "#fb923c", Bet: "#f97316", ModelArtifact: "#93c5fd",
  };
  const DEFAULT_COLOR = "#94a3b8";

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  }
  function el(tag, attrs, text) {
    const node = document.createElement(tag);
    if (attrs) for (const key in attrs) node.setAttribute(key, attrs[key]);
    if (text != null) node.textContent = text;
    return node;
  }
  function link(url, text) {
    return url ? `<a href="${esc(url)}">${esc(text)}</a>` : esc(text);
  }

  // ---------- shared chrome ----------
  function renderMetrics(stats) {
    const host = document.getElementById("metrics");
    if (!stats) return;
    const fmt = (n) => Number(n).toLocaleString("en-US");
    const items = [];
    if (stats.entities != null) items.push(["Entities", fmt(stats.entities)]);
    if (stats.assertions != null) items.push(["Relationships", fmt(stats.assertions)]);
    if (stats.sources != null) items.push(["Sources", fmt(stats.sources)]);
    if (stats.shown_nodes != null)
      items.push(["Shown", fmt(stats.shown_nodes) + " <small>of " + fmt(stats.total_nodes) + "</small>"]);
    if (stats.communities != null) items.push(["Communities", fmt(stats.communities)]);
    host.innerHTML = items
      .map((it) => `<div class="metric"><div class="value">${it[1]}</div><div class="label">${it[0]}</div></div>`)
      .join("");
  }

  function artifactLinks(artifacts) {
    if (!artifacts || !artifacts.length) return '<span class="card-sub">None generated yet.</span>';
    return artifacts.map((a) => `<div><a href="${esc(a.url)}">${esc(a.label)} →</a></div>`).join("");
  }

  renderMetrics(DATA.stats);
  const fullLink = document.getElementById("full-graph-link");
  if (fullLink && DATA.full_graph_url) fullLink.href = DATA.full_graph_url;
  const artifactHost = document.getElementById("artifacts");
  if (artifactHost) artifactHost.innerHTML = artifactLinks(DATA.artifacts);

  if (DATA.page === "intelligence") {
    renderIntelligence(DATA.intelligence);
    return;
  }
  if (DATA.page === "changes") {
    renderChanges(DATA.changes);
    return;
  }
  document.getElementById("graph-app").hidden = false;
  startGraph(DATA);

  // ---------- graph page ----------
  function startGraph(data) {
    const kind = data.kind;
    let allNodes = data.nodes;
    let allLinks = data.links;
    const searchIndex = data.search_index || [];
    let nodeById = new Map(allNodes.map((n) => [n.id, n]));
    let linkById = new Map(allLinks.map((l) => [l.id, l]));
    let fullLoaded = false;

    const container = document.getElementById("graph");
    const selectionPanel = document.getElementById("selection");
    const searchInput = document.getElementById("search");
    const predicateSelect = document.getElementById("predicate");
    const datasetSelect = document.getElementById("dataset");
    const app = document.getElementById("graph-app");

    let selectedId = null;
    let selectedLinkId = null;
    let keyOnly = false;
    let transform = { x: 0, y: 0, k: 1 };

    const svg = document.createElementNS(SVGNS, "svg");
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", "100%");
    container.appendChild(svg);
    const viewport = document.createElementNS(SVGNS, "g");
    svg.appendChild(viewport);

    function displayType(node) {
      return kind === "data"
        ? node.mapped_type || node.type
        : node.visual_type || node.type;
    }
    function groupKey(node) {
      return node.community || displayType(node) || "Other";
    }
    function colorFor(node) {
      return COLORS[displayType(node)] || DEFAULT_COLOR;
    }

    // ---------- filter selects ----------
    function fillSelect(select, label, values) {
      select.innerHTML =
        `<option value="">${esc(label)}</option>` +
        values.map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
    }
    fillSelect(predicateSelect, "All relationships",
      [...new Set(allLinks.map((l) => l.predicate).filter(Boolean))].sort());
    const datasets = [...new Set(allNodes.map((n) => n.dataset).filter(Boolean))].sort();
    if (datasets.length && kind === "data") {
      fillSelect(datasetSelect, "All datasets", datasets);
    } else {
      datasetSelect.hidden = true;
    }

    function filtered() {
      const query = searchInput.value.trim().toLowerCase();
      const predicate = predicateSelect.value;
      const dataset = datasetSelect.value;
      let nodes = allNodes;
      if (query) {
        nodes = nodes.filter((n) =>
          [n.name, n.type, n.mapped_type, n.domain, n.dataset, n.source_path, n.community]
            .some((v) => String(v || "").toLowerCase().includes(query)));
      }
      if (dataset) nodes = nodes.filter((n) => n.dataset === dataset);
      let ids = new Set(nodes.map((n) => n.id));
      let links = allLinks.filter((l) => ids.has(l.source) && ids.has(l.target));
      if (predicate) links = links.filter((l) => l.predicate === predicate);
      if (keyOnly) {
        links = links.filter((l) => l.key_relationship);
        const linked = new Set();
        links.forEach((l) => { linked.add(l.source); linked.add(l.target); });
        nodes = nodes.filter((n) => linked.has(n.id));
        ids = linked;
      }
      return { nodes: nodes.map((n) => ({ ...n })), links };
    }

    // ---------- deterministic clustered layout (no physics) ----------
    let view = { nodes: [], links: [], centers: new Map() };
    function layout() {
      const width = container.clientWidth || 800;
      const height = container.clientHeight || 600;
      const f = filtered();
      const local = new Map(f.nodes.map((n) => [n.id, n]));
      const links = f.links.filter((l) => local.has(l.source) && local.has(l.target));

      const degree = new Map();
      links.forEach((l) => {
        degree.set(l.source, (degree.get(l.source) || 0) + 1);
        degree.set(l.target, (degree.get(l.target) || 0) + 1);
      });
      f.nodes.forEach((n) => { n.degree = degree.get(n.id) || 0; });

      const groups = new Map();
      f.nodes.forEach((n) => {
        const key = groupKey(n);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(n);
      });
      const keys = [...groups.keys()].sort((a, b) => groups.get(b).length - groups.get(a).length);
      const cols = Math.max(1, Math.ceil(Math.sqrt(keys.length)));
      const rows = Math.max(1, Math.ceil(keys.length / cols));
      const cellW = width / cols;
      const cellH = height / rows;
      const centers = new Map();
      keys.forEach((key, i) => {
        centers.set(key, {
          x: cellW * ((i % cols) + 0.5),
          y: cellH * (Math.floor(i / cols) + 0.5),
        });
      });

      keys.forEach((key) => {
        const members = groups.get(key).sort((a, b) => b.degree - a.degree);
        const center = centers.get(key);
        const radius = Math.min(cellW, cellH) * 0.34;
        const denom = Math.sqrt(members.length + 1);
        members.forEach((n, idx) => {
          const ring = Math.sqrt(idx) / denom;
          const angle = idx * 2.399963; // golden angle → even phyllotaxis spread
          n.x = center.x + Math.cos(angle) * radius * ring;
          n.y = center.y + Math.sin(angle) * radius * ring;
        });
      });

      // Normalise everything into the viewport with padding so nothing clips at the edges
      // and cluster labels stay readable above their group.
      const xs = f.nodes.map((n) => n.x);
      const ys = f.nodes.map((n) => n.y);
      const minX = Math.min(...xs), maxX = Math.max(...xs);
      const minY = Math.min(...ys), maxY = Math.max(...ys);
      const padX = 52, padTop = 52, padBottom = 34;
      const spanX = maxX - minX || 1, spanY = maxY - minY || 1;
      const scale = Math.min((width - 2 * padX) / spanX, (height - padTop - padBottom) / spanY);
      const offX = padX - minX * scale + ((width - 2 * padX) - spanX * scale) / 2;
      const offY = padTop - minY * scale;
      const place = (p) => { p.x = p.x * scale + offX; p.y = p.y * scale + offY; };
      f.nodes.forEach(place);
      centers.forEach(place);
      // Anchor each cluster label just above its topmost node.
      keys.forEach((key) => {
        const center = centers.get(key);
        const top = Math.min(...groups.get(key).map((n) => n.y));
        center.labelY = Math.max(14, top - 12);
      });

      view = { nodes: f.nodes, links, centers, localById: local };
    }

    function applyTransform() {
      viewport.setAttribute("transform",
        `translate(${transform.x},${transform.y}) scale(${transform.k})`);
    }

    function render() {
      viewport.innerHTML = "";
      const labelLayer = document.createElementNS(SVGNS, "g");
      const linkLayer = document.createElementNS(SVGNS, "g");
      const nodeLayer = document.createElementNS(SVGNS, "g");
      viewport.append(labelLayer, linkLayer, nodeLayer);

      const { nodes, links, centers, localById } = view;
      if (!nodes.length) {
        const text = document.createElementNS(SVGNS, "text");
        text.setAttribute("x", (container.clientWidth || 800) / 2);
        text.setAttribute("y", (container.clientHeight || 600) / 2);
        text.setAttribute("fill", "#64748b");
        text.setAttribute("text-anchor", "middle");
        text.setAttribute("font-size", "15");
        text.textContent = "No nodes match the current filters.";
        viewport.appendChild(text);
        applyTransform();
        return;
      }

      centers.forEach((center, key) => {
        const label = document.createElementNS(SVGNS, "text");
        label.setAttribute("class", "cluster-label");
        label.setAttribute("x", center.x);
        label.setAttribute("y", center.labelY != null ? center.labelY : center.y);
        label.setAttribute("text-anchor", "middle");
        label.textContent = key.length > 28 ? key.slice(0, 27) + "…" : key;
        labelLayer.appendChild(label);
      });

      links.forEach((link) => {
        const a = localById.get(link.source);
        const b = localById.get(link.target);
        if (!a || !b) return;
        const line = document.createElementNS(SVGNS, "line");
        const classes = ["link"];
        if (link.key_relationship) classes.push("key");
        if (link.confidence_tier === "inferred") classes.push("inferred");
        const touchesSel = selectedId && (link.source === selectedId || link.target === selectedId);
        if (selectedLinkId === link.id || touchesSel) classes.push("selected");
        else if (selectedId || selectedLinkId) classes.push("dim");
        line.setAttribute("class", classes.join(" "));
        line.setAttribute("x1", a.x); line.setAttribute("y1", a.y);
        line.setAttribute("x2", b.x); line.setAttribute("y2", b.y);
        line.setAttribute("stroke-width", link.key_relationship ? 2 : 1.1);
        line.addEventListener("click", (e) => {
          e.stopPropagation();
          selectedLinkId = link.id; selectedId = null;
          showLinkDetails(link.id); render();
        });
        const title = document.createElementNS(SVGNS, "title");
        title.textContent = `${a.name} —${link.predicate}→ ${b.name}`;
        line.appendChild(title);
        linkLayer.appendChild(line);
      });

      const neighborOf = new Set();
      if (selectedId) {
        neighborOf.add(selectedId);
        links.forEach((l) => {
          if (l.source === selectedId) neighborOf.add(l.target);
          if (l.target === selectedId) neighborOf.add(l.source);
        });
      }
      const labelled = new Set(
        [...nodes].sort((a, b) => b.degree - a.degree)
          .slice(0, transform.k < 1.2 ? 14 : transform.k < 2 ? 32 : nodes.length)
          .map((n) => n.id));
      if (selectedId) labelled.add(selectedId);

      nodes.forEach((node) => {
        const group = document.createElementNS(SVGNS, "g");
        const dim = selectedId && !neighborOf.has(node.id);
        group.setAttribute("class", `node${node.id === selectedId ? " selected" : ""}${dim ? " dim" : ""}`);
        group.addEventListener("click", (e) => {
          e.stopPropagation();
          selectedId = node.id; selectedLinkId = null;
          showNodeDetails(node.id); render();
          if (history.replaceState) history.replaceState(null, "", "#node=" + encodeURIComponent(node.id));
        });
        const r = Math.max(4, Math.min(15, 4.5 + Math.sqrt(node.degree) * 1.9));
        const circle = document.createElementNS(SVGNS, "circle");
        circle.setAttribute("cx", node.x); circle.setAttribute("cy", node.y);
        circle.setAttribute("r", r);
        circle.setAttribute("fill", colorFor(node));
        circle.setAttribute("fill-opacity", "0.92");
        circle.setAttribute("stroke", "#050a12");
        circle.setAttribute("stroke-width", "1.2");
        group.appendChild(circle);
        if (labelled.has(node.id)) {
          const text = document.createElementNS(SVGNS, "text");
          text.setAttribute("x", node.x);
          text.setAttribute("y", node.y + r + 8);
          text.textContent = node.name.length > 22 ? node.name.slice(0, 21) + "…" : node.name;
          group.appendChild(text);
        }
        const title = document.createElementNS(SVGNS, "title");
        title.textContent = `${node.name} (${displayType(node)})`;
        group.appendChild(title);
        nodeLayer.appendChild(group);
      });
      applyTransform();
    }

    function relayout() { layout(); render(); }

    // ---------- details ----------
    function badge(text, tone) { return `<span class="badge ${tone || ""}">${esc(text)}</span>`; }
    function relList(items, side) {
      if (!items.length) return '<p class="placeholder">None detected.</p>';
      return items.map((l) => {
        const other = nodeById.get(l[side]);
        return `<div class="rel"><strong>${esc(l.predicate)}</strong> ${other ? esc(other.name) : ""}
          <div class="meta">confidence ${Number(l.confidence || 0).toFixed(2)}${l.confidence_tier ? " · " + esc(l.confidence_tier) : ""}</div>
          ${l.evidence ? `<div class="evidence">${esc(String(l.evidence).slice(0, 200))}</div>` : ""}</div>`;
      }).join("");
    }
    function showNodeDetails(id) {
      const node = nodeById.get(id);
      if (!node) return;
      const outgoing = allLinks.filter((l) => l.source === id).slice(0, 40);
      const incoming = allLinks.filter((l) => l.target === id).slice(0, 40);
      const wiki = node.wiki ? `<p><a href="${esc(node.wiki)}">Open wiki page →</a></p>` : "";
      selectionPanel.innerHTML = `
        <h3 class="detail-title">${esc(node.name)}</h3>
        <p>${badge(node.extraction_source || "unknown", node.extraction_source === "structured_connector" ? "good" : "")}
        ${badge(node.confidence_tier || "extracted", node.confidence_tier === "inferred" ? "warn" : "good")}</p>
        <div class="kv">
          <strong>Type</strong> ${esc(displayType(node))}<br>
          ${node.community ? `<strong>Community</strong> ${esc(node.community)}<br>` : ""}
          ${node.dataset ? `<strong>Dataset</strong> ${esc(node.dataset)}<br>` : ""}
          ${node.source_path ? `<strong>Source</strong> <code>${esc(node.source_path)}</code><br>` : ""}
        </div>
        ${node.description ? `<p class="evidence">${esc(node.description)}</p>` : ""}
        ${wiki}
        <button id="impact-btn" class="ghost" style="margin:8px 0">What depends on this →</button>
        <div id="impact"></div>
        <h3>Outgoing</h3>${relList(outgoing, "target")}
        <h3>Incoming</h3>${relList(incoming, "source")}`;
      const impactBtn = document.getElementById("impact-btn");
      if (impactBtn) impactBtn.addEventListener("click", () => showImpact(id));
    }

    // Reverse-reachability (depth 2) over the loaded links — "blast radius" of a node.
    function showImpact(id) {
      const reverse = new Map();
      allLinks.forEach((l) => {
        if (!reverse.has(l.target)) reverse.set(l.target, []);
        reverse.get(l.target).push(l.source);
      });
      const seen = new Set([id]);
      let frontier = [id];
      for (let depth = 0; depth < 2; depth++) {
        const next = [];
        frontier.forEach((cur) => (reverse.get(cur) || []).forEach((src) => {
          if (!seen.has(src)) { seen.add(src); next.push(src); }
        }));
        frontier = next;
      }
      seen.delete(id);
      const names = [...seen].map((nid) => (nodeById.get(nid) || {}).name).filter(Boolean).sort();
      const host = document.getElementById("impact");
      if (!host) return;
      if (!names.length) {
        host.innerHTML = '<p class="placeholder">Nothing in the current view depends on this. Load the full graph for the complete blast radius.</p>';
        return;
      }
      const shown = names.slice(0, 30);
      host.innerHTML = `<div class="note"><strong>${names.length}</strong> node(s) reach this within 2 hops:
        <div>${shown.map((n) => `<span class="chip">${esc(n)}</span>`).join("")}${names.length > shown.length ? `<span class="chip">+${names.length - shown.length}</span>` : ""}</div></div>`;
    }
    function showLinkDetails(id) {
      const link = linkById.get(id);
      if (!link) return;
      const source = nodeById.get(link.source);
      const target = nodeById.get(link.target);
      const weak = link.evidence_level === "weak" || link.confidence_tier === "inferred";
      selectionPanel.innerHTML = `
        <h3 class="detail-title">${esc(link.predicate)}</h3>
        <p>${badge(link.evidence_level || "unknown", link.evidence_level === "authoritative" ? "good" : weak ? "warn" : "")}
        ${badge(link.confidence_tier || "extracted", link.confidence_tier === "inferred" ? "warn" : "good")}
        ${link.key_relationship ? badge("key relationship", "good") : ""}</p>
        <div class="kv">
          <strong>From</strong> ${esc(source ? source.name : link.source)}<br>
          <strong>To</strong> ${esc(target ? target.name : link.target)}<br>
          <strong>Confidence</strong> ${Number(link.confidence || 0).toFixed(2)}<br>
          ${link.extractor ? `<strong>Extractor</strong> ${esc(link.extractor)}<br>` : ""}
          ${link.source_path ? `<strong>Source</strong> <code>${esc(link.source_path)}</code><br>` : ""}
        </div>
        ${weak ? `<div class="note">Semantic or weakly-evidenced relationship — treat as interpretation until checked against the cited source.</div>` : ""}
        <h3>Evidence</h3>
        ${link.evidence ? `<p class="evidence">${esc(link.evidence)}</p>` : '<p class="placeholder">No evidence text attached.</p>'}`;
    }
    function clearSelection() {
      selectedId = null; selectedLinkId = null;
      selectionPanel.className = "placeholder";
      selectionPanel.innerHTML = "Click a node or relationship to inspect its evidence, confidence, source path, and wiki page.";
    }

    // ---------- zoom / pan ----------
    function clampScale(k) { return Math.max(0.3, Math.min(3.5, k)); }
    function zoomAround(px, py, factor) {
      const bx = (px - transform.x) / transform.k;
      const by = (py - transform.y) / transform.k;
      transform.k = clampScale(transform.k * factor);
      transform.x = px - bx * transform.k;
      transform.y = py - by * transform.k;
      applyTransform();
    }
    function fit() { transform = { x: 0, y: 0, k: 1 }; render(); }

    svg.addEventListener("wheel", (e) => {
      e.preventDefault();
      const rect = svg.getBoundingClientRect();
      zoomAround(e.clientX - rect.left, e.clientY - rect.top, Math.exp(-e.deltaY * 0.0012));
    }, { passive: false });
    let drag = null;
    svg.addEventListener("mousedown", (e) => {
      if (e.target.closest(".node") || e.target.closest(".link")) return;
      drag = { x: e.clientX, y: e.clientY, tx: transform.x, ty: transform.y };
    });
    window.addEventListener("mousemove", (e) => {
      if (!drag) return;
      transform.x = drag.tx + e.clientX - drag.x;
      transform.y = drag.ty + e.clientY - drag.y;
      applyTransform();
    });
    window.addEventListener("mouseup", () => { drag = null; });
    svg.addEventListener("click", () => { clearSelection(); render(); });

    // ---------- legend ----------
    function renderLegend() {
      const present = [...new Set(view.nodes.map(displayType))].sort();
      const legend = document.getElementById("legend");
      legend.innerHTML =
        present.map((t) => `<div class="legend-row"><span class="swatch" style="background:${COLORS[t] || DEFAULT_COLOR}"></span>${esc(t)}</div>`).join("") +
        `<div class="legend-row"><span class="swatch line" style="background:var(--accent)"></span>Key relationship</div>` +
        `<div class="legend-row"><span class="swatch line" style="background:#44566f"></span>Standard / inferred</div>`;
    }

    // ---------- search across ALL entities (not just the plotted subset) ----------
    const resultsBox = document.getElementById("search-results");
    function runSearch() {
      const query = searchInput.value.trim().toLowerCase();
      if (query.length < 2) { resultsBox.hidden = true; resultsBox.innerHTML = ""; return; }
      const hits = searchIndex
        .filter((e) => String(e.n || "").toLowerCase().includes(query)
          || String(e.t || "").toLowerCase().includes(query))
        .slice(0, 40);
      if (!hits.length) {
        resultsBox.hidden = false;
        resultsBox.innerHTML = '<div class="result muted">No matches.</div>';
        return;
      }
      resultsBox.hidden = false;
      resultsBox.innerHTML = hits.map((h) => {
        const plotted = nodeById.has(h.i);
        return `<div class="result" data-id="${esc(h.i)}" data-wiki="${esc(h.w || "")}">
          <span class="result-name">${esc(h.n)}</span>
          <span class="result-meta">${esc(h.t || "")}${plotted ? "" : " · not plotted"}</span>
        </div>`;
      }).join("");
      resultsBox.querySelectorAll(".result[data-id]").forEach((row) => {
        row.addEventListener("click", () => focusEntity(row.dataset.id, row.dataset.wiki));
      });
    }
    function focusEntity(id, wikiUrl) {
      if (nodeById.has(id)) {
        selectedId = id; selectedLinkId = null;
        showNodeDetails(id); render();
        if (history.replaceState) history.replaceState(null, "", "#node=" + encodeURIComponent(id));
        return;
      }
      // Not plotted: pull the full graph if we can, otherwise fall back to the wiki page.
      if (!fullLoaded) {
        loadFullGraph().then((ok) => {
          if (ok && nodeById.has(id)) focusEntity(id);
          else if (wikiUrl) window.location.href = wikiUrl;
        });
      } else if (wikiUrl) {
        window.location.href = wikiUrl;
      }
    }

    // ---------- lazy-load the complete graph on demand ----------
    async function loadFullGraph() {
      if (fullLoaded) return true;
      const btn = document.getElementById("load-full");
      try {
        const resp = await fetch(data.full_graph_url, { cache: "no-store" });
        const full = await resp.json();
        allNodes = (full.nodes || []).filter((n) => n.graph_kind === kind);
        allLinks = (full.links || []).filter((l) => l.graph_kind === kind);
        nodeById = new Map(allNodes.map((n) => [n.id, n]));
        linkById = new Map(allLinks.map((l) => [l.id, l]));
        fullLoaded = true;
        if (btn) { btn.textContent = `Full graph loaded (${allNodes.length} nodes)`; btn.disabled = true; }
        relayout(); renderLegend();
        return true;
      } catch (err) {
        if (btn) { btn.textContent = "Open graph.json (offline)"; }
        return false;
      }
    }

    // ---------- export the current view ----------
    function svgMarkup() {
      const clone = svg.cloneNode(true);
      clone.setAttribute("xmlns", SVGNS);
      const rect = svg.getBoundingClientRect();
      clone.setAttribute("width", rect.width);
      clone.setAttribute("height", rect.height);
      const style = document.createElementNS(SVGNS, "style");
      style.textContent =
        ".link{stroke:#44566f;stroke-opacity:.5}.link.key{stroke:#38bdf8;stroke-opacity:.92}" +
        ".node text{fill:#f8fafc;font:650 8px Inter,sans-serif;paint-order:stroke;stroke:#050a12;stroke-width:2.4px;text-anchor:middle}" +
        ".cluster-label{fill:#64748b;font:700 11px Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase}";
      clone.insertBefore(style, clone.firstChild);
      const bg = document.createElementNS(SVGNS, "rect");
      bg.setAttribute("width", "100%"); bg.setAttribute("height", "100%"); bg.setAttribute("fill", "#050a12");
      clone.insertBefore(bg, clone.firstChild);
      return '<?xml version="1.0" encoding="UTF-8"?>\n' + new XMLSerializer().serializeToString(clone);
    }
    function download(blob, filename) {
      const url = URL.createObjectURL(blob);
      const a = el("a", { href: url, download: filename });
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    function exportSvg() {
      download(new Blob([svgMarkup()], { type: "image/svg+xml" }), `${kind}-graph.svg`);
    }
    function exportPng() {
      const rect = svg.getBoundingClientRect();
      const scale = 2;
      const img = new Image();
      img.onload = () => {
        const canvas = el("canvas");
        canvas.width = rect.width * scale; canvas.height = rect.height * scale;
        const ctx = canvas.getContext("2d");
        ctx.scale(scale, scale);
        ctx.drawImage(img, 0, 0);
        canvas.toBlob((blob) => { if (blob) download(blob, `${kind}-graph.png`); });
      };
      img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svgMarkup());
    }

    // ---------- wiring ----------
    let raf = null;
    function scheduleRelayout() {
      if (raf) cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => { raf = null; relayout(); renderLegend(); });
    }
    searchInput.addEventListener("input", () => { runSearch(); scheduleRelayout(); });
    document.getElementById("load-full").addEventListener("click", loadFullGraph);
    document.getElementById("export-svg").addEventListener("click", exportSvg);
    document.getElementById("export-png").addEventListener("click", exportPng);
    predicateSelect.addEventListener("change", scheduleRelayout);
    datasetSelect.addEventListener("change", scheduleRelayout);
    document.getElementById("key-only").addEventListener("click", (e) => {
      keyOnly = !keyOnly; e.currentTarget.classList.toggle("active", keyOnly); scheduleRelayout();
    });
    document.getElementById("reset").addEventListener("click", () => {
      searchInput.value = ""; predicateSelect.value = ""; datasetSelect.value = "";
      keyOnly = false; document.getElementById("key-only").classList.remove("active");
      clearSelection(); fit(); scheduleRelayout();
    });
    document.getElementById("zoom-in").addEventListener("click", () => {
      const r = svg.getBoundingClientRect(); zoomAround(r.width / 2, r.height / 2, 1.25);
    });
    document.getElementById("zoom-out").addEventListener("click", () => {
      const r = svg.getBoundingClientRect(); zoomAround(r.width / 2, r.height / 2, 0.8);
    });
    document.getElementById("fit").addEventListener("click", fit);
    document.getElementById("hide-details").addEventListener("click", () => {
      app.classList.add("details-collapsed");
      requestAnimationFrame(relayout);
    });
    let resizeTimer = null;
    window.addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(relayout, 150);
    });

    const hint = document.getElementById("hint");
    hint.textContent = `Showing ${DATA.stats.shown_nodes} of ${DATA.stats.total_nodes} ${kind} nodes — ranked by importance. Search covers all ${DATA.stats.total_nodes}. Scroll to zoom, drag to pan.`;

    // Deep-link support: #node=<id> focuses that node on load.
    function applyHash() {
      const match = /[#&]node=([^&]+)/.exec(window.location.hash);
      if (match) focusEntity(decodeURIComponent(match[1]), null);
    }

    requestAnimationFrame(() => { relayout(); renderLegend(); applyHash(); });
  }

  // ---------- intelligence dashboard ----------
  function renderIntelligence(intel) {
    const host = document.getElementById("intel-app");
    host.hidden = false;
    if (!intel) {
      host.innerHTML = `<div class="empty-state">No Graphify analysis found yet.<br>
        Run <code>ontology-agent graphify run</code> then rebuild the portal to populate architecture hotspots,
        surprising connections, and community cohesion.</div>`;
      return;
    }
    const sections = [];

    const maxDeg = Math.max(1, ...intel.hotspots.map((h) => h.degree));
    sections.push(`
      <div class="intel-section">
        <h2>Architecture hotspots</h2>
        <p class="lead">The most connected "god" nodes — high-traffic hubs worth reviewing for coupling and refactor risk.</p>
        <div class="grid cols-2">
          ${intel.hotspots.map((h, i) => `
            <div class="card">
              <div class="hotspot">
                <div><div class="card-title">${i + 1}. ${link(h.wiki_url, h.label)}</div>
                ${h.community ? `<div class="card-sub">${esc(h.community)}</div>` : ""}</div>
                <div class="rank">${h.degree} links</div>
              </div>
              <div class="bar"><span style="width:${Math.round((h.degree / maxDeg) * 100)}%"></span></div>
            </div>`).join("") || `<p class="placeholder">No hotspots detected.</p>`}
        </div>
      </div>`);

    sections.push(`
      <div class="intel-section">
        <h2>Surprising connections</h2>
        <p class="lead">Links Graphify flagged as unexpected — they bridge separate communities or cross directory boundaries.</p>
        <div class="grid cols-2">
          ${intel.surprises.map((s) => `
            <div class="card">
              <div class="card-title">${link(s.source_wiki, s.source)} <span class="card-sub">${esc(s.relation || "→")}</span> ${link(s.target_wiki, s.target)}</div>
              ${s.why ? `<p class="card-sub">${esc(s.why)}</p>` : ""}
              <div>${(s.source_files || []).map((f) => `<span class="chip">${esc(f)}</span>`).join("")}</div>
            </div>`).join("") || `<p class="placeholder">No surprising connections detected.</p>`}
        </div>
      </div>`);

    const refactor = intel.refactor_candidates || [];
    if (refactor.length) {
      sections.push(`
        <div class="intel-section">
          <h2>Refactor candidates</h2>
          <p class="lead">Sizeable but loosely-knit communities (lowest cohesion) — likely doing too many things and worth splitting.</p>
          <div class="grid cols-3">
            ${refactor.map((c) => `
              <div class="card">
                <div class="card-title">${esc(c.label)}</div>
                <div class="card-sub">${c.size} nodes · cohesion ${c.cohesion.toFixed(3)}</div>
                <div class="bar low"><span style="width:${Math.round(c.cohesion * 100)}%"></span></div>
                <div>${(c.members || []).map((m) => `<span class="chip">${esc(m.name)}</span>`).join("")}</div>
              </div>`).join("")}
          </div>
        </div>`);
    }

    const questions = intel.questions || [];
    if (questions.length) {
      sections.push(`
        <div class="intel-section">
          <h2>Start here — suggested questions</h2>
          <p class="lead">Generated from the graph structure, answered by traversing it (no LLM, no cost).</p>
          <div class="grid cols-2">
            ${questions.map((q) => `
              <div class="card">
                <div class="card-title">${link(q.wiki_url, q.question)}</div>
                <p class="card-sub">${esc(q.answer)}</p>
              </div>`).join("")}
          </div>
        </div>`);
    }

    const q = intel.quality;
    if (q) {
      const badgeTone = q.clean ? "good" : "warn";
      sections.push(`
        <div class="intel-section">
          <h2>Data quality</h2>
          <p class="lead">Structural health of the extracted relationships.</p>
          <div class="grid cols-3">
            <div class="card"><div class="card-title">Relationships</div><div class="card-sub">${q.total_relationships.toLocaleString("en-US")}</div></div>
            <div class="card"><div class="card-title">Duplicate edges</div><div class="card-sub"><span class="badge ${q.duplicate_edges ? "warn" : "good"}">${q.duplicate_edges}</span></div></div>
            <div class="card"><div class="card-title">Self-loops</div><div class="card-sub"><span class="badge ${q.self_loops ? "warn" : "good"}">${q.self_loops}</span></div></div>
            <div class="card"><div class="card-title">Multi-edge pairs</div><div class="card-sub">${q.multi_edge_pairs}</div></div>
            <div class="card"><div class="card-title">Overall</div><div class="card-sub"><span class="badge ${badgeTone}">${q.clean ? "clean" : "review"}</span></div></div>
          </div>
        </div>`);
    }

    const maxSize = Math.max(1, ...intel.communities.map((c) => c.size));
    sections.push(`
      <div class="intel-section">
        <h2>Community cohesion</h2>
        <p class="lead">How tightly knit each detected community is. Larger, low-cohesion clusters are candidates for splitting.</p>
        <div class="grid cols-3">
          ${intel.communities.slice(0, 24).map((c) => `
            <div class="card">
              <div class="card-title">${esc(c.label)}</div>
              <div class="card-sub">${c.size} nodes · cohesion ${c.cohesion.toFixed(3)}</div>
              <div class="bar"><span style="width:${Math.round((c.size / maxSize) * 100)}%"></span></div>
              <div>${c.members.map((m) => `<span class="chip">${esc(m.name)}</span>`).join("")}</div>
            </div>`).join("")}
        </div>
      </div>`);

    const artifacts = DATA.artifacts || [];
    if (artifacts.length) {
      sections.push(`
        <div class="intel-section">
          <h2>Explore artifacts</h2>
          <p class="lead">Graphify's own visualisations — useful, high-fidelity companions to this portal.</p>
          <div class="grid cols-3">
            ${artifacts.map((a) => `<div class="card"><div class="card-title">${link(a.url, a.label)}</div></div>`).join("")}
          </div>
        </div>`);
    }
    host.innerHTML = sections.join("");
  }

  // ---------- changes (run-to-run diff) ----------
  function renderChanges(changes) {
    const host = document.getElementById("intel-app");
    host.hidden = false;
    if (!changes || !changes.has_baseline) {
      host.innerHTML = `<div class="empty-state">No prior run to compare against yet.<br>
        Re-run <code>ontology-agent run</code> after your sources change and this tab will show
        exactly what was added, removed and modified.</div>`;
      return;
    }
    const s = changes.summary;
    const entityRows = (rows) =>
      rows.map((r) => `<div class="card">
        <div class="card-title">${link(r.wiki_url, r.name)}</div>
        <div class="card-sub">${esc(r.type)}${r.community ? " · " + esc(r.community) : ""}</div>
      </div>`).join("") || `<p class="placeholder">None.</p>`;
    const relRows = (rows) =>
      rows.map((r) => `<div class="card">
        <div class="card-title">${link(r.source_wiki, r.source)} <span class="card-sub">${esc(r.predicate)}</span> ${link(r.target_wiki, r.target)}</div>
      </div>`).join("") || `<p class="placeholder">None.</p>`;
    const sections = [];

    sections.push(`<div class="intel-section">
      <h2>Since the last run</h2>
      <p class="lead">Renames appear as a removal + an addition (entity identity is name + type).</p>
      <div class="grid cols-3">
        <div class="card"><div class="card-title">+${s.entities_added} / −${s.entities_removed}</div><div class="card-sub">entities added / removed</div></div>
        <div class="card"><div class="card-title">~${s.entities_modified}</div><div class="card-sub">entities modified</div></div>
        <div class="card"><div class="card-title">+${s.relationships_added} / −${s.relationships_removed}</div><div class="card-sub">relationships added / removed</div></div>
      </div>
    </div>`);

    sections.push(`<div class="intel-section"><h2>Added entities</h2>
      <div class="grid cols-3">${entityRows(changes.entities_added)}</div></div>`);
    sections.push(`<div class="intel-section"><h2>Removed entities</h2>
      <div class="grid cols-3">${entityRows(changes.entities_removed)}</div></div>`);

    if (changes.entities_modified.length) {
      sections.push(`<div class="intel-section"><h2>Modified entities</h2>
        <div class="grid cols-2">${changes.entities_modified.map((m) => `
          <div class="card"><div class="card-title">${link(m.wiki_url, m.name)}</div>
          <div class="card-sub">${esc(m.type)}</div>
          ${m.changes.map((c) => `<div class="kv"><strong>${esc(c.field)}</strong> ${esc(c.old || "∅")} → ${esc(c.new || "∅")}</div>`).join("")}
          </div>`).join("")}</div></div>`);
    }

    sections.push(`<div class="intel-section"><h2>New relationships</h2>
      <div class="grid cols-2">${relRows(changes.relationships_added)}</div></div>`);
    sections.push(`<div class="intel-section"><h2>Removed relationships</h2>
      <div class="grid cols-2">${relRows(changes.relationships_removed)}</div></div>`);

    if (changes.communities_changed.length) {
      sections.push(`<div class="intel-section"><h2>Communities that grew / shrank</h2>
        <div class="grid cols-3">${changes.communities_changed.map((c) => `
          <div class="card"><div class="card-title">${esc(c.label)}</div>
          <div class="card-sub">${c.old_size} → ${c.new_size} nodes (${c.delta > 0 ? "+" : ""}${c.delta})</div></div>`).join("")}</div></div>`);
    }
    host.innerHTML = sections.join("");
  }
})();
