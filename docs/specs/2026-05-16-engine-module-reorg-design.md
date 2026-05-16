# `gaia.engine` Module Reorganization Design

**Status:** Design proposal for v0.5 follow-up
**Date:** 2026-05-16
**Branch:** off `v0.5`
**Related PRs:** TBD (reorg PR a + reorg PR b)
**Builds on:** `docs/specs/2026-05-15-causal-cleanup-reasoning-shapes.md` (BayesInference shape decision)
**Scope:** Two coordinated reorganizations of first- and second-level modules under `gaia.engine`:
  1. consolidate single-file packages (`engine.lang.types/`) and demote `engine.logic/` to `engine.ir.logic/` (PR a, small)
  2. promote `engine.lang.bayes/` to peer `engine.bayes/` and align Bayes verb directory naming (PR b, medium)

**Non-goals:** Do not flatten the entire engine into a single layer. Do not rename `engine.lang/` to `engine.core/`. Do not move `lang.runtime/`, `lang.dsl/`, `lang.compiler/` out of `lang/`. Do not introduce a new IR data model. Do not change BP, inquiry, or trace top-level layout.

## 1. Motivation

PR #606 + #609 landed `BayesInference(Reasoning)` as a runtime-level first-class concept (per `docs/specs/2026-05-15-causal-cleanup-reasoning-shapes.md` §4.2). The class hierarchy now treats Bayes as a top-level reasoning family. The Python module layout, however, still nests Bayes five levels deep at `gaia.engine.lang.bayes.*`. This is an **inconsistency between the runtime hierarchy decision and the module path** that should be resolved before more reasoning families (causal, statistics, ...) land and inherit the same layout.

Three smaller issues compound:

1. `gaia.engine.lang.types/` is a sub-package shell containing one file (`primitives.py`). It is over-structure: the four primitive types (Bool/Nat/Real/Probability) are formula-domain concepts and belong with the formula AST.

2. `gaia.engine.logic/` is the only top-level engine peer that has no Gaia-native abstractions of its own — it is a thin sympy-on-IR analysis layer. By the same criterion that places `bp/`, `inquiry/`, `lang/`, `trace/` at the top level (each owns substantial concept layer), `logic/` belongs as an IR sub-module under `engine.ir.logic/`.

3. The Bayes verb directory is named `bayes.verbs/` while the core verb directory is named `lang.dsl/`. After Bayes is promoted to peer, the asymmetry surfaces in the public import path.

This spec proposes the minimal coordinated reorg that resolves all four issues, frames `engine.lang/` as a host module with `engine.bayes/` as a peer extension, and sets a precedent for future extensions.

## 2. Current Code Facts

(based on `origin/codex/remove-excluded-foundation-dsl` head — i.e., v0.5 + PR #606 + PR #609)

```
gaia/engine/
├── _stale_check.py
├── packaging.py
├── bp/                        # 10 modules — Belief Propagation engine
├── inquiry/                   # 13 modules — goal-tree analysis
├── ir/                        # 12 modules — Intermediate Representation
├── lang/
│   ├── runtime/               # 11 modules — Knowledge / Reasoning / Scaffold dataclasses
│   ├── compiler/              # 5 modules — lang AST → IR
│   ├── dsl/                   # 15 modules — public verbs (derive, equal, ...)
│   ├── formula/               # 5 modules — predicate logic AST
│   ├── bayes/                 # ← extension nested inside lang
│   │   ├── runtime/
│   │   ├── verbs/             # ← naming inconsistent with lang.dsl/
│   │   ├── compiler/
│   │   ├── distributions/
│   │   └── adapters/
│   ├── refs/                  # 6 modules — @label resolution
│   ├── review/                # 3 modules — review manifest gen
│   └── types/                 # ← single file (primitives.py)
├── logic/                     # ← single file (propositional.py); only top-level peer with no own abstraction
└── trace/                     # 9 modules
```

Tombstone infrastructure (`gaia/_legacy_imports.py`) is already in place for the alpha-0 `gaia.<old> → gaia.engine.<new>` migration:

- `_tombstoned_namespace_getattr(old, new)` redirects attribute access
- `TOMBSTONED_NAMESPACES` dict registers the redirects; meta-path finder picks them up for `import gaia.<old>.<sub>` style imports
- `tests/baseline/test_l2_tombstones.py` enforces the registry contract

This spec reuses that machinery for new tombstones.

## 3. First-Principles Criteria

A module organization is judged by how much it lowers three costs:

- **Cognitive cost** — how much effort to find the right file
- **Coupling cost** — how many files change together for one feature
- **Boundary cost** — cross-module import / cyclic risk / dependency direction

Four objective tests:

1. **Cohesion** — files that change together must live together
2. **Dependency direction** — imports form an acyclic, single-direction graph
3. **API surface** — short, stable public import paths
4. **Evolution pressure** — where does the next thing naturally go

This spec applies these criteria to each diagnosed issue.

## 4. Diagnosis

### 4.1 Bayes nested under `lang/` violates evolution pressure (criterion 4)

PR #606 + #609 established `BayesInference(Reasoning)` as a first-class runtime category (a sibling of `Directed`/`Relation`/`Decompose`/`Compose`). When future extensions land — e.g., causal (the speculative `CausalEdge` from `2026-05-15-causal-cleanup-reasoning-shapes.md` §6), or statistics — they should follow the same precedent. With the current layout that precedent says: nest under `engine.lang/`. That makes `engine.lang/` a perpetual junk drawer of "everything authoring-related" and implicitly contradicts the BayesInference decision (which carved Bayes out as runtime-first-class).

The fix: promote `bayes/` to be a peer module under `engine/`. This sets a clean precedent — new reasoning families land as `engine.<family>/`, not `engine.lang.<family>/`.

### 4.2 `engine.logic/` has no own abstraction; it is an IR consumer (criterion 1, 2)

By the cohesion + dependency-direction criterion, top-level engine peers are characterized by owning their own data model:

| Top-level peer | Own abstractions | Files |
|---|---|---|
| `engine.bp/` | `FactorGraph` / `Potential` / `JunctionTree` / `MeanFieldEngine` | 10 |
| `engine.inquiry/` | `ProofState` / goal-tree / `ReviewTarget` / `Anchor` / `Snapshot` | 13 |
| `engine.lang/` | `Knowledge` / `Reasoning` / `Scaffold` / formula AST | 50+ |
| `engine.ir/` | (the data hub itself) | 12 |
| `engine.trace/` | trace records / ranking / hashing | 9 |
| `engine.logic/` | **none** — pure sympy-on-IR adapter | 1 |

`engine.logic/` is the outlier. Its public functions all have signature `(graph: LocalCanonicalGraph, knowledge_id: str) → sympy.Expr`. It defines no Gaia data classes, persists nothing, and consumes IR exclusively. Structurally it is the same kind of module as `engine.ir.coarsen`, `engine.ir.linearize`, `engine.ir.validator` — IR analysis utilities — except it uses an external solver (sympy) as backend.

The fix: demote `engine.logic/` to `engine.ir.logic/` (sub-package). The IR-consumer relationship becomes explicit; future solver backends (Z3, CVC5, ATP) join the same sub-package. If logic ever grows substantial own abstractions (e.g., a unified `Theory` data model spanning solvers, with caching and proof certificates), it can be promoted back to a top-level peer at that point. YAGNI says don't anticipate.

### 4.3 `engine.lang.types/` is single-file over-structure (criterion 1)

Contents: `primitives.py` exporting `Bool`, `Nat`, `Real`, `Probability`, `PrimitiveType`. These are formula-domain primitive types — used by `lang.formula.term.Variable.domain`, by `lang.formula.predicate` for term type checking, and by `Claim.formula` payloads. They have no second contributor in the package and no theoretical reason to sit in their own namespace.

The fix: merge into `lang.formula/primitives.py`.

### 4.4 `lang.dsl/` vs `bayes.verbs/` naming inconsistency (criterion 3)

Both directories serve the same role: public verb entry. The current names diverge because `lang.dsl/` has historically held more than verbs (formula factories, sugar, legacy strategies) while `bayes.verbs/` has only `model.py` and `likelihood.py`. After Bayes promotes to peer, the asymmetry becomes visible in import paths:

```python
from gaia.engine.lang.dsl import derive
from gaia.engine.bayes.verbs import model       # ← inconsistent
```

The fix: rename `bayes.verbs/` → `bayes.dsl/`. Future Bayes-side sugar/factories land in `bayes.dsl/sugar.py` etc., matching the lang convention.

### 4.5 What is NOT diagnosed as a problem

- **`lang.runtime/`, `lang.dsl/`, `lang.compiler/` placement under `lang/`**: these form a tight cohesion triangle. Adding any new core reasoning verb requires touching all three. They must stay together. Promoting them to engine top-level breaks the triangle and increases coupling cost.

- **`lang/` name as host module**: code-fact analysis shows `bayes` single-direction depends on `lang.runtime` (for `Reasoning` base class), `lang.compiler` (for compile-time helpers), and `lang.formula`/`refs`/`review` (shared services). `lang` is not a peer to `bayes`; it is the host that `bayes` plugs into. Renaming `lang` to `core` would imply a peer relation that doesn't match the actual import graph. Keep the `lang` name; document the host/extension boundary.

- **`compiler` co-location**: `lang.compiler/` and `bayes.compiler/` (post-promotion) stay separate per current code; they are cohesive within their own authoring layers and do not benefit from forced unification.

## 5. Logic Layer Architecture

The `engine.logic` demotion in §4.2 motivates an explicit articulation of how logical analysis is split across module boundaries. Three scopes coexist; they are not redundant.

### 5.1 Three scopes of logical structure

| Scope | What it is | Where the structure lives | Where the analysis goes |
|---|---|---|---|
| **A. Within-claim** | one-claim predicate logic: quantifiers, predicates, terms, arithmetic (`Forall(x, Greater(f(x), 0))` inside a single `Claim.formula`) | `lang.formula` AST + IR `formula_atom` metadata after lowering | (none today) — `engine.ir.logic.predicate` (future Z3-backed) |
| **B. Between-claim** | propositional connectives linking claims (`claim_a ∧ claim_b → helper`), produced by IR Operator nodes | IR `LocalCanonicalGraph.operators` | `engine.ir.logic.propositional` (current sympy backend) |
| **C. Cross-cutting** | analysis spanning A + B (e.g., `Forall(x, P(x))` claim contradicts `Lnot(P(b))` claim — needs both formula metadata and Operator graph) | both | (none today) — `engine.ir.logic.predicate` or `engine.ir.logic.smt` (future) |

### 5.2 What the IR preserves vs collapses

When `lang.compiler.lower_formula` lowers a `Claim` with `formula = Forall(x in Real, Greater(f(x), 0))`:

- top-level connectives (`Land/Lor/Lnot/Implies/Iff` at the formula root) → lowered to IR `Operator` nodes between knowledge nodes (B-scope structure)
- top-level quantifiers / predicates / arithmetic (`Forall/Exists/Equals/Greater/UserPredicate` at the root) → preserved as JSON metadata on the Knowledge node (`metadata["formula_atom"]`, `metadata["formula_bindings"]`); the Knowledge becomes opaque from the Operator graph's perspective (A-scope structure preserved but not active)

The IR therefore contains **all the information needed for A and C scope analysis** — the metadata is complete. What is missing is the **active analyzer** that reads `formula_atom` metadata and feeds it to a first-order / SMT solver.

The current `engine.logic.propositional` only walks `graph.operators` and ignores metadata. It covers scope B exhaustively and scope A/C not at all.

### 5.3 Why all three scopes belong in `engine.ir.logic/`

Scope A might naively appear to belong with `lang.formula/` (since `Forall/Equals/...` are formula AST nodes). But the analyzer's input is **not** the AST — by the time analysis runs, the formulas have been lowered to IR with metadata. The analyzer takes IR + metadata, not raw AST. Putting it in `lang.formula/` would force `lang.formula/` to depend on IR (wrong direction) and on Z3 (heavy dep on a data layer).

Scope C inherently combines IR Operator graph with claim-internal metadata; it has nowhere to live except IR-level.

Therefore: all three logic scopes' analyzers belong under `engine.ir.logic/` as additional backends. The current sympy `propositional.py` is the first; future FOL/SMT backends are siblings.

### 5.4 What `lang.formula/` retains

Pure AST utilities, not "logic analysis":

- `is_formula(x)` (type check)
- atom collection (walk `ClaimAtom` nodes)
- variable binding extraction (used during lowering)
- well-formedness checks (`_check_term`, decompose validation)

These are syntactic helpers tied to AST structure. They do not need solvers; they live close to their callers (`lang.formula.predicate`, `lang.dsl.decompose`, `lang.compiler.lower_formula`).

## 6. Host vs Extension Framing

After PR b lands, `engine.lang/` and `engine.bayes/` are **not symmetric peers**. The dependency graph is:

```
bayes.runtime ─→ lang.runtime          (BayesInference inherits Reasoning)
bayes.compiler ─→ lang.compiler         (compile-time helpers)
bayes.runtime / verbs ─→ lang.formula   (predicate logic AST shared)
bayes.* ─→ lang.refs / lang.review      (shared services)
bayes.* ─→ engine.ir, engine.bp         (downstream)
lang.* ↛ bayes.*                        (zero reverse imports)
```

`lang/` is the **host**: it defines the base `Reasoning` hierarchy, the formula AST, and shared services (refs, review). `bayes/` is an **extension**: it adds new `Reasoning` subclasses, new verbs, and a Bayes-specific compile path that all plug into the host.

This framing answers two recurring naming questions:

1. *"Should `lang/` be renamed `core/` for symmetry with `bayes/`?"* — No. `core/peer-bayes/peer-causal/...` would imply a flat peer hierarchy, but the import graph is hub-and-spoke. The `lang` name preserves "this is the language host module"; `bayes` (and future causal/statistics) extend it.

2. *"Why does `bayes.runtime` mirror `lang.runtime` while `lang.runtime` does not have a `bayes/` subdirectory?"* — Because each extension owns its own Reasoning subclasses and verbs but reuses the host's base hierarchy. The mirror is structural, not hierarchical.

Future extensions follow this contract:

> Any new reasoning family that introduces its own runtime classes (e.g., `CausalEdge` per `2026-05-15-causal-cleanup-reasoning-shapes.md` §6) lands as a peer module under `gaia.engine.<family>/`, not under `gaia.engine.lang.<family>/`. The peer module follows the same internal layout as `gaia.engine.bayes/`: at minimum `runtime/` + `dsl/`; optionally `compiler/`, `distributions/`, `adapters/` as needed. The peer extension may freely import from `gaia.engine.lang.*` (host) and `gaia.engine.ir/` / `engine.bp/` (downstream); the host must not import from any extension.

## 7. Target State

After both PRs land:

```
gaia/engine/
├── _stale_check.py
├── packaging.py
├── lang/                          # host: core authoring + shared services
│   ├── runtime/
│   ├── dsl/
│   ├── compiler/
│   ├── formula/
│   │   ├── connective.py
│   │   ├── predicate.py
│   │   ├── primitives.py          # ← merged from engine.lang.types/
│   │   ├── quantifier.py
│   │   ├── symbols.py
│   │   └── term.py
│   ├── refs/
│   └── review/
├── bayes/                         # peer extension (promoted from engine.lang.bayes)
│   ├── runtime/
│   ├── dsl/                       # ← renamed from verbs/
│   ├── compiler/
│   ├── distributions/
│   ├── adapters/
│   └── README.md
├── ir/
│   ├── coarsen.py / linearize.py / validator.py / formalize.py / ...
│   └── logic/                     # ← demoted from engine.logic/
│       ├── __init__.py
│       └── propositional.py       # current sympy backend; siblings (predicate/smt/...) added later
├── bp/
├── inquiry/
└── trace/
```

**Disappearing:** `engine.lang.types/`, `engine.logic/`, `engine.lang.bayes/`.
**Appearing:** `engine.bayes/`, `engine.ir.logic/`.
**Renamed inside `bayes/`:** `verbs/` → `dsl/`.
**Untouched:** `lang.runtime/`, `lang.dsl/`, `lang.compiler/`, `lang.refs/`, `lang.review/`, `ir/*` other than the new `logic/` subdir, `bp/`, `inquiry/`, `trace/`, `_stale_check.py`, `packaging.py`.

## 8. Migration Plan

Two sequenced PRs to minimize blast radius and let reviewers focus on one structural argument at a time.

### 8.1 PR a — Single-file consolidation + logic demotion

**Scope:** Two file moves, two new tombstones, three deleted shells, no semantic changes.

| From | To |
|---|---|
| `gaia/engine/lang/types/primitives.py` | `gaia/engine/lang/formula/primitives.py` |
| `gaia/engine/logic/propositional.py` | `gaia/engine/ir/logic/propositional.py` |

Tombstones added to `TOMBSTONED_NAMESPACES`:

```python
"gaia.engine.lang.types": "gaia.engine.lang.formula",
"gaia.engine.logic": "gaia.engine.ir.logic",
```

Existing entry updated:

```python
# old: "gaia.logic": "gaia.engine.logic"
"gaia.logic": "gaia.engine.ir.logic",
```

Deleted (after tombstones install):

- `gaia/engine/lang/types/__init__.py` (and the directory if no other contents)
- `gaia/engine/logic/__init__.py` (and the directory)

`gaia/engine/lang/__init__.py`: continue re-exporting `Bool, Nat, Real, Probability, PrimitiveType` so user-facing import `from gaia.engine.lang import Bool` keeps working unchanged.

Update `gaia/engine/ir/logic/__init__.py` (new file) with explicit scope notes per §5:

```python
"""Logic backends for compiled Gaia IR.

Provides solver-backed analysis of the IR's logical structure. Backends use
external libraries (sympy, future Z3/CVC5) while keeping `gaia.engine.ir`
data classes free of solver dependencies.

Current scope:
    propositional — sympy-based analysis of claim-level Operator graphs
        (NEGATION/CONJUNCTION/DISJUNCTION/IMPLICATION/EQUIVALENCE/
        CONTRADICTION/COMPLEMENT). Treats Knowledge nodes as atoms; does
        not look inside Claim.formula metadata.

Future (out of scope for this PR; tracked separately):
    predicate — first-order / SMT backends consuming `formula_atom` metadata
        for claim-internal predicate / quantifier / arithmetic analysis.
    smt — cross-cutting analysis combining Operator graph with claim-internal
        formula metadata.

See docs/specs/2026-05-16-engine-module-reorg-design.md §5 for the three-scope
taxonomy.
"""
```

Estimated diff: ~120 lines (file moves + tombstone updates + new `__init__.py` + path rewrites in tests / examples / docs that use the old paths).

### 8.2 PR b — Bayes promotion + verbs/dsl rename

**Scope:** One subtree move, one rename, one tombstone, repo-wide import path updates.

| From | To |
|---|---|
| `gaia/engine/lang/bayes/` (entire tree) | `gaia/engine/bayes/` |
| `gaia/engine/bayes/verbs/*` (post-move) | `gaia/engine/bayes/dsl/*` |

Tombstone added:

```python
"gaia.engine.lang.bayes": "gaia.engine.bayes",
```

Repo-wide import rewrites:

- `from gaia.engine.lang.bayes import ...` → `from gaia.engine.bayes import ...`
- `from gaia.engine.lang.bayes.runtime import ...` → `from gaia.engine.bayes.runtime import ...`
- `from gaia.engine.lang.bayes.verbs import ...` → `from gaia.engine.bayes.dsl import ...`
- internal cross-imports in `bayes/*` updated similarly

Doc updates (see §11).

Estimated diff: ~350-450 lines (mostly mechanical import path updates + tombstone install + docs sync).

### 8.3 Sequencing rationale

PR a first because it is contained, has minimal blast radius, and resolves unambiguous over-structure with no naming debate. Reviewers focus on the demotion argument (criterion 4.2) without being distracted by the Bayes promotion.

PR b second because it depends on the BayesInference decision being settled (which happened in PR #606+#609) and has wider repo-touch. With PR a already merged, PR b's change set is purely the bayes-related moves.

## 9. Tombstone Strategy

Reuse the existing `gaia/_legacy_imports.py` machinery:

- `TOMBSTONED_NAMESPACES` registers each old → new redirect
- `_TombstonedSubmoduleFinder` (already installed at module load time) intercepts `import gaia.<old>.<sub>` style imports
- `_tombstoned_namespace_getattr` handles `from gaia.<old> import X` style imports

Each tombstone raises a clean `ImportError` (alpha-0 strict policy — not a deprecation warning):

```
gaia.engine.logic.propositional has moved to gaia.engine.ir.logic.propositional;
this path was never public API and is removed in alpha 0. Update imports to
`gaia.engine.ir.logic.propositional`.
```

The `tests/baseline/test_l2_tombstones.py` enforces that every entry in `TOMBSTONED_NAMESPACES` actually raises an `ImportError` with the right redirect.

For PR a, two new entries added and one updated (see §8.1). For PR b, one new entry added.

The `verbs/ → dsl/` rename inside `bayes/` does not need a separate tombstone because `engine.lang.bayes.verbs` only ever existed as an internal sub-package; the public API was always `engine.lang.bayes.<verb>` re-exported. Test that public verbs (`from gaia.engine.bayes import model, likelihood`) still resolve; internal `bayes.dsl/__init__.py` re-exports the same names.

## 10. Test Plan

### PR a tests

Smoke imports (must pass):

```python
from gaia.engine.lang import Bool, Nat, Real, Probability, PrimitiveType    # public API unchanged
from gaia.engine.lang.formula.primitives import Bool                          # new direct path
from gaia.engine.ir.logic.propositional import is_satisfiable, are_equivalent # new direct path
```

Tombstone redirects (must raise ImportError):

```python
import pytest

with pytest.raises(ImportError, match="moved to gaia.engine.lang.formula"):
    from gaia.engine.lang.types.primitives import Bool

with pytest.raises(ImportError, match="moved to gaia.engine.ir.logic"):
    from gaia.engine.logic.propositional import is_satisfiable

with pytest.raises(ImportError, match="moved to gaia.engine.ir.logic"):
    import gaia.engine.logic.propositional
```

Existing test suites must continue to pass without changes:

- `tests/baseline/test_l2_tombstones.py` (extended automatically when `TOMBSTONED_NAMESPACES` is updated)
- `tests/gaia/lang/formula/test_predicate.py`
- any test that exercises propositional analysis on compiled packages

### PR b tests

Smoke imports:

```python
from gaia.engine.bayes import model, likelihood                       # new public path
from gaia.engine.bayes.runtime import BayesInference, PredictiveModel, Likelihood
from gaia.engine.bayes.dsl import model                               # renamed verbs → dsl
from gaia.engine.lang.runtime.action import Reasoning
from gaia.engine.bayes.runtime.actions import BayesInference

assert issubclass(BayesInference, Reasoning)                           # cross-module subclass
```

Tombstone redirect:

```python
with pytest.raises(ImportError, match="moved to gaia.engine.bayes"):
    from gaia.engine.lang.bayes import model
```

Existing test suites must pass without semantic regressions:

- `tests/gaia/lang/bayes/*` — Bayes runtime + verbs + lowering tests (paths updated as part of PR b)
- `tests/gaia/lang/test_action_hierarchy.py::test_bayes_action_shapes_follow_reasoning_taxonomy` — verifies `BayesInference / PredictiveModel / Likelihood` subclass relations across module boundaries

### Cross-PR test

IR hash stability: compile a sample Gaia package (e.g., one of the existing `*-gaia` examples) before each PR and after; the resulting `.gaia/ir.json` and `.gaia/ir_hash` must be byte-identical. Module path changes must not perturb compiled IR.

## 11. Doc Updates

PR a:

- update `docs/foundations/gaia-lang/predicate-logic.md` — fix any direct references to `gaia.engine.lang.types` import paths
- update `docs/foundations/gaia-lang/knowledge-and-reasoning.md` — fix any references to `engine.logic.propositional`
- new `gaia/engine/ir/logic/__init__.py` docstring per §8.1

PR b:

- update `docs/specs/2026-05-15-causal-cleanup-reasoning-shapes.md` §4.2 — replace `gaia.engine.lang.bayes.runtime` references with `gaia.engine.bayes.runtime`; add a host/extension paragraph per §6 of this spec
- update `docs/foundations/gaia-lang/bayes.md` — update import examples
- update `docs/foundations/gaia-lang/knowledge-and-reasoning.md` §6 (Bayes Module) — update path references
- update `docs/for-users/language-reference.md` import-block example — update Bayes import
- update `README.md` — update any Bayes-related import snippets
- move `gaia/engine/lang/bayes/README.md` → `gaia/engine/bayes/README.md`; update its import examples

Both PRs:

- a paragraph in `docs/foundations/gaia-lang/package.md` (or a new `engine-architecture.md`) framing host vs extension per §6 of this spec, so future contributors reading the layout know why `lang/` and `bayes/` are not peers despite sitting at the same nesting depth

## 12. Validation

For each PR:

```bash
git diff --check
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest tests/ --no-cov
uv run --extra dev pytest tests/baseline/test_l2_tombstones.py -v
uv run --extra docs mkdocs build --strict
```

Smoke compile on a known package:

```bash
gaia compile <some-existing-package>
gaia build check <some-existing-package>
diff <package>/.gaia/ir.json <reference-ir.json>
```

## 13. Future Work

Tracked separately, not part of this spec:

- **First-order / SMT logic backends** — implement `engine.ir.logic.predicate` (Z3-backed) consuming `formula_atom` metadata for scope A and C analysis (§5.1). Promote `engine.ir.logic/` to top-level `engine.logic/` only if a unified `Theory` data model emerges (Gaia-native abstractions over multiple solvers).

- **Causal extension module** — when the `CausalEdge` GaiaGraph record from `2026-05-15-causal-cleanup-reasoning-shapes.md` §6 is implemented, land it as `gaia.engine.causal/` per the precedent in §6 of this spec.

- **Compose review consolidation** — `engine.lang.review/` (manifest gen), `engine.inquiry/` (consume manifest), `engine.trace/review.py` (post-execution review) all carry "review" but operate at different lifecycle stages. Worth a separate spec to clarify whether these should consolidate, rename, or stay split.

- **`Action` alias retirement** — track in `2026-05-15-reasoning-claim-reference-boundary.md` §9 deferred work. Independent of this reorg.

## 14. Out of Scope (Explicit)

Items considered and deliberately rejected for this spec:

- **Full hierarchy flattening** (promoting `lang.runtime` / `lang.dsl` / `lang.compiler` to engine top-level): rejected per §4.5. Cohesion triangle is real; flattening breaks it.

- **Renaming `lang/` → `core/`**: rejected per §4.5 + §6. Code-fact dependency direction is host/extension, not peer.

- **Splitting `lang.dsl/` into `verbs/`, `factories/`, `legacy/`**: orthogonal nesting, no current consumer. YAGNI.

- **Promoting Bayes out of `engine/`** (e.g., to top-level `gaia.bayes/`): out of scope for v0.5; alpha-0 layout already commits engine code under `gaia.engine/` and Bayes is engine code.

- **Adding `engine.causal/` / `engine.statistics/` as part of this PR**: the spec sets the precedent (§6) but does not implement extensions that don't yet exist. They land as separate PRs when the feature work is ready.

- **Removing tombstones**: post-deprecation cleanup is independent of this reorg. Tombstones are alpha-0 hard-error redirects, not soft deprecation; they stay in place indefinitely as long as `gaia.<old>` paths could plausibly appear in user code.
