"use strict";
(function () {
  const DATA = JSON.parse(document.getElementById("portal-data").textContent);
  const SVGNS = "http://www.w3.org/2000/svg";

  const COLORS = {
    System: "#38bdf8", ArchitectureGroup: "#38bdf8", Module: "#a7f3d0", Technology: "#fde68a", APIEndpoint: "#fca5a5",
    DataModel: "#c4b5fd", Database: "#93c5fd", DataStore: "#93c5fd", DeploymentUnit: "#fdba74",
    Config: "#f9a8d4", ExternalService: "#fcd34d", File: "#bae6fd", Class: "#ddd6fe",
    Function: "#fecaca", Concept: "#94a3b8",
  };
  const DEFAULT_COLOR = "#94a3b8";
  // Curated fallback palette for types without a named color: hashing a type into
  // arbitrary hsl() produced clashing hues that changed meaning per graph. Hashing
  // into a fixed palette keeps type→color stable and readable everywhere.
  const EXTRA_COLORS = [
    "#5eead4", "#f0abfc", "#fbbf24", "#86efac", "#7dd3fc", "#fda4af",
    "#d8b4fe", "#fed7aa", "#a5b4fc", "#bef264", "#f9a8d4", "#67e8f9",
  ];

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  }

  function sourceWikiHref(path) {
    const slug = String(path || "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
    return slug ? `../wiki/sources/${slug}.html` : "#";
  }
  function friendlyRelation(value) {
    const raw = String(value || "related to").replace(/([a-z])([A-Z])/g, "$1 $2");
    return raw.replaceAll("_", " ").toLowerCase();
  }
  function friendlyLabel(value) {
    const label = friendlyRelation(value);
    return label.charAt(0).toUpperCase() + label.slice(1);
  }
  function el(tag, attrs, text) {
    const node = document.createElement(tag);
    if (attrs) for (const key in attrs) node.setAttribute(key, attrs[key]);
    if (text != null) node.textContent = text;
    return node;
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
    return artifacts.map((a) => `<div class="artifact-link"><a href="${esc(a.url)}">${esc(a.label)} →</a></div>`).join("");
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
  if (DATA.page === "ask") {
    renderAsk(DATA);
    return;
  }
  if (DATA.page === "sources") {
    renderSources(DATA);
    return;
  }
  document.getElementById("graph-app").hidden = false;
  startGraph(DATA);

  // ---------- graph page ----------
  function startGraph(data) {
    const kind = data.kind;
    let allNodes = data.nodes;
    let allLinks = data.links;
    const overviewNodes = data.nodes;
    const overviewLinks = data.links;
    const searchIndex = data.search_index || [];
    let nodeById = new Map(allNodes.map((n) => [n.id, n]));
    let linkById = new Map(allLinks.map((l) => [l.id, l]));
    let fullLoaded = false;
    let fullGraphPromise = null;
    let focusRequest = 0;

    const container = document.getElementById("graph");
    const selectionPanel = document.getElementById("selection");
    const searchInput = document.getElementById("search");
    const predicateSelect = document.getElementById("predicate");
    const datasetSelect = document.getElementById("dataset");
    const layerSelect = document.getElementById("layer");
    const app = document.getElementById("graph-app");

    let selectedId = null;
    let selectedLinkId = null;
    let architectureFocus = null;
    let keyOnly = false;
    let transform = { x: 0, y: 0, k: 1 };

    const svg = document.createElementNS(SVGNS, "svg");
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", "100%");
    container.appendChild(svg);
    const defs = document.createElementNS(SVGNS, "defs");
    defs.innerHTML = '<marker id="dependency-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#52657f"/></marker>';
    svg.appendChild(defs);
    const viewport = document.createElementNS(SVGNS, "g");
    svg.appendChild(viewport);

    function displayType(node) {
      return node.graph_kind === "data"
        ? node.mapped_type || node.type
        : node.visual_type || node.type;
    }
    function groupKey(node) {
      return node.community || displayType(node) || "Other";
    }
    function colorFor(node) {
      const type = displayType(node);
      if (COLORS[type]) return COLORS[type];
      let hash = 0;
      for (const character of String(type)) hash = (hash * 31 + character.charCodeAt(0)) | 0;
      return EXTRA_COLORS[Math.abs(hash) % EXTRA_COLORS.length] || DEFAULT_COLOR;
    }

    // ---------- filter selects ----------
    function fillSelect(select, label, values, selected) {
      select.innerHTML =
        `<option value="">${esc(label)}</option>` +
        values.map((v) => `<option value="${esc(v.value)}">${esc(v.label)}</option>`).join("");
      select.value = values.some((v) => v.value === selected) ? selected : "";
    }
    function optionCounts(values) {
      const counts = new Map();
      values.filter(Boolean).forEach((value) => counts.set(value, (counts.get(value) || 0) + 1));
      return [...counts.entries()]
        .sort((a, b) => String(a[0]).localeCompare(String(b[0])))
        .map(([value, count]) => ({ value, label: `${friendlyRelation(value)} (${count})` }));
    }
    function scopedNodes({ ignoreDataset = false } = {}) {
      const query = searchInput.value.trim().toLowerCase();
      const layer = layerSelect.value;
      const dataset = ignoreDataset ? "" : datasetSelect.value;
      let nodes = layer === "repo" && !architectureFocus ? overviewNodes : allNodes;
      if (layer !== "all") nodes = nodes.filter((n) => n.graph_kind === layer);
      if (architectureFocus && layer !== "data") {
        nodes = nodes.filter((n) => n.graph_kind !== "repo" || n.architecture_group === architectureFocus || n.group_key === architectureFocus);
      }
      if (query) {
        nodes = nodes.filter((n) =>
          [n.name, n.type, n.mapped_type, n.domain, n.dataset, n.source_path, n.community]
            .some((v) => String(v || "").toLowerCase().includes(query)));
      }
      if (dataset) nodes = nodes.filter((n) => n.dataset === dataset);
      return nodes;
    }
    function scopedLinks() {
      return layerSelect.value === "repo" && !architectureFocus ? overviewLinks : allLinks;
    }
    function refreshFacets() {
      const selectedDataset = datasetSelect.value;
      const selectedPredicate = predicateSelect.value;
      const datasetNodes = scopedNodes({ ignoreDataset: true });
      const datasets = optionCounts(datasetNodes.map((n) => n.dataset));
      fillSelect(datasetSelect, "All datasets", datasets, selectedDataset);
      datasetSelect.hidden = datasets.length === 0 || layerSelect.value === "repo";

      const relationNodes = scopedNodes();
      const ids = new Set(relationNodes.map((n) => n.id));
      const relations = optionCounts(scopedLinks()
        .filter((l) => ids.has(l.source) && ids.has(l.target))
        .map((l) => l.predicate));
      fillSelect(predicateSelect, "All relationships", relations, selectedPredicate);
    }
    refreshFacets();

    function filtered() {
      const predicate = predicateSelect.value;
      let nodes = scopedNodes();
      let ids = new Set(nodes.map((n) => n.id));
      let links = scopedLinks().filter((l) => ids.has(l.source) && ids.has(l.target));
      if (predicate) links = links.filter((l) => l.predicate === predicate);
      if (keyOnly) {
        links = links.filter((l) => l.key_relationship);
        const linked = new Set();
        links.forEach((l) => { linked.add(l.source); linked.add(l.target); });
        nodes = nodes.filter((n) => linked.has(n.id));
      }
      return { nodes: nodes.map((n) => ({ ...n })), links };
    }

    // ---------- clustered layout + one-shot force spread ----------
    // ponytail: bounded-iteration force relaxation, NOT a live sim, so it spreads
    // overlapping nodes once and then stays static — no continuous CPU (that was the
    // old freeze). Naive O(n²) repulsion is fine at the capped node count (~600 max);
    // swap in Barnes–Hut only if that cap ever grows past a couple thousand.
    function forceSpread(nodes, links, byId, width, height, centerOf) {
      if (nodes.length > 700) return;
      const clusterCount = new Set(nodes.map((n) => (centerOf && centerOf(n)) || null)).size;
      // Many small clusters (repo communities) need stronger cohesion or repulsion
      // bleeds them into one blob; few large clusters (data types) can spread looser.
      const manyClusters = clusterCount > 12;
      const REPULSION = manyClusters ? 380 : 780;
      const SPRING = 0.03, SPRING_LEN = 34;
      const GRAVITY = manyClusters ? 0.22 : 0.14;
      const ITERS = 170, MAX_STEP = 26;
      const pairs = links
        .map((l) => [byId.get(l.source), byId.get(l.target)])
        .filter((p) => p[0] && p[1] && p[0] !== p[1]);
      const fallback = { x: width / 2, y: height / 2 };
      for (let it = 0; it < ITERS; it++) {
        const cool = 1 - it / ITERS;
        for (const a of nodes) {
          // Gravity anchors each node to its OWN cluster center — global gravity
          // squashed every community into one central blob.
          const c = (centerOf && centerOf(a)) || fallback;
          a._fx = (c.x - a.x) * GRAVITY; a._fy = (c.y - a.y) * GRAVITY;
        }
        for (let i = 0; i < nodes.length; i++) {
          const a = nodes[i];
          for (let j = i + 1; j < nodes.length; j++) {
            const b = nodes[j];
            let dx = a.x - b.x, dy = a.y - b.y;
            let d2 = dx * dx + dy * dy;
            if (d2 < 0.01) { dx = (i - j) * 0.1 + 0.1; dy = 0.1; d2 = dx * dx + dy * dy; }
            const d = Math.sqrt(d2), f = REPULSION / d2, ux = dx / d, uy = dy / d;
            a._fx += ux * f; a._fy += uy * f;
            b._fx -= ux * f; b._fy -= uy * f;
          }
        }
        for (const [a, b] of pairs) {
          // Cross-domain relationships are drawn as arcs, but must not pull distinct
          // domains back into one overlapping mass during layout.
          if (centerOf && centerOf(a) !== centerOf(b)) continue;
          let dx = b.x - a.x, dy = b.y - a.y;
          const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
          const f = SPRING * (d - SPRING_LEN), ux = dx / d, uy = dy / d;
          a._fx += ux * f; a._fy += uy * f;
          b._fx -= ux * f; b._fy -= uy * f;
        }
        for (const a of nodes) {
          a.x += Math.max(-MAX_STEP, Math.min(MAX_STEP, a._fx)) * cool;
          a.y += Math.max(-MAX_STEP, Math.min(MAX_STEP, a._fy)) * cool;
        }
      }
    }

    let view = { nodes: [], links: [], centers: new Map() };
    function layoutArchitecture(nodes, links, width, height) {
      const incoming = new Map(nodes.map((node) => [node.id, 0]));
      const outgoing = new Map(nodes.map((node) => [node.id, []]));
      links.forEach((link) => {
        incoming.set(link.target, (incoming.get(link.target) || 0) + 1);
        outgoing.get(link.source).push(link.target);
      });
      const rank = new Map(nodes.map((node) => [node.id, 0]));
      const remainingIncoming = new Map(incoming);
      const queue = nodes.filter((node) => remainingIncoming.get(node.id) === 0).map((node) => node.id);
      const visited = new Set();
      while (queue.length) {
        const id = queue.shift();
        visited.add(id);
        (outgoing.get(id) || []).forEach((target) => {
          rank.set(target, Math.min(5, Math.max(rank.get(target) || 0, (rank.get(id) || 0) + 1)));
          remainingIncoming.set(target, (remainingIncoming.get(target) || 0) - 1);
          if (remainingIncoming.get(target) === 0) queue.push(target);
        });
      }
      const cycleColumns = Math.max(1, Math.min(4, Math.ceil(Math.sqrt(nodes.length))));
      nodes.filter((node) => !visited.has(node.id)).forEach((node, index) => rank.set(node.id, index % cycleColumns));
      const columns = new Map();
      nodes.forEach((node) => {
        const column = rank.get(node.id) || 0;
        if (!columns.has(column)) columns.set(column, []);
        columns.get(column).push(node);
      });
      const ordered = [...columns.keys()].sort((a, b) => a - b);
      ordered.forEach((column, columnIndex) => {
        const members = columns.get(column).sort((a, b) => (incoming.get(b.id) || 0) - (incoming.get(a.id) || 0));
        const rowGap = members.length > 1
          ? Math.min(96, Math.max(64, (height - 140) / (members.length - 1)))
          : 0;
        members.forEach((node, rowIndex) => {
          node.x = 90 + columnIndex * Math.max(190, (width - 180) / Math.max(1, ordered.length - 1));
          node.y = 70 + rowIndex * rowGap;
        });
      });
      return new Map();
    }
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

      const architectureOnly = f.nodes.length > 0 && f.nodes.every((node) => node.graph_kind === "repo");
      if (architectureOnly) {
        const centers = layoutArchitecture(f.nodes, links, width, height);
        view = { nodes: f.nodes, links, centers, localById: local, architecture: true };
        return;
      }

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

      // Relax the phyllotaxis seed so clumped nodes push apart and become readable.
      forceSpread(f.nodes, links, local, width, height, (n) => centers.get(groupKey(n)));

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
      // The force pass moved nodes, so re-anchor each cluster label to the centroid of
      // its (spread) members and sit it just above the topmost one.
      keys.forEach((key) => {
        const members = groups.get(key);
        const center = centers.get(key);
        center.x = members.reduce((s, n) => s + n.x, 0) / members.length;
        center.labelY = Math.max(14, Math.min(...members.map((n) => n.y)) - 12);
        center.count = members.length;
      });

      view = { nodes: f.nodes, links, centers, localById: local, architecture: false };
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
      // Cluster labels paint LAST so category names stay visible above the circles.
      viewport.append(linkLayer, nodeLayer, labelLayer);

      const { nodes, links, centers, localById } = view;
      const denseView = nodes.length > 500;
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

      const invKc = 1 / transform.k;
      // Data-like layers (few clusters) always show every category label. Repo-like
      // layers (dozens of communities) label only the biggest ones at fit zoom —
      // 30 stacked labels were worse than none; the rest appear as you zoom in.
      const majorCenters = new Set(
        centers.size > 12
          ? [...centers.values()].sort((a, b) => (b.count || 0) - (a.count || 0)).slice(0, 8)
          : centers.values());
      centers.forEach((center, key) => {
        if (transform.k < 2 && !majorCenters.has(center)) return;
        const label = document.createElementNS(SVGNS, "text");
        label.setAttribute("class", "cluster-label");
        label.setAttribute("x", center.x);
        label.setAttribute("y", center.labelY != null ? center.labelY : center.y);
        label.setAttribute("text-anchor", "middle");
        label.style.fontSize = (11 * invKc).toFixed(2) + "px";
        const clusterLabel = friendlyRelation(key).toUpperCase();
        label.textContent = clusterLabel.length > 28 ? clusterLabel.slice(0, 27) + "…" : clusterLabel;
        labelLayer.appendChild(label);
      });

      links.forEach((link) => {
        const a = localById.get(link.source);
        const b = localById.get(link.target);
        if (!a || !b) return;
        const crossGroup = groupKey(a) !== groupKey(b);
        const edge = document.createElementNS(SVGNS, crossGroup ? "path" : "line");
        const classes = ["link"];
        if (crossGroup) classes.push("cross-domain");
        if (link.key_relationship) classes.push("key");
        if (link.confidence_tier === "inferred") classes.push("inferred");
        const touchesSel = selectedId && (link.source === selectedId || link.target === selectedId);
        if (selectedLinkId === link.id || touchesSel) classes.push("selected");
        else if (selectedId || selectedLinkId) classes.push("dim");
        edge.setAttribute("class", classes.join(" "));
        if (crossGroup) {
          const dx = b.x - a.x, dy = b.y - a.y;
          const distance = Math.sqrt(dx * dx + dy * dy) || 1;
          const bend = Math.min(72, Math.max(18, distance * .14));
          const sign = String(link.source) < String(link.target) ? 1 : -1;
          const controlX = (a.x + b.x) / 2 - (dy / distance) * bend * sign;
          const controlY = (a.y + b.y) / 2 + (dx / distance) * bend * sign;
          edge.setAttribute("d", `M ${a.x} ${a.y} Q ${controlX} ${controlY} ${b.x} ${b.y}`);
        } else {
          edge.setAttribute("x1", a.x); edge.setAttribute("y1", a.y);
          edge.setAttribute("x2", b.x); edge.setAttribute("y2", b.y);
        }
        edge.setAttribute("stroke-width", (link.key_relationship ? 2 : 1.1) * invKc);
        if (denseView && !link.key_relationship) edge.style.strokeOpacity = "0.1";
        if (view.architecture) edge.setAttribute("marker-end", "url(#dependency-arrow)");
        edge.addEventListener("click", (e) => {
          e.stopPropagation();
          selectedLinkId = link.id; selectedId = null;
          showLinkDetails(link.id); render();
        });
        const title = document.createElementNS(SVGNS, "title");
        title.textContent = `${a.name} —${link.predicate}→ ${b.name}`;
        edge.appendChild(title);
        linkLayer.appendChild(edge);
      });

      const neighborOf = new Set();
      if (selectedId) {
        neighborOf.add(selectedId);
        links.forEach((l) => {
          if (l.source === selectedId) neighborOf.add(l.target);
          if (l.target === selectedId) neighborOf.add(l.source);
        });
      }
      // Show more names as you zoom in, but never the whole graph at once (that was a
      // wall of overlapping text). invK keeps every label a constant on-screen size
      // regardless of the zoom transform, so they stay readable instead of ballooning.
      const invK = 1 / transform.k;
      const cap = transform.k < 1.2 ? 28 : transform.k < 2 ? 44 : transform.k < 3 ? 90 : 150;
      // Circles grow slower than distances while zooming, so magnifying genuinely
      // opens space between nodes instead of magnifying the clutter.
      const rScale = transform.k < 1.2 ? 1 : transform.k < 2 ? 0.8 : transform.k < 3 ? 0.65 : 0.5;
      let labelCandidates = [...nodes]
        .filter((node) => transform.k >= 1.2 || node.extraction_source !== "portal_aggregate")
        .sort((a, b) => b.degree - a.degree);
      if (!view.architecture && transform.k < 1.2) {
        const perCluster = new Map();
        labelCandidates = labelCandidates.filter((node) => {
          const name = String(node.name || "");
          if (name.length > 24 || name.includes("_")) return false;
          const key = groupKey(node);
          const count = perCluster.get(key) || 0;
          perCluster.set(key, count + 1);
          return count < 2;
        });
      }
      const labelled = new Set(labelCandidates.slice(0, cap).map((node) => node.id));
      if (selectedId) labelled.add(selectedId);

      nodes.forEach((node) => {
        const group = document.createElementNS(SVGNS, "g");
        const dim = selectedId && !neighborOf.has(node.id);
        group.setAttribute("class", `node${node.id === selectedId ? " selected" : ""}${dim ? " dim" : ""}`);
        const activate = () => {
          if (node.aggregate_kind === "architecture") {
            drillArchitecture(node);
            return;
          }
          selectedId = node.id; selectedLinkId = null;
          showNodeDetails(node.id); render();
          if (history.replaceState) history.replaceState(null, "", "#node=" + encodeURIComponent(node.id));
        };
        group.addEventListener("click", (e) => { e.stopPropagation(); activate(); });
        if (!denseView) {
          group.setAttribute("tabindex", "0");
          group.setAttribute("role", "button");
          group.setAttribute("aria-label", `${node.name} (${displayType(node)})`);
          group.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); }
          });
        }
        const architectureCard = Boolean(view.architecture);
        const baseRadius = denseView
          ? Math.max(1.7, Math.min(4.4, 1.8 + Math.sqrt(node.degree) * 0.42))
          : Math.max(3.5, Math.min(13, 4 + Math.sqrt(node.degree) * 1.7));
        const r = baseRadius * rScale;
        if (architectureCard) {
          const rect = document.createElementNS(SVGNS, "rect");
          rect.setAttribute("x", node.x - 76); rect.setAttribute("y", node.y - 30);
          rect.setAttribute("width", 152); rect.setAttribute("height", 60);
          rect.setAttribute("rx", 12); rect.setAttribute("class", "architecture-card");
          rect.setAttribute("fill", colorFor(node));
          group.appendChild(rect);
          const titleText = document.createElementNS(SVGNS, "text");
          titleText.setAttribute("x", node.x); titleText.setAttribute("y", node.y - 3);
          titleText.setAttribute("class", "architecture-title");
          titleText.textContent = node.name.length > 24 ? node.name.slice(0, 23) + "…" : node.name;
          group.appendChild(titleText);
          const metaText = document.createElementNS(SVGNS, "text");
          metaText.setAttribute("x", node.x); metaText.setAttribute("y", node.y + 15);
          metaText.setAttribute("class", "architecture-meta");
          const cardMeta = node.description || (node.member_count ? `${node.member_count} components` : displayType(node));
          metaText.textContent = cardMeta.length > 31 ? cardMeta.slice(0, 30) + "…" : cardMeta;
          group.appendChild(metaText);
        } else if (node.graph_kind === "data") {
          // Data-layer nodes are squares, architecture nodes circles — a second
          // channel besides color, so the layers stay distinguishable for
          // color-blind users and in grayscale exports.
          const square = document.createElementNS(SVGNS, "rect");
          square.setAttribute("x", node.x - r); square.setAttribute("y", node.y - r);
          square.setAttribute("width", r * 2); square.setAttribute("height", r * 2);
          square.setAttribute("rx", Math.max(1, r * 0.3));
          square.setAttribute("fill", colorFor(node));
          square.setAttribute("fill-opacity", denseView ? "0.82" : "0.92");
          square.setAttribute("stroke", "#050a12");
          square.setAttribute("stroke-width", denseView ? "0.55" : "1.2");
          group.appendChild(square);
        } else {
          const circle = document.createElementNS(SVGNS, "circle");
          circle.setAttribute("cx", node.x); circle.setAttribute("cy", node.y);
          circle.setAttribute("r", r);
          circle.setAttribute("fill", colorFor(node));
          circle.setAttribute("fill-opacity", denseView ? "0.82" : "0.92");
          circle.setAttribute("stroke", "#050a12");
          circle.setAttribute("stroke-width", denseView ? "0.55" : "1.2");
          group.appendChild(circle);
        }
        if (!architectureCard && labelled.has(node.id)) {
          const text = document.createElementNS(SVGNS, "text");
          text.setAttribute("x", node.x);
          text.setAttribute("y", node.y + r + 9 * invK);
          text.style.fontSize = (9.5 * invK).toFixed(2) + "px";
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

    function relayout() {
      refreshFacets();
      layout();
      render();
      renderMetrics({ ...DATA.stats, shown_nodes: view.nodes.length });
      const searchScope = window.location.protocol === "file:"
        ? "Offline search covers these visible nodes."
        : "Search covers every entity.";
      hint.textContent = `Showing ${view.nodes.length} readable nodes from ${DATA.stats.total_nodes} canonical entities. ${searchScope}`;
      renderArchitectureBreadcrumbs();
    }

    function renderArchitectureBreadcrumbs() {
      const host = document.getElementById("architecture-breadcrumbs");
      if (!host) return;
      if (layerSelect.value !== "repo") { host.hidden = true; return; }
      host.hidden = false;
      host.innerHTML = architectureFocus
        ? `<button id="architecture-back" class="ghost">Architecture</button><span>›</span><strong>${esc(architectureFocus)}</strong>`
        : `<strong>Architecture overview</strong><span>${view.nodes.length} areas · Dependencies flow left to right · Select an area to drill in.</span>`;
      const back = document.getElementById("architecture-back");
      if (back) back.addEventListener("click", () => {
        architectureFocus = null; selectedId = null; selectedLinkId = null;
        updateUrlState(); scheduleRelayout();
      });
    }

    async function drillArchitecture(node) {
      if (!await loadFullGraph()) return;
      architectureFocus = node.group_key || node.full_name || node.name;
      layerSelect.value = "repo";
      searchInput.value = "";
      selectedId = null; selectedLinkId = null;
      updateUrlState(); scheduleRelayout();
    }

    function updateUrlState() {
      if (!history.replaceState) return;
      const params = new URLSearchParams();
      if (layerSelect.value !== "repo") params.set("layer", layerSelect.value);
      if (searchInput.value.trim()) params.set("q", searchInput.value.trim());
      if (predicateSelect.value) params.set("relation", predicateSelect.value);
      if (datasetSelect.value) params.set("dataset", datasetSelect.value);
      if (architectureFocus) params.set("focus", architectureFocus);
      if (selectedId) params.set("node", selectedId);
      history.replaceState(null, "", params.size ? `#${params}` : "#layer=repo");
    }

    // ---------- details ----------
    function badge(text, tone) { return `<span class="badge ${tone || ""}">${esc(text)}</span>`; }
    function evidenceBlock(evidence) {
      const text = String(evidence || "");
      if (!text) return "";
      if (text.length <= 200) return `<div class="evidence">${esc(text)}</div>`;
      return `<details class="evidence-more"><summary class="evidence">${esc(text.slice(0, 200))}…</summary><div class="evidence">${esc(text)}</div></details>`;
    }
    function relList(items, side) {
      if (!items.length) return '<p class="placeholder">None detected.</p>';
      return items.map((l) => {
        const other = nodeById.get(l[side]);
        return `<div class="rel"><strong>${esc(friendlyRelation(l.predicate))}</strong> ${other ? esc(other.name) : ""}
          <div class="meta">confidence ${Number(l.confidence || 0).toFixed(2)}${l.confidence_tier ? " · " + esc(l.confidence_tier) : ""}</div>
          ${evidenceBlock(l.evidence)}</div>`;
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
          ${node.member_count ? `<strong>Records / members</strong> ${Number(node.member_count).toLocaleString()}<br>` : ""}
          ${node.connector ? `<strong>Connector</strong> ${esc(node.connector)}<br>` : ""}
          ${node.authority ? `<strong>Authority</strong> ${esc(node.authority)}<br>` : ""}
          ${node.source_path ? `<strong>Source</strong> <code>${esc(node.source_path)}</code><br>` : ""}
        </div>
        ${(node.source_paths || []).length > 1 ? `<details><summary>Source artifacts (${node.source_paths.length})</summary>${node.source_paths.map((path) => `<div class="answer-meta"><code>${esc(path)}</code></div>`).join("")}</details>` : ""}
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
    // Label density steps with zoom (see render): recompute labels only when a
    // threshold is crossed, not on every wheel tick, so zooming stays cheap.
    function labelBucket(k) { return k < 1.2 ? 0 : k < 2 ? 1 : k < 3 ? 2 : 3; }
    let lastBucket = 0;
    function zoomAround(px, py, factor) {
      const bx = (px - transform.x) / transform.k;
      const by = (py - transform.y) / transform.k;
      transform.k = clampScale(transform.k * factor);
      transform.x = px - bx * transform.k;
      transform.y = py - by * transform.k;
      const bucket = labelBucket(transform.k);
      if (bucket !== lastBucket) { lastBucket = bucket; render(); }
      else applyTransform();
    }
    function fit() { transform = { x: 0, y: 0, k: 1 }; render(); }

    svg.addEventListener("wheel", (e) => {
      e.preventDefault();
      const rect = svg.getBoundingClientRect();
      zoomAround(e.clientX - rect.left, e.clientY - rect.top, Math.exp(-e.deltaY * 0.0012));
    }, { passive: false });
    // Pointer events cover mouse AND touch: one-finger drag pans, two fingers pinch-zoom.
    let drag = null;
    let pinch = null;
    const activePointers = new Map();
    svg.addEventListener("pointerdown", (e) => {
      if (e.target.closest(".node") || e.target.closest(".link")) return;
      activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (svg.setPointerCapture) svg.setPointerCapture(e.pointerId);
      if (activePointers.size === 1) {
        drag = { id: e.pointerId, x: e.clientX, y: e.clientY, tx: transform.x, ty: transform.y };
      } else if (activePointers.size === 2) {
        drag = null;
        const [a, b] = [...activePointers.values()];
        pinch = { distance: Math.hypot(a.x - b.x, a.y - b.y) || 1, k: transform.k };
      }
    });
    svg.addEventListener("pointermove", (e) => {
      if (!activePointers.has(e.pointerId)) return;
      activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pinch && activePointers.size === 2) {
        const [a, b] = [...activePointers.values()];
        const rect = svg.getBoundingClientRect();
        const distance = Math.hypot(a.x - b.x, a.y - b.y) || 1;
        const targetK = clampScale(pinch.k * (distance / pinch.distance));
        zoomAround((a.x + b.x) / 2 - rect.left, (a.y + b.y) / 2 - rect.top, targetK / transform.k);
      } else if (drag && e.pointerId === drag.id) {
        transform.x = drag.tx + e.clientX - drag.x;
        transform.y = drag.ty + e.clientY - drag.y;
        applyTransform();
      }
    });
    const endPointer = (e) => {
      activePointers.delete(e.pointerId);
      if (activePointers.size < 2) pinch = null;
      if (drag && e.pointerId === drag.id) drag = null;
    };
    svg.addEventListener("pointerup", endPointer);
    svg.addEventListener("pointercancel", endPointer);
    svg.addEventListener("click", () => { clearSelection(); render(); });

    // ---------- legend ----------
    function renderLegend() {
      const present = [...new Set(view.nodes.map(displayType))].sort();
      const legend = document.getElementById("legend");
      legend.innerHTML =
        present.map((t) => `<div class="legend-row"><span class="swatch" style="background:${COLORS[t] || DEFAULT_COLOR}"></span>${esc(t === "ArchitectureGroup" ? "Architecture area" : friendlyLabel(t))}</div>`).join("") +
        `<div class="legend-row"><span class="swatch line" style="background:var(--accent)"></span>Key relationship</div>` +
        `<div class="legend-row"><span class="swatch line" style="background:#44566f"></span>Standard / inferred</div>` +
        `<div class="legend-row"><span class="swatch"></span>Architecture (circle)</div>` +
        `<div class="legend-row"><span class="swatch square"></span>Business data (square)</div>`;
    }

    // ---------- search across ALL entities (not just the plotted subset) ----------
    const resultsBox = document.getElementById("search-results");
    let searchTimer = null;
    let searchAbort = null;
    let searchRequest = 0;
    function renderSearchHits(hits) {
      if (!hits.length) {
        resultsBox.hidden = false;
        resultsBox.innerHTML = '<div class="result muted">No matches.</div>';
        return;
      }
      resultsBox.hidden = false;
      resultsBox.setAttribute("role", "listbox");
      resultsBox.innerHTML = hits.map((h) => {
        const plotted = nodeById.has(h.i);
        return `<div class="result" role="option" tabindex="0" data-id="${esc(h.i)}" data-wiki="${esc(h.w || "")}">
          <span class="result-name">${esc(h.n)}</span>
          <span class="result-meta">${esc(h.t || "")}${plotted ? "" : " · not plotted"}</span>
        </div>`;
      }).join("");
      resultsBox.querySelectorAll(".result[data-id]").forEach((row) => {
        row.addEventListener("click", () => focusEntity(row.dataset.id, row.dataset.wiki));
        row.addEventListener("keydown", (e) => {
          if (e.key === "Enter") { e.preventDefault(); focusEntity(row.dataset.id, row.dataset.wiki); }
          else if (e.key === "ArrowDown") { e.preventDefault(); (row.nextElementSibling || row).focus(); }
          else if (e.key === "ArrowUp") {
            e.preventDefault();
            if (row.previousElementSibling) row.previousElementSibling.focus();
            else searchInput.focus();
          }
        });
      });
    }
    function localSearch(query) {
      return searchIndex
        .filter((e) => String(e.n || "").toLowerCase().includes(query)
          || String(e.t || "").toLowerCase().includes(query))
        .slice(0, 40);
    }
    async function runRemoteSearch(query, layer, localHits, request) {
      if (window.location.protocol === "file:" || !data.entity_search_url) return;
      searchAbort = new AbortController();
      try {
        const params = new URLSearchParams({ q: query, layer, limit: "40" });
        const response = await fetch(`${data.entity_search_url}?${params}`, {
          cache: "no-store",
          signal: searchAbort.signal,
        });
        if (!response.ok) return;
        const payload = await response.json();
        if (request !== searchRequest
          || searchInput.value.trim().toLowerCase() !== query
          || layerSelect.value !== layer) return;
        renderSearchHits(payload.results || localHits);
      } catch (error) {
        // Visible-graph search remains available when the local API is offline.
      }
    }
    function scheduleSearch() {
      const query = searchInput.value.trim().toLowerCase();
      const request = ++searchRequest;
      if (searchTimer) clearTimeout(searchTimer);
      if (searchAbort) searchAbort.abort();
      if (query.length < 2) { resultsBox.hidden = true; resultsBox.innerHTML = ""; return; }
      const localHits = localSearch(query);
      renderSearchHits(localHits);
      const layer = layerSelect.value;
      searchTimer = setTimeout(() => runRemoteSearch(query, layer, localHits, request), 250);
    }
    function focusEntity(id, wikiUrl) {
      const request = ++focusRequest;
      if (nodeById.has(id)) {
        selectedId = id; selectedLinkId = null;
        showNodeDetails(id); render();
        if (history.replaceState) history.replaceState(null, "", "#node=" + encodeURIComponent(id));
        return;
      }
      // Not plotted: pull the full graph if we can, otherwise fall back to the wiki page.
      if (!fullLoaded) {
        loadFullGraph().then((ok) => {
          if (request !== focusRequest) return;
          if (ok && nodeById.has(id)) {
            selectedId = id; selectedLinkId = null;
            showNodeDetails(id); render();
            if (history.replaceState) history.replaceState(null, "", "#node=" + encodeURIComponent(id));
          }
          else if (wikiUrl) window.location.href = wikiUrl;
        });
      } else if (wikiUrl) {
        window.location.href = wikiUrl;
      }
    }

    // ---------- lazy-load the complete graph on demand ----------
    async function loadFullGraph() {
      if (fullLoaded) return true;
      if (fullGraphPromise) return fullGraphPromise;
      const btn = document.getElementById("load-full");
      if (btn) { btn.textContent = "Loading full graph…"; btn.disabled = true; }
      container.classList.add("loading");
      fullGraphPromise = (async () => {
        try {
          const resp = await fetch(data.full_graph_url, { cache: "no-store" });
          if (!resp.ok) throw new Error(`Graph request failed: ${resp.status}`);
          const full = await resp.json();
          allNodes = full.nodes || [];
          allLinks = full.links || [];
          nodeById = new Map(allNodes.map((n) => [n.id, n]));
          linkById = new Map(allLinks.map((l) => [l.id, l]));
          fullLoaded = true;
          if (btn) { btn.textContent = `Full graph loaded (${allNodes.length} nodes)`; btn.disabled = true; }
          relayout(); renderLegend();
          return true;
        } catch (err) {
          fullGraphPromise = null;
          if (btn) { btn.textContent = "Open graph.json (offline)"; btn.disabled = false; }
          return false;
        } finally {
          container.classList.remove("loading");
        }
      })();
      return fullGraphPromise;
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
    let layoutTimer = null;
    function scheduleRelayout() {
      if (layoutTimer) clearTimeout(layoutTimer);
      layoutTimer = setTimeout(() => {
        layoutTimer = null; relayout(); renderLegend();
      }, 120);
    }
    searchInput.addEventListener("input", () => { scheduleSearch(); updateUrlState(); scheduleRelayout(); });
    searchInput.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowDown") return;
      const first = resultsBox.querySelector(".result[data-id]");
      if (first) { e.preventDefault(); first.focus(); }
    });
    document.getElementById("load-full").addEventListener("click", loadFullGraph);
    document.getElementById("export-svg").addEventListener("click", exportSvg);
    document.getElementById("export-png").addEventListener("click", exportPng);
    predicateSelect.addEventListener("change", () => { updateUrlState(); scheduleRelayout(); });
    datasetSelect.addEventListener("change", () => { updateUrlState(); scheduleRelayout(); });
    layerSelect.addEventListener("change", () => {
      architectureFocus = null;
      updateUrlState();
      if (searchInput.value.trim().length >= 2) scheduleSearch();
      scheduleRelayout();
    });
    document.getElementById("key-only").addEventListener("click", (e) => {
      keyOnly = !keyOnly; e.currentTarget.classList.toggle("active", keyOnly); scheduleRelayout();
    });
    document.getElementById("reset").addEventListener("click", () => {
      searchInput.value = ""; predicateSelect.value = ""; datasetSelect.value = "";
      layerSelect.value = "repo";
      architectureFocus = null;
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
      document.getElementById("show-details").hidden = false;
      requestAnimationFrame(relayout);
    });
    document.getElementById("show-details").addEventListener("click", () => {
      app.classList.remove("details-collapsed");
      document.getElementById("show-details").hidden = true;
      requestAnimationFrame(relayout);
    });
    let resizeTimer = null;
    window.addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(relayout, 150);
    });

    const hint = document.getElementById("hint");
    hint.textContent = window.location.protocol === "file:"
      ? `Showing ${DATA.stats.shown_nodes} readable nodes. Serve the portal for full-corpus search across ${DATA.stats.total_nodes}.`
      : `Showing ${DATA.stats.shown_nodes} readable nodes. Search covers all ${DATA.stats.total_nodes} canonical entities.`;

    // Deep-link support: #node=<id> focuses that node on load.
    function applyHash() {
      const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
      const layer = params.get("layer") || data.kind || "repo";
      if (["all", "repo", "data"].includes(layer)) layerSelect.value = layer;
      searchInput.value = params.get("q") || "";
      architectureFocus = params.get("focus");
      refreshFacets();
      datasetSelect.value = params.get("dataset") || "";
      predicateSelect.value = params.get("relation") || "";
      relayout(); renderLegend();
      const node = params.get("node");
      if (node) focusEntity(node, null);
    }

    requestAnimationFrame(applyHash);
  }

  // ---------- answer-first GraphRAG ----------
  function renderAsk(data) {
    const host = document.getElementById("answer-app");
    host.hidden = false;
    host.innerHTML = `
      <div class="answer-hero">
        <div class="eyebrow">Neo4j GraphRAG</div>
        <h2>Ask your enterprise knowledge</h2>
        <p>Answers combine semantic retrieval, bounded graph traversal, and source evidence.</p>
        <form id="ask-form" class="ask-form">
          <textarea id="question" rows="3" placeholder="Ask about dependencies, evidence, ownership, or impact…"></textarea>
          <button id="ask-submit" type="submit">Ask Ontology Atlas</button>
        </form>
        <div class="suggestions">${(data.suggested_questions || []).map((q) =>
          `<button type="button" class="suggestion" data-question="${esc(q)}">${esc(q)}</button>`).join("")}</div>
        <div id="rag-status" class="status-card">Checking GraphRAG readiness…</div>
      </div>
      <div id="answer-result" class="answer-result" hidden></div>`;

    const status = document.getElementById("rag-status");
    const form = document.getElementById("ask-form");
    const question = document.getElementById("question");
    const submit = document.getElementById("ask-submit");
    const result = document.getElementById("answer-result");

    async function refreshStatus() {
      if (window.location.protocol === "file:") {
        status.className = "status-card warn";
        status.innerHTML = 'Live answers require <code>ontology-agent portal serve</code>. <a href="explore.html">Explore the graph offline →</a>';
        submit.disabled = true;
        return;
      }
      try {
        const response = await fetch(data.rag_status_url, { cache: "no-store" });
        const payload = await response.json();
        const ready = Boolean(payload.ready);
        const stale = Boolean(payload.stale);
        status.hidden = ready && !stale;
        status.className = `status-card ${ready && !stale ? "ready" : "warn"}`;
        status.textContent = ready && !stale
          ? ""
          : (payload.message || "GraphRAG is not indexed yet. Run ontology-agent rag index.");
        submit.disabled = !ready;
      } catch (error) {
        status.hidden = false;
        status.className = "status-card warn";
        status.textContent = "GraphRAG service is unavailable. Serve the portal from the project directory.";
        submit.disabled = true;
      }
    }

    function renderAnswer(payload) {
      const citations = payload.citations || payload.supporting_chunks || [];
      const paths = payload.paths || [];
      const answerHtml = payload.answer_html || `<p>${esc(payload.answer || "No answer returned.")}</p>`;
      const neighborhoodRows = paths.map((path) => {
        const summary = Array.isArray(path) ? path.join(" → ") : path.summary || String(path);
        const match = /^(.*?) -\[(.*?)\]-> (.*)$/.exec(summary);
        return match
          ? `<div class="mini-edge"><span class="mini-node">${esc(match[1])}</span><span class="mini-rel">${esc(friendlyRelation(match[2]))} →</span><span class="mini-node">${esc(match[3])}</span></div>`
          : `<div class="path-row">${esc(summary)}</div>`;
      });
      const neighborhood = neighborhoodRows.slice(0, 6).join("");
      const moreNeighborhood = neighborhoodRows.length > 6
        ? `<details class="more-paths"><summary>${neighborhoodRows.length - 6} more paths</summary>${neighborhoodRows.slice(6).join("")}</details>`
        : "";
      result.hidden = false;
      result.innerHTML = `
        <article class="answer-card">
          <h3>Grounded answer</h3>
          <div class="answer-copy">${answerHtml}</div>
          ${(payload.warnings || []).map((w) => `<div class="note">${esc(w)}</div>`).join("")}
        </article>
        <section class="answer-grid">
          <article class="card"><h3>Evidence</h3>${citations.length ? citations.map((c, i) => `
            <details ${i === 0 ? "open" : ""}><summary><a href="${sourceWikiHref(c.source_path || c.path)}">${esc(c.source_path || c.path || `Source ${i + 1}`)}</a></summary>
            <p class="evidence">${esc(c.evidence || c.text || "")}</p>
            <div class="answer-meta">${esc(c.evidence_level || "evidence_backed")}${c.score != null ? ` · score ${Number(c.score).toFixed(3)}` : ""}</div></details>`).join("") : '<p class="placeholder">No supporting evidence was retrieved.</p>'}</article>
          <article class="card"><h3>Answer neighborhood</h3>${neighborhood || '<p class="placeholder">No relationship path was returned.</p>'}${moreNeighborhood}</article>
        </section>`;
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const value = question.value.trim();
      if (!value) return;
      submit.disabled = true;
      submit.textContent = "Retrieving evidence…";
      result.hidden = false;
      result.innerHTML = '<div class="status-card">Searching the graph and its source evidence…</div>';
      try {
        const response = await fetch(data.rag_query_url, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: value }),
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || "GraphRAG query failed.");
        renderAnswer(payload);
      } catch (error) {
        result.innerHTML = `<div class="status-card warn">${esc(error.message || error)}</div>`;
      } finally {
        submit.disabled = false;
        submit.textContent = "Ask Ontology Atlas";
      }
    });
    document.querySelectorAll(".suggestion").forEach((button) => {
      button.addEventListener("click", () => {
        question.value = button.dataset.question || "";
        question.focus();
      });
    });
    refreshStatus();
  }

  // ---------- sources browser (full text straight from Neo4j) ----------
  function renderSources(data) {
    const host = document.getElementById("intel-app");
    host.hidden = false;
    if (window.location.protocol === "file:") {
      host.innerHTML = `<div class="empty-state">Browsing source text requires the live portal.<br>
        Run <code>ontology-agent portal serve</code> and reload this page.</div>`;
      return;
    }
    host.innerHTML = `
      <section class="intel-section sources-app">
        <h2>Ingested sources</h2>
        <p class="lead">Every source stored in Neo4j, with its full text. Documents are chunked;
        code and structured artifacts show their extracted evidence spans.</p>
        <input id="source-filter" placeholder="Filter sources by path or type…" autocomplete="off"
          aria-label="Filter sources">
        <div class="sources-split">
          <div id="source-list" class="sources-list" role="listbox" aria-label="Sources">
            <p class="placeholder">Loading sources…</p>
          </div>
          <div id="source-body" class="source-body">
            <p class="placeholder">Select a source to read its full text.</p>
          </div>
        </div>
      </section>`;
    const list = document.getElementById("source-list");
    const body = document.getElementById("source-body");
    const filter = document.getElementById("source-filter");
    let sources = [];
    let activeId = null;

    function renderList() {
      const query = filter.value.trim().toLowerCase();
      const visible = sources.filter((s) =>
        !query || s.path.toLowerCase().includes(query) || s.source_type.toLowerCase().includes(query));
      list.innerHTML = visible.map((s) => {
        const pieces = String(s.path || s.title).split("/");
        const file = pieces.pop();
        const dir = pieces.length ? pieces.join("/") + "/" : "";
        const count = s.chunk_count
          ? `${s.chunk_count} chunk${s.chunk_count === 1 ? "" : "s"}`
          : s.span_count ? `${s.span_count} span${s.span_count === 1 ? "" : "s"}` : "";
        return `
        <div class="result source-row${s.id === activeId ? " active" : ""}" role="option"
          tabindex="0" aria-selected="${s.id === activeId}" data-id="${esc(s.id)}">
          <div class="source-path"><span class="source-dir">${esc(dir)}</span>${esc(file)}</div>
          <div class="source-meta"><span class="chip">${esc(s.source_type)}</span>${count ? `<span class="source-count">${count}</span>` : ""}</div>
        </div>`;
      }).join("") || '<p class="placeholder">No sources match.</p>';
      list.querySelectorAll(".source-row").forEach((row) => {
        const open = () => openSource(row.dataset.id);
        row.addEventListener("click", open);
        row.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
        });
      });
    }

    async function openSource(id) {
      activeId = id;
      renderList();
      const source = sources.find((s) => s.id === id);
      body.innerHTML = '<p class="placeholder">Loading text…</p>';
      try {
        const response = await fetch(`${data.sources_url}/${encodeURIComponent(id)}`, { cache: "no-store" });
        if (!response.ok) throw new Error(response.status === 404 ? "This source has no stored text." : "Source text is unavailable.");
        const payload = await response.json();
        body.innerHTML = `
          <h3 class="detail-title">${esc(source ? source.path : id)}</h3>
          ${(payload.chunks || []).map((chunk) => `<pre class="source-text">${esc(chunk.text)}</pre>`).join("")}`;
      } catch (error) {
        body.innerHTML = `<div class="status-card warn">${esc(error.message || error)}</div>`;
      }
    }

    filter.addEventListener("input", renderList);
    fetch(data.sources_url, { cache: "no-store" })
      .then((response) => { if (!response.ok) throw new Error("Source listing is unavailable."); return response.json(); })
      .then((payload) => { sources = payload.sources || []; renderList(); })
      .catch((error) => { list.innerHTML = `<div class="status-card warn">${esc(error.message || error)}</div>`; });
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
    const hotspots = intel.impact_hotspots || [];
    const boundaries = intel.cross_boundaries || [];
    const lineage = intel.data_lineage || [];
    const orphans = intel.orphan_groups || [];
    const ownership = intel.ownership_gaps || [];
    const relationshipRows = (rows) => rows.map((row) => `
      <div class="card">
        <div class="card-title">${esc(row.source)} <span class="card-sub">${esc(friendlyRelation(row.predicate))}</span> ${esc(row.target)}</div>
        <div class="card-sub">${esc(row.source_area || row.source_type || "")}${row.target_area || row.target_type ? " → " + esc(row.target_area || row.target_type) : ""}</div>
        ${Number(row.count || 0) > 1 ? `<div class="answer-meta">${Number(row.count).toLocaleString()} supporting relationships</div>` : ""}
        ${row.evidence ? `<p class="evidence">${esc(row.evidence)}</p>` : ""}
        ${row.source_path ? `<div class="answer-meta">${esc(row.source_path)}</div>` : ""}
      </div>`).join("") || '<p class="placeholder">No findings in this category.</p>';
    // Ranked bar chart: bar length is comparative degree, so the biggest change
    // radius reads at a glance instead of as a wall of identical number cards.
    const maxDegree = Math.max(1, ...hotspots.map((item) => Number(item.degree || 0)));
    const truncatedList = (items, render) => items.slice(0, 6).map(render).join("")
      + (items.length > 6 ? `<div class="card-sub">+${items.length - 6} more</div>` : "");
    host.innerHTML = `
      <section class="intel-section"><h2>Impact hotspots</h2>
        <p class="lead">Measured fan-in and fan-out identify components with the largest likely change radius. This is an inspection priority, not an automatic refactor verdict.</p>
        <div class="hotspot-chart">${hotspots.map((item, index) => `<div class="card hotspot-card">
          <div class="hotspot">
            <span class="rank">${index + 1}</span>
            <div class="hotspot-main">
              <div class="card-title">${esc(item.name)} <span class="card-sub">${Number(item.degree || 0)} connections</span></div>
              <div class="bar"><span style="width:${Math.max(3, Math.round(Number(item.degree || 0) / maxDegree * 100))}%"></span></div>
              <div class="answer-meta">${esc(friendlyLabel(item.type))} · ${esc(item.area || "Unassigned")} · ${Number(item.fan_in || 0)} incoming · ${Number(item.fan_out || 0)} outgoing${item.source_path ? ` · ${esc(item.source_path)}` : ""}</div>
            </div>
          </div></div>`).join("") || '<p class="placeholder">No actionable hotspots detected.</p>'}</div>
      </section>
      <section class="intel-section"><h2>Cross-area dependencies</h2><p class="lead">Evidence-backed relationships that cross architecture boundaries.</p><div class="grid cols-2">${relationshipRows(boundaries)}</div></section>
      <section class="intel-section"><h2>Model and data lineage</h2><p class="lead">Connections between architecture, datasets, models, predictions, and outputs.</p><div class="grid cols-2">${relationshipRows(lineage)}</div></section>
      <section class="intel-section"><h2>Knowledge gaps</h2><p class="lead">Concrete omissions that reduce answer quality or ownership clarity.</p><div class="grid cols-3">
        <div class="card"><div class="card-title">Orphaned mapped records</div><div class="metric-inline">${orphans.reduce((sum, item) => sum + Number(item.count || 0), 0)}</div><div class="answer-meta">Mapped records with no graph relationships.</div>${truncatedList(orphans, (item) => `<div class="card-sub">${esc(item.dataset)} · ${esc(item.type)}: ${Number(item.count)}</div>`)}</div>
        <div class="card"><div class="card-title">Datasets without ownership</div><div class="metric-inline">${ownership.length}</div><div class="answer-meta">Datasets whose records declare no owner.</div>${truncatedList(ownership, (item) => `<div class="card-sub">${esc(item.dataset)} · ${Number(item.records)} records</div>`)}</div>
        <div class="card"><div class="card-title">Relationships without evidence</div><div class="metric-inline">${Number((intel.evidence_gaps || {}).relationships_without_evidence || 0)}</div><div class="answer-meta">Relationships lacking a source path, evidence text, or source span.</div></div>
      </div></section>`;
  }

  // ---------- changes (run-to-run diff) ----------
  function renderChanges(changes) {
    const host = document.getElementById("intel-app");
    host.hidden = false;
    if (!changes || !changes.has_baseline) {
      host.innerHTML = `<div class="empty-state">No prior run to compare against yet.<br>
        Re-run <code>ontology-agent launch</code> after your sources change and this tab will show
        exactly what was added, removed and modified.</div>`;
      return;
    }
    if (!changes.compatible) {
      host.innerHTML = `<section class="intel-section"><h2>Comparison intentionally stopped</h2>
        <div class="status-card warn">${esc(changes.incompatibility_reason || "The two runs used incompatible ingestion scopes.")}</div>
        <p class="lead">Use this run as the new baseline. The next run with the same sources, mappings, limits, and extraction settings will produce a trustworthy change report.</p></section>`;
      return;
    }
    const s = changes.summary;
    const changed = s.entities_added + s.entities_removed + s.entities_modified
      + s.relationships_added + s.relationships_removed;
    if (!changed) {
      host.innerHTML = `<div class="empty-state"><strong>No knowledge changes detected.</strong><br>
        The current run matches its compatible baseline. Change a source or structured-data artifact,
        then run <code>ontology-agent launch</code> again to see its impact.</div>`;
      return;
    }
    const entityGroups = (rows) =>
      rows.map((r) => `<div class="card">
        <div class="card-title">${esc(r.label)}</div>
        <div class="metric-inline">${Number(r.count).toLocaleString()}</div>
        <div class="card-sub">${esc(r.category)}${r.change ? ` · ${esc(r.change)}` : ""}</div>
        ${(r.representatives || []).map((name) => `<span class="chip">${esc(name)}</span>`).join("")}
      </div>`).join("") || `<p class="placeholder">None.</p>`;
    const relationshipGroups = (rows) => rows.map((r) => `<div class="card">
      <div class="card-title">${esc(r.source)} → ${esc(r.target)}</div>
      <div class="card-sub">${esc(friendlyRelation(r.predicate))} · ${Number(r.count).toLocaleString()} relationship${Number(r.count) === 1 ? "" : "s"}</div>
    </div>`).join("") || `<p class="placeholder">None.</p>`;
    const addedArchitecture = changes.entity_groups_added.filter((r) => r.category === "Architecture").map((r) => ({ ...r, change: "Added" }));
    const removedArchitecture = changes.entity_groups_removed.filter((r) => r.category === "Architecture").map((r) => ({ ...r, change: "Removed" }));
    const addedData = changes.entity_groups_added.filter((r) => r.category === "Business data").map((r) => ({ ...r, change: "Added" }));
    const removedData = changes.entity_groups_removed.filter((r) => r.category === "Business data").map((r) => ({ ...r, change: "Removed" }));
    const sections = [];

    sections.push(`<div class="intel-section">
      <h2>Since the last run</h2>
      <p class="lead">A decision-level summary grouped by architecture area, dataset, business concept, and relationship type. Individual records stay out of the primary view.</p>
      <div class="grid cols-3">
        <div class="card"><div class="card-title">+${s.architecture_entities_added} / −${s.architecture_entities_removed}</div><div class="card-sub">architecture components</div></div>
        <div class="card"><div class="card-title">+${s.business_records_added} / −${s.business_records_removed}</div><div class="card-sub">business records</div></div>
        <div class="card"><div class="card-title">~${s.entities_modified}</div><div class="card-sub">components modified</div></div>
        <div class="card"><div class="card-title">+${s.architecture_relationships_added} / −${s.architecture_relationships_removed}</div><div class="card-sub">architecture relationships</div></div>
        <div class="card"><div class="card-title">+${s.business_relationships_added} / −${s.business_relationships_removed}</div><div class="card-sub">business-data relationships</div></div>
      </div>
    </div>`);

    if (addedArchitecture.length || removedArchitecture.length || changes.modified_components.length) {
      sections.push(`<div class="intel-section"><h2>Architecture and schema changes</h2>
        <p class="lead">Stable components and boundaries—not volatile row-level events.</p>
        <div class="grid cols-3">${entityGroups([...addedArchitecture, ...removedArchitecture])}</div></div>`);
    }

    if (addedData.length || removedData.length) {
      sections.push(`<div class="intel-section"><h2>Business-data movement</h2>
        <p class="lead">Record movement grouped by dataset and business concept. Only useful human names are shown.</p>
        <div class="grid cols-3">${entityGroups([...addedData, ...removedData])}</div></div>`);
    }

    if (changes.modified_components.length) {
      sections.push(`<div class="intel-section"><h2>Modified architecture components</h2>
        <div class="grid cols-2">${changes.modified_components.map((m) => `
          <div class="card"><div class="card-title">${esc(m.name)}</div>
          <div class="card-sub">${esc(m.type)}</div>
          <div class="answer-meta">Changed: ${m.fields.map(esc).join(", ")}</div>
          </div>`).join("")}</div></div>`);
    }

    if ((changes.affected_components || []).length) {
      sections.push(`<div class="intel-section"><h2>Affected upstream and downstream areas</h2>
        <p class="lead">Direct neighbors of changed knowledge, grouped to avoid raw-record noise.</p>
        <div class="grid cols-3">${changes.affected_components.map((item) => `<div class="card">
          <div class="card-title">${esc(item.name)}</div>
          <div class="card-sub">${esc(item.direction)} · ${esc(item.type)} · ${esc(item.area)}</div>
          <div class="answer-meta">${Number(item.relationship_count).toLocaleString()} affected relationship${Number(item.relationship_count) === 1 ? "" : "s"}</div>
          ${(item.predicates || []).map((predicate) => `<span class="chip">${esc(friendlyRelation(predicate))}</span>`).join("")}
        </div>`).join("")}</div></div>`);
    }

    if (changes.relationship_groups_added.length) sections.push(`<div class="intel-section"><h2>New relationships</h2>
      <div class="grid cols-2">${relationshipGroups(changes.relationship_groups_added)}</div></div>`);
    if (changes.relationship_groups_removed.length) sections.push(`<div class="intel-section"><h2>Removed relationships</h2>
      <div class="grid cols-2">${relationshipGroups(changes.relationship_groups_removed)}</div></div>`);
    host.innerHTML = sections.join("");
  }
})();
