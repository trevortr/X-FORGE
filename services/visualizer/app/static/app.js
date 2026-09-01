const ui = {
  select: document.querySelector("#run-select"),
  refresh: document.querySelector("#refresh"),
  reset: document.querySelector("#reset"),
  revealAll: document.querySelector("#reveal-all"),
  showAllEdges: document.querySelector("#show-all-edges"),
  showLabels: document.querySelector("#show-labels"),
  zoomOut: document.querySelector("#zoom-out"),
  zoomFit: document.querySelector("#zoom-fit"),
  zoomIn: document.querySelector("#zoom-in"),
  zoomValue: document.querySelector("#zoom-value"),
  panLeft: document.querySelector("#pan-left"),
  panUp: document.querySelector("#pan-up"),
  panDown: document.querySelector("#pan-down"),
  panRight: document.querySelector("#pan-right"),
  expandHorizontal: document.querySelector("#expand-horizontal"),
  expandVertical: document.querySelector("#expand-vertical"),
  resetView: document.querySelector("#reset-view"),
  target: document.querySelector("#target"),
  status: document.querySelector("#status"),
  iterations: document.querySelector("#iterations"),
  visible: document.querySelector("#visible"),
  graph: document.querySelector("#graph"),
  inspector: document.querySelector("#inspector"),
  message: document.querySelector("#message"),
};

let runs = [];
let selectedRun;
let expanded = new Set();
let renderVersion = 0;
let zoom = 1;
let horizontalScale = 1;
let verticalScale = 1;
let canvasSize = { width: 800, height: 520 };

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed (${response.status})`);
  }
  return response.json();
}

function notify(message) {
  ui.message.textContent = message;
  ui.message.classList.add("shown");
  window.setTimeout(() => ui.message.classList.remove("shown"), 2000);
}

async function loadRuns() {
  ui.select.disabled = true;
  try {
    ({ runs } = await fetchJson("/api/runs"));
    ui.select.replaceChildren();
    if (!runs.length) {
      ui.select.append(new Option("No result sets found", ""));
      showEmpty("No result sets found", "Complete a pipeline run, then refresh.");
      return;
    }
    for (const run of runs) {
      ui.select.append(new Option(`${run.name} — ${run.target ?? "unknown"}`, run.name));
    }
    ui.select.disabled = false;
    const requested = new URLSearchParams(window.location.search).get("run");
    ui.select.value = runs.some((run) => run.name === requested) ? requested : runs[0].name;
    await selectRun(ui.select.value);
  } catch (error) {
    notify(error.message);
    showEmpty("Results unavailable", "The service could not read the results directory.");
  }
}

async function selectRun(runName) {
  selectedRun = runs.find((run) => run.name === runName);
  if (!selectedRun) return;
  expanded = new Set();
  const url = new URL(window.location.href);
  url.searchParams.set("run", runName);
  window.history.replaceState({}, "", url);
  ui.target.textContent = selectedRun.target ?? selectedRun.name;
  ui.status.textContent = selectedRun.status ?? "—";
  ui.status.dataset.value = selectedRun.status ?? "";
  ui.iterations.textContent = selectedRun.completed_iterations ?? "—";
  ui.reset.disabled = false;
  ui.revealAll.disabled = false;
  ui.showAllEdges.disabled = false;
  ui.showAllEdges.checked = false;
  ui.showLabels.disabled = false;
  ui.showLabels.checked = false;
  resetViewportState();
  setViewportControlsDisabled(false);
  clearInspector();
  await renderGraph();
}

async function renderGraph(showAll = false) {
  const version = ++renderVersion;
  ui.graph.classList.add("loading");
  try {
    const query = new URLSearchParams();
    for (const moleculeId of [...expanded].sort()) query.append("expanded", moleculeId);
    if (showAll) query.set("show_all", "true");
    if (ui.showAllEdges.checked) query.set("show_all_edges", "true");
    if (ui.showLabels.checked) query.set("show_labels", "true");
    if (horizontalScale !== 1) query.set("horizontal_scale", horizontalScale.toString());
    if (verticalScale !== 1) query.set("vertical_scale", verticalScale.toString());
    const suffix = query.size ? `?${query}` : "";
    const view = await fetchJson(
      `/api/runs/${encodeURIComponent(selectedRun.name)}/graph${suffix}`,
    );
    if (version !== renderVersion) return;
    const parsed = new DOMParser().parseFromString(view.svg, "image/svg+xml");
    const svg = parsed.documentElement;
    if (svg.localName !== "svg" || parsed.querySelector("parsererror")) {
      throw new Error("The server returned invalid SVG");
    }
    svg.removeAttribute("width");
    svg.removeAttribute("height");
    svg.classList.add("lineage-svg");
    ui.graph.replaceChildren(document.importNode(svg, true));
    canvasSize = {
      width: view.canvas_width ?? 800,
      height: view.canvas_height ?? 520,
    };
    applyZoom();
    ui.visible.textContent = `${view.visible_count} / ${view.total_count}`;
    expanded = new Set(
      view.nodes.filter((node) => node.expanded && node.has_children).map((node) => node.id),
    );
    ui.revealAll.disabled = view.fully_expanded;
    bindNodes(view.nodes);
  } catch (error) {
    notify(error.message);
    showEmpty("Graph unavailable", error.message);
  } finally {
    ui.graph.classList.remove("loading");
  }
}

function setViewportControlsDisabled(disabled) {
  for (const control of [
    ui.zoomOut,
    ui.zoomFit,
    ui.zoomIn,
    ui.panLeft,
    ui.panUp,
    ui.panDown,
    ui.panRight,
    ui.expandHorizontal,
    ui.expandVertical,
    ui.resetView,
  ]) {
    control.disabled = disabled;
  }
}

function setZoom(value) {
  zoom = Math.min(3, Math.max(0.15, value));
  applyZoom();
}

function fitGraph() {
  const availableWidth = Math.max(ui.graph.clientWidth - 8, 1);
  const availableHeight = Math.max(ui.graph.clientHeight - 8, 1);
  setZoom(Math.min(
    availableWidth / canvasSize.width,
    availableHeight / canvasSize.height,
  ));
}

function panGraph(horizontal, vertical) {
  ui.graph.scrollBy({
    left: horizontal * ui.graph.clientWidth * 0.65,
    top: vertical * ui.graph.clientHeight * 0.65,
    behavior: "smooth",
  });
}

async function expandCanvas(axis) {
  const oldWidth = canvasSize.width * zoom;
  const oldHeight = canvasSize.height * zoom;
  const centerX = (ui.graph.scrollLeft + ui.graph.clientWidth / 2) / oldWidth;
  const centerY = (ui.graph.scrollTop + ui.graph.clientHeight / 2) / oldHeight;
  if (axis === "horizontal") horizontalScale = Math.min(4, horizontalScale * 1.25);
  if (axis === "vertical") verticalScale = Math.min(4, verticalScale * 1.25);
  await renderGraph();
  window.requestAnimationFrame(() => {
    const newWidth = canvasSize.width * zoom;
    const newHeight = canvasSize.height * zoom;
    ui.graph.scrollTo({
      left: centerX * newWidth - ui.graph.clientWidth / 2,
      top: centerY * newHeight - ui.graph.clientHeight / 2,
    });
  });
}

function resetViewportState() {
  zoom = 1;
  horizontalScale = 1;
  verticalScale = 1;
  applyZoom();
  ui.graph.scrollTo({ left: 0, top: 0 });
}

async function resetViewport() {
  const needsRender = horizontalScale !== 1 || verticalScale !== 1;
  resetViewportState();
  if (selectedRun && needsRender) await renderGraph();
}

function applyZoom() {
  ui.zoomValue.textContent = `${Math.round(zoom * 100)}% · ${horizontalScale.toFixed(1)}×${verticalScale.toFixed(1)}`;
  const svg = ui.graph.querySelector("svg");
  if (!svg) return;
  svg.style.width = `${Math.round(canvasSize.width * zoom)}px`;
  svg.style.height = `${Math.round(canvasSize.height * zoom)}px`;
}

function bindNodes(nodes) {
  const svg = ui.graph.querySelector("svg");
  const elements = new Map(
    [...svg.querySelectorAll("[id]")].map((element) => [element.id, element]),
  );
  for (const node of nodes) {
    const targets = [
      elements.get(`node-${node.dom_id}`),
      elements.get(`label-${node.dom_id}`),
    ].filter(Boolean);
    for (const target of targets) {
      target.classList.add("molecule-target");
      target.setAttribute("tabindex", "0");
      target.setAttribute("role", "button");
      target.addEventListener("mouseenter", () => showInspector(node));
      target.addEventListener("focus", () => showInspector(node));
      target.addEventListener("click", () => toggleNode(node));
      target.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") toggleNode(node);
      });
    }
  }
}

function toggleNode(node) {
  showInspector(node);
  if (!node.has_children) {
    notify("No generated children");
    return;
  }
  if (node.expanded) {
    expanded.delete(node.id);
    notify("Children hidden");
  } else {
    expanded.add(node.id);
  }
  renderGraph();
}

function showInspector(node) {
  const molecule = node.molecule;
  const fragment = document.createDocumentFragment();
  fragment.append(textElement("p", node.is_root ? "Initial hit" : "Generated molecule", "kicker"));
  fragment.append(textElement("h2", molecule.smiles ?? node.id));
  fragment.append(structurePreview(molecule.smiles, node.id));
  const facts = document.createElement("dl");
  facts.className = "facts";
  addFact(facts, "Molecule ID", node.id);
  addFact(facts, "Iterations", node.iterations.join(", ") || molecule.iteration);
  addFact(facts, "Parent IDs", node.parents.join(", ") || "None");
  addFact(facts, "Generator", molecule.generator_model ?? "—");
  if (molecule.pareto_rank !== undefined) addFact(facts, "Pareto rank", molecule.pareto_rank);
  if (molecule.selection_score !== undefined) {
    addFact(facts, "Selection score", formatValue(molecule.selection_score));
  }
  fragment.append(facts);
  fragment.append(textElement("h3", `Score history · ${molecule.scores?.length ?? 0}`));
  for (const score of molecule.scores ?? []) {
    const card = document.createElement("section");
    card.className = "score";
    card.append(textElement("strong", `${score.stage} · iteration ${score.computed_at_iteration}`));
    const values = document.createElement("dl");
    for (const [name, value] of Object.entries(score.values ?? {})) {
      addFact(values, name, formatValue(value));
    }
    if (score.passed !== null && score.passed !== undefined) {
      addFact(values, "passed", String(score.passed));
    }
    card.append(values);
    fragment.append(card);
  }
  ui.inspector.replaceChildren(fragment);
}

function structurePreview(smiles, moleculeId) {
  const preview = document.createElement("figure");
  preview.className = "structure-preview";
  if (!smiles) {
    preview.append(textElement("p", "No SMILES available for depiction.", "quiet"));
    return preview;
  }
  const image = document.createElement("img");
  image.alt = `2D molecular structure for ${moleculeId}`;
  image.decoding = "async";
  image.src = `/api/depict?smiles=${encodeURIComponent(smiles)}`;
  image.addEventListener("error", () => {
    preview.replaceChildren(textElement("p", "Structure depiction unavailable.", "quiet"));
  });
  preview.append(image);
  return preview;
}

function clearInspector() {
  ui.inspector.replaceChildren(
    textElement("p", "Molecule details", "kicker"),
    textElement("h2", "Hover over a node"),
    textElement("p", "Provenance and score history will appear here.", "quiet"),
  );
}

function textElement(tag, value, className) {
  const element = document.createElement(tag);
  element.textContent = value;
  if (className) element.className = className;
  return element;
}

function addFact(list, name, value) {
  list.append(textElement("dt", name), textElement("dd", value ?? "—"));
}

function formatValue(value) {
  return typeof value === "number" ? Number(value).toPrecision(5) : String(value);
}

function showEmpty(title, copy) {
  const container = document.createElement("div");
  container.className = "empty";
  container.append(textElement("strong", title), textElement("span", copy));
  ui.graph.replaceChildren(container);
}

ui.select.addEventListener("change", () => selectRun(ui.select.value));
ui.refresh.addEventListener("click", loadRuns);
ui.revealAll.addEventListener("click", () => renderGraph(true));
ui.showAllEdges.addEventListener("change", () => renderGraph());
ui.showLabels.addEventListener("change", () => renderGraph());
ui.zoomOut.addEventListener("click", () => setZoom(zoom / 1.25));
ui.zoomIn.addEventListener("click", () => setZoom(zoom * 1.25));
ui.zoomFit.addEventListener("click", fitGraph);
ui.panLeft.addEventListener("click", () => panGraph(-1, 0));
ui.panUp.addEventListener("click", () => panGraph(0, -1));
ui.panDown.addEventListener("click", () => panGraph(0, 1));
ui.panRight.addEventListener("click", () => panGraph(1, 0));
ui.expandHorizontal.addEventListener("click", () => expandCanvas("horizontal"));
ui.expandVertical.addEventListener("click", () => expandCanvas("vertical"));
ui.resetView.addEventListener("click", resetViewport);
ui.reset.addEventListener("click", () => {
  expanded = new Set();
  resetViewportState();
  clearInspector();
  renderGraph();
});
window.addEventListener("resize", applyZoom);
loadRuns();
