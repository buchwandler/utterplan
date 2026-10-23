# Manifest-driven SSMD bundles

UtterPlan's bundle lifecycle accepts one canonical `<name>.ssmd-bundle/` root and dispatches from its `manifest.json`. Both compilation and projection use this entry point:

```bash
utterplan bundle compile novel.ssmd-bundle --chapters 5-17
utterplan bundle compile story.ssmd-bundle
utterplan bundle render novel.ssmd-bundle --chapters 5-17 --profile narration.renderprofile.toml
utterplan bundle render story.ssmd-bundle --profile narration.renderprofile.toml
```

The manifest format determines whether the bundle contains independently planned book items or one document item. A chapter directory, document source file, or arbitrary directory is not an alternate root. UtterPlan reads manifests and source documents but does not modify them.

## Manifest kinds

Both supported manifests use `schema_version: 1` and `ssmd_version: "0.9"`.

A book manifest declares `format: "ssmdconvert.book"` and a `chapters` array. Every chapter has a unique `id`, positive `source_number`, `title`, and normalized relative POSIX `path`; optional hashes are informational and do not override the current source content. Chapter paths are resolved within the bundle root.

A document manifest declares `format: "ssmdconvert.document"` and one `document` object containing an `id`, relative `path`, and document metadata. Its current source is compiled as one FlowPlan. The bundle's name does not select its kind: `manifest.json` is authoritative.

## Compile

```bash
utterplan bundle compile novel.ssmd-bundle --chapters 5-17
utterplan bundle compile story.ssmd-bundle --text-preparation identity
```

When already inside a bundle root, `.` is also accepted because the supplied path is resolved before the directory name is validated:

```bash
cd story.ssmd-bundle
utterplan bundle compile --lang en .
```

Compilation defaults to all items. For book bundles, `--chapters` selects manifest `source_number` values: one number, an inclusive range, or comma-separated combinations such as `1,3-5,9`. Selected items retain manifest order. A document bundle accepts only `--chapters all`.

By default, one schema-v7 `.utterplan.toml` plan per selected item and `compile-report.toml` are written under `<bundle>/utterplan/`. `--output-dir` and `--report` override those destinations. Existing plans are protected unless `--force` is supplied; `--fail-fast` records later selected items as skipped after a failure. `--language` is a fallback for SSMD language metadata. Bundle sources are SSMD 0.9, so the command does not accept an input-format override. The report is operational metadata and does not affect plan identity.

### Bundle-level logical role inventory

A successful complete bundle compile writes `utterplan/role-inventory.toml` under the selected UtterPlan output directory (by default, `<bundle>/utterplan/`). For example:

```bash
ssmdconvert bundle convert story.ssmd.md
utterplan bundle compile story.ssmd-bundle
```

The bundle contains the source and compiled document plan alongside the derived inventory:

```text
story.ssmd-bundle/
├── document.ssmd.md
├── manifest.json
└── utterplan/
    ├── document.utterplan.toml
    └── role-inventory.toml
```

The TOML contract uses `format = "utterplan.bundle-role-inventory"` and `version = 1`. It records `bundle_kind`, a SHA-256 of the exact manifest bytes, aggregate `[[roles]]` with speech-segment occurrence counts, bundle-order `[[items]]`, and each item's source and plan paths, actual source-byte SHA-256, canonical `plan_id`, explicit role order/counts, and implicit/default-role count. Paths are bundle-relative POSIX paths, not absolute machine paths. Inventory bytes are deterministic and the file is replaced atomically.

Roles and counts derive from compiled FlowPlan speech segments through UtterPlan's logical role semantics, not by scanning SSMD markup or inspecting RenderPlans. Aggregate role order is first semantic occurrence across items in manifest order; item role order is first occurrence within that plan. Empty and audio-only segments do not count. Speech without an explicit role sets `uses_default_role = true` and increments `implicit_occurrences`; it is not assigned an invented role name. A profile-aware consumer resolves the concrete default role later.

Freshness is content-based: `manifest_sha256` hashes the current `manifest.json` bytes, each `source_sha256` hashes its current source bytes, and each item stores the compiled plan's `plan_id`. Modification times are not used. A subset book compile never replaces the canonical whole-bundle inventory and returns no inventory path. A failed full compile also leaves any previous inventory untouched. The successful full-compile summary reports explicit roles, whether a default role is required, and the inventory path; partial compiles do not claim a whole-bundle inventory was produced.

## Render

Compilation and rendering are separate operations. Rendering reads saved plans and requires an explicit RenderProfile:

```bash
utterplan bundle render novel.ssmd-bundle \
  --chapters 5-17 \
  --profile narration.renderprofile.toml
```

The default RenderPlan root is `<bundle>/renderplan/`. Each variant includes a canonical `renderprofile.toml` snapshot, RenderPlan artifacts, and `render-report.toml`; book variants also maintain `renderplan-set.toml` as the active collection index. The variant directory combines a readable label with the RenderProfile identity fingerprint. `--variant` changes the label without removing the fingerprint. `--utterplan-dir`, `--output-root`, and `--report` override their respective locations.

Role coverage is checked before new variant artifacts are written. The selected profile must cover every required logical role, including its default role when any speech has no explicit role. Profile identity mismatches, unsafe paths, and metadata collisions are not bypassed by `--force`.

## Replan

When VoiceRender reports `preflight.replan`, refine the active plan using its exact matching feedback:

```bash
utterplan bundle replan novel.ssmd-bundle \
  --variant narration--28f616b6fe3b \
  --chapters 5
```

The full variant directory name, including its profile fingerprint, is required. Replanning reads the stored profile snapshot and active plan references, validates preflight feedback against the active RenderPlan, writes deterministic child plans, and updates only selected active references. It refuses stale parent feedback; run VoiceRender again on the newly active plan before another refinement. `--dry-run` validates and reports planned changes without writing child RenderPlans or changing active references. The single-file `render-plan --previous ... --preflight ...` interface remains available for low-level projection and refinement.

## Safe and read-only behavior

The supplied workspace path is resolved first. The resolved directory must be named `<name>.ssmd-bundle` and contain a regular, non-symlink `manifest.json`. Therefore `.` and equivalent aliases are valid when they resolve to the bundle root; paths to `chapters/` or an item file remain invalid. Manifest item paths must be normalized relative POSIX paths, remain inside the resolved root, and resolve to regular files. Symlink escapes and unsafe output collisions are rejected. Manifest size and document size are bounded. Source digests are not used to replace current edited content; the manifest and source files are never refreshed or rewritten.

## Python API

The public services share the manifest dispatch and selection behavior used by the CLI:

```python
from utterplan import compile_bundle, replan_bundle, render_bundle

compiled = compile_bundle("novel.ssmd-bundle", chapters="5-17")
projected = render_bundle(
    "novel.ssmd-bundle",
    profile="narration.renderprofile.toml",
    chapters="5-17",
)

assert compiled.kind == projected.kind == "book"
assert compiled.exit_code == projected.exit_code == 0
print(projected.variant)
```

`compile_bundle()`, `render_bundle()`, and `replan_bundle()` accept paths and keyword options. Their result records expose the resolved bundle, kind, selection, per-item outcomes, artifact paths, reports, and exit status. Optional progress and start callbacks receive typed records; services do not print. Invalid or unsafe requests raise `BundleServiceError` or `BundleReplanError`, while item-level failures are returned in result outcomes.

For a successful full bundle compile, `BundleCompileResult.role_inventory_path` is the canonical `role-inventory.toml` path. It is `None` for partial selections and any compile with a failed item; in those cases the prior whole-bundle inventory, if present, remains untouched. The artifact is additive and does not alter plan identity or bundle rendering.
