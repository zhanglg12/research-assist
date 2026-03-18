# Profile Map Generation

Use this note when OpenClaw refreshes `profiles/research-interest.json`.

Goal:

- generate a profile that looks like the user's research map
- avoid collapsing the profile into a loose bag of keywords

Think like a painter:

- `collection` structure is the sketch
- representative papers are the main pigments
- semantic search is the blending layer between nearby regions

## Evidence priority

Use evidence in this order:

1. collection / sub-collection structure
2. representative papers inside those regions
3. semantic neighbors that connect nearby themes
4. summary terms for wording refinement

Rules:

- treat collection names as strong priors, not final truth
- if collection names and paper content disagree, trust the papers more
- use semantic neighbors to connect nearby regions, not to flatten everything into one topic
- use high-frequency terms to polish labels and aliases, not to define the map by themselves

## What a good profile looks like

A good profile should feel like a compact research atlas:

- a few clear regions
- target about 6 regions by default
- keep the usual range around 4-8 regions unless the evidence is unusually sparse or unusually fragmented
- each region centered on a stable method axis
- short labels
- retrieval-friendly aliases
- little overlap between regions

Examples of good region styles:

- `GP + PDE`
- `Bilevel + Hyperparameter`
- `Random Feature PDE`
- `PINN Variants`

Examples of weak region styles:

- `AI for Science`
- `Machine Learning`
- `Optimization`

## Compression rule

When many papers cluster together, compress them into one method-oriented slice.

When one collection mixes several distinct methods, split them into multiple slices.

If the draft profile has fewer than about 4 regions, it is usually over-compressed.

If the draft profile has more than about 8 regions, it is usually too fragmented for a digest-oriented research map.

Do not preserve the folder tree literally in the final profile.
Preserve the map structure, not the raw directory listing.

## OpenClaw generation rule

Before writing the final profile, ask:

1. What is the main region implied by the collection structure?
2. Which representative papers prove that this region is real?
3. What neighboring regions are revealed by semantic search?
4. What short label and aliases would retrieve this region on arXiv without spilling too far?
5. Does the full profile land near the default target of about 6 regions? If not, should it be compressed or split?

The final profile should read like a map drawn by a careful curator, not a dump of folders, and not a cloud of generic terms.
