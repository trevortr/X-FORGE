const ui = {
  select: document.querySelector("#run-select"),
  refresh: document.querySelector("#refresh"),
  reset: document.querySelector("#reset"),
  revealAll: document.querySelector("#reveal-all"),
  showAllEdges: document.querySelector("#show-all-edges"),
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
ui.reset.addEventListener("click", () => {
  expanded = new Set();
  clearInspector();
  renderGraph();
});
loadRuns();
