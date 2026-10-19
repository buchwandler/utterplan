# SSMDDoc workspace support

UtterPlan can compile an editable `.ssmdoc` workspace as one SSMD 0.9 document. This is a workspace input convenience around the existing one-document compiler; it is not a book format and does not create chapter plans.

## Workspace contract

A workspace is identified by a `manifest.json` whose `format` is `ssmdconvert.document` and whose `schema_version` is `1`. UtterPlan supports the v1 contract and expects the canonical document entry to identify `document-0001` at the normalized relative path `document.ssmd.md`. The source is SSMD 0.9.

The current `document.ssmd.md` is authoritative. Its manifest digest and character count are metadata, not a lock: if you edit the document and its recorded digest becomes stale, UtterPlan compiles the current file. It never rewrites the manifest, refreshes hashes, or edits source content. Semantic plans and reports are written directly under the workspace's visible `utterplan/` directory; profile-specific RenderPlans are written directly under `renderplan/`. These are derived artifacts, not manifest members.

Discovery and path handling are deliberately strict. The manifest must be valid UTF-8 JSON within the 2 MiB limit, and the document is limited to 64 MiB. UtterPlan checks the canonical path and workspace containment, rejects unsupported manifest versions and unsafe paths, and does not follow a document path outside the workspace. It reads no source-media files. `ssmdconvert` is not a runtime dependency: UtterPlan consumes the published file-format contract directly.

ZIP bundles are not supported by this workflow; use an editable directory workspace.

## Compile a workspace

Run `compile-document` with the workspace directory (the suffix need not be `.ssmdoc` if the manifest identifies it):

```bash
utterplan compile-document story.ssmdoc
```

It writes one plan and one operational report by default:

```text
story.ssmdoc/utterplan/
├── document.utterplan.toml
└── compile-report.toml
```

The report describes the single compilation and is not a FlowPlan. You can override the destination and report path:

```bash
utterplan compile-document story.ssmdoc \
  --output-dir build/story-plan \
  --report build/story-report.toml \
  --language en-US \
  --spacy off
```

Options are `--output-dir`, `--report`, `--language`/`--lang`, `--text-preparation`, `--renderability`, `--spacy`, `--diagnostics`, and `--force`. SSMD header language remains authoritative; pass `--language` as a fallback when the document has no language. Existing plan outputs are protected unless `--force` is supplied. The report may not collide with the plan, manifest, or source document. `compile-document` is a single-workspace command, so it has no chapter selector or `--fail-fast` option.

The existing `compile` and `validate` commands also accept the workspace root or its canonical `document.ssmd.md` file as input. `compile` keeps its normal stdout/`-o` behavior; use `compile-document` when you want the workspace-oriented default output directory and report. `validate` compiles the source for validation without writing a plan.

## Python API

Use `compile_ssmdoc()` for file-backed workspace compilation. The existing `compile_document()` remains the in-memory text API:

```python
from utterplan import compile_ssmdoc

result = compile_ssmdoc("story.ssmdoc", language="en-US")
if result.failed:
    raise RuntimeError(f"workspace compilation failed; see {result.report_path}")
print(result.plan_path)
```

The result provides the workspace and source paths, output and report paths, and the one-item batch outcome. Options include `output_dir`, `report`, `language`, `planner_config`, `force`, `diagnostics`, and progress/start callbacks. The default artifacts match the CLI: `utterplan/document.utterplan.toml` and `utterplan/compile-report.toml`.

## SSMDDoc is not SSMDBook

An SSMDDoc contains one editable document and produces one canonical FlowPlan. An SSMDBook manifest discovers multiple independent chapter documents; `compile-book` writes one plan per selected chapter and never builds a book-level combined plan. Use [SSMDBook workflows](ssmdbook.md) for book compilation and RenderPlan projection.

Neither workspace workflow changes its source manifest or source documents. UtterPlan stops at semantic FlowPlans; engine selection, G2P, synthesis, and audio remain downstream.

## Projecting a document RenderPlan

After `utterplan compile-document .`, project the existing canonical FlowPlan without recompiling it:

```bash
utterplan render-document . --profile narration.renderprofile.toml
```

This writes `renderplan/<label>--<profile-fingerprint>/renderprofile.toml`, `document.renderplan.toml`, and `render-report.toml` directly under the workspace. The printed exact variant can be passed to `voicerender render-document`. A document is never wrapped in a one-chapter book or a RenderPlanSet. Re-run `compile-document` and this projection after source edits; VoiceRender intentionally renders only the selected explicit RenderPlan.

### Logical roles and profile coverage

A source-level `voice` name such as `narrator`, `host`, or `guest` is a **logical role**; it does not name an engine voice. The selected RenderProfile's **role binding** supplies the concrete renderer configuration. Treat one RenderProfile as the complete cast for a rendering variant, including its default role and shared planning/pause policy. UtterPlan accepts exactly one profile for this projection; it does not accept one profile per role or discover engines.

Use `utterplan inspect <plan> --roles` to see explicit speech-role counts and whether unqualified speech needs the selected profile's default. `render-document` reports required roles and complete coverage, and rejects any missing roles before creating a new variant directory. The same multi-role RenderProfile format and example are documented in the [README](https://github.com/buchwandler/utterplan/blob/main/README.md#logical-roles-and-complete-renderprofiles).
