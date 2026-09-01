# Run visualizer

The visualizer is a persistent, read-only web interface for completed X-FORGE
runs. It discovers `run.json` files beneath the mounted results directory and
builds molecule provenance with NetworkX and renders it as Matplotlib SVG.

## Interaction

- Only the run's initial hit molecules are displayed when a run is loaded.
- Clicking a visible molecule reveals its immediate generated children;
  clicking it again collapses that branch.
- Hovering over any molecule shows an RDKit-rendered 2D structure, its SMILES,
  stable ID, observed iterations, parent IDs, generator metadata, and
  append-only score history.
- Reveal whole graph expands every default lineage branch at once. Reset
  returns the graph to the initial hits.
- By default, the graph uses one earliest-observed parent per molecule and
  suppresses cycles. Show all edges includes repeated-parent and cyclic
  relationships between the molecules currently visible without changing the
  clean tree used for node expansion.
- Leaf molecules are squares; molecules with children are circles (initial
  hits retain their diamond marker).
- SMILES labels are hidden by default and can be enabled explicitly. The
  viewport toolbar provides zoom in/out, fit, four-direction panning, separate
  horizontal/vertical canvas expansion, and view reset controls.

Edges are reconstructed from every iteration's `generated` population rather
than only from the deduplicated molecule catalog. If the same stable molecule
appears from different parents during a run, every observed relationship is
retained and is available through Show all edges.

## Run

Start the viewer independently of the one-shot orchestrator:

```bash
docker compose up --build -d visualizer
```

Open <http://localhost:12010>. The `./results` host directory is mounted
read-only, and the run picker discovers new runs whenever it is refreshed.

NetworkX uses each molecule's earliest observed iteration for a deterministic
layered layout. Matplotlib creates the SVG and tags each node artist with a safe
DOM identifier; the browser only handles expansion and metadata interaction.
There is no JavaScript graph library or external CDN dependency.

## Tests

```bash
PYTHONPATH=services/visualizer pytest services/visualizer/tests
```
