---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0003
release_version: 0.2.0
kind: fixed
summary:
  Fixed runnable examples with command-line arguments, path-safe outputs, and
  a dedicated SSMD example script
status: accepted
audience: null
scopes: []
source_refs:
  - git:e49a6ddc97c789574098a635fc823da885b48439
paths:
  - .gitignore
  - examples/basic.py
  - examples/chapter.ssmd
  - examples/compile_file.py
  - examples/inspect_plan.py
  - examples/multilingual.py
  - examples/ssmd.py
  - examples/ssmd_example.py
issues: []
prs: []
sources:
  - git:e49a6ddc97c789574098a635fc823da885b48439
contributors:
  - "@holgern"
breaking: false
internal: false
order: 3
---

Example scripts expose main() entry points with argparse interfaces, resolve default paths next to the script instead of the current working directory, and write generated plans beside the source. examples/ssmd.py is replaced by examples/ssmd_example.py, examples/chapter.ssmd provides sample SSMD input, and generated examples/\*.utterplan.json outputs are excluded from git.
