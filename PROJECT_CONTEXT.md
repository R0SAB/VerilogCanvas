# VerilogCanvas — project context

Updated: 2026-10-05. Baseline: Qt 1.2.2 on `main`.

This is a development handoff distilled from the original project conversation.
Read it together with README.md, current source, tests and subsequent commits.
It records design intent and historical validation, not a guarantee that every
edge case is covered. Update it when behavior or architectural decisions change.

## Purpose and current state

VerilogCanvas is a Windows desktop schematic editor that generates a Verilog or
SystemVerilog top-level module. It supports module instances, parameters, wires,
top-level ports, named nets, transforms, inline HDL and documentation groups.

The user has used generated HDL in a real project: compilation, programming the
hardware and operation succeeded. The current Qt version was reported to work
well enough for practical use. GitHub was introduced to preserve this baseline
and future changes.

The original editor used Tkinter (last historical baseline: 0.31). It became slow
on the user's larger schematic. A Qt performance prototype was tested, then the
full editing workflow was ported to PySide6. The repository contains the Qt
edition; do not reintroduce a dependency on the old Tkinter UI.

## Working preferences

- Discuss work with the user in Russian. Program UI and repository-facing
  documentation are English; Russian UI/localization is not required.
- Preserve established appearance and interaction semantics while making changes.
- Backward compatibility with previous versions is not required unless the user
  explicitly asks. Do not add compatibility layers or old-version tests by default.
- Preserve user schematic files; use copies for experiments.
- Fix reported scenarios with focused model/GUI regression checks where useful.
- Distinguish automated/offscreen validation from actual Windows testing.
- Read current repository state before continuing; an old chat or archive may be
  stale. Missing screenshots or attachments are not evidence of their contents.

## Source map

| File | Responsibility |
| --- | --- |
| `qt_editor.py` | Full application entry point, actions, editing and interactions |
| `qt_app.py` | Retained scene, graphics items, viewport and cached grid; also used by preview tests |
| `qt_dialogs.py` | Native Qt property and source dialogs |
| `model.py` | Document objects, routing, connections, validation and HDL generation |
| `hdl_import.py` | Existing Verilog/SV module interface import |
| `inline_hdl.py` | Inline HDL interface/body processing |
| `schematic_text.py` | Schematic serialization with readable HDL source records |
| `recover_hdl.py` | Emergency extraction of embedded HDL |
| `export_cli.py` | Command-line HDL generation |
| `examples/` | Sample schematics and HDL |
| `tests/` | Model tests and standalone Qt interaction checks |

The model uses document/node/port/wire/label/comment objects. Explicit wire
attachments and vertices carry connectivity; screen-coordinate coincidence alone
is not a replacement for that topology. Straight segments are individual Qt scene
objects, while underlying routes remain represented by wires and vertices.

## Run, build and validate

Python 3.12 or newer is required. The current dependency is
`PySide6==6.11.2` in `requirements_qt.txt`.

- `run_qt_windows.bat` creates/uses `.venv-qt`, installs dependencies and launches
  the editor.
- `build_qt_windows.bat` runs model and Qt checks and invokes PyInstaller.
- Output: `dist\VerilogCanvasQt.exe`.
- The one-file executable bundles Python and Qt and extracts runtime libraries on
  startup; the target machine does not need Python or Qt installed.
- Build the Windows executable on Windows. Historical development validation used
  Linux with Qt's offscreen platform, not a locally tested Windows binary.

From the repository root:

```text
python -m pip install -r requirements_qt.txt
python qt_editor.py
python -m unittest discover -s tests -q
python tests/qt_preview_smoke.py
python tests/qt_grid_smoke.py
python tests/qt_editor_smoke.py
python tests/qt_segments_smoke.py
python tests/qt_junction_markers_smoke.py
python tests/qt_consumed_tips_smoke.py
```

Set `QT_QPA_PLATFORM=offscreen` on headless Linux. The 1.2.2 README records
166 model tests plus these Qt checks. This handoff-only commit does not constitute
a fresh test run. Earlier checks also exercised a supplied 22-block/58-wire
schematic; do not assume that private fixture is present in a new checkout.

## HDL and naming decisions

- Ordinary blocks have module and unique instance names, parameters, left inputs
  and right outputs. Ports default to one bit when no range is supplied.
- Import interfaces from .v/.sv, including ANSI/non-ANSI declarations, parameters,
  signed ports and packed/unpacked dimensions. Ignore output initializers such as
  `output reg out = 0;` when importing an interface.
- Display dimensions compactly and evaluate parameter values for display:
  `[IN_MSB:0]` becomes `[15:0]` when IN_MSB is 15.
- Display parameter values in the block body. Port names are blue and dimensions
  grey.
- Top-level input/output symbols have a fixed appearance and size. Inout is not
  part of the established requirement.
- Generated unnamed nets use names such as `syn_net...`; widths follow the
  connected driver. Buses are drawn thicker than scalar wires.
- An unnamed direct top-level I/O connection uses the top-level port directly.
  An explicit differing net label requests an intermediate named net.
- A label equal to its connected top-level input/output name reuses that port net,
  rather than declaring a duplicate or reporting an already-used name.
- Equal net labels connect physically separate wire pieces electrically.
- Top-level declarations support enums/localparams and other user source.
- Input transforms retain graphical wiring. Example:
  `mode = ($ == MOD_AM) ? 1 : 0`. Substitute the connected signal for `$`;
  MOD_AM can belong to an enum declared in the top-level declarations.
- Inline HDL blocks have orange frames and automatically derived graphical ports
  from their interface declarations. They insert a body without a module wrapper.
- **Inline HDL uses the shared top-level namespace.** Do not restore generated
  name prefixes or private block scopes. Preserve user body identifiers; reuse
  matching existing net names. Interface edits can map removed connected ports
  to replacements.
- Embedded HDL/declarations stay readable as raw text in .vsch for recovery,
  rather than existing only as escaped opaque payloads.

Preferred parameterized instance formatting:

```verilog
data_pipe
#(
    .WIDTH(8)
)
u_pipe
(
    .clk(clk),
    .rst_n(rst_n),
    .data_in(data_in),
    .data_out(data_out)
);
```

## Comments, groups and selection

- Ordinary comments are schematic documentation only and are excluded from HDL.
  Text wraps. Their resize grip appears only when selected.
- Group comments always display a dashed frame above the other schematic objects.
  Captions wrap. Their lower-right resize grip works without first selecting them.
- Spatial containment groups modules, top-level I/O and ordinary comments.
  Moving a member moves the group; Ctrl+drag moves that member independently.
- Resizing a group changes its frame/membership without dragging its contents.
- Moving between selected members in one group leaves the green selection
  indication only on the last selected member.
- Area selection supports moving a collection together.
- Group copy/paste includes internal wiring, labels and comments and assigns
  unique instance, top-level port and label names.
- Deleting a group frame alone does not delete its contents.
- HDL group headings use `// ############ COMMENT #############`.
  Group-local signals are declared before the first instance in that group.
- Module dimensions are adjusted graphically, not with numeric property fields.

## Wire interaction invariants

This is the most regression-sensitive subsystem.

1. Routing is orthogonal and grid-aligned. The committed path should match the
   drawing preview, including manual bends.
2. Draw from a port to another port, an existing wire, or empty space. Free ends
   can be moved; attached dangling wires can be extended.
3. Every straight edge between corners/junctions has its own selectable scene
   object. Drag a horizontal edge vertically or a vertical edge horizontally.
   Only the selected edge is highlighted; do not revert to moving an entire
   collinear run as one segment.
4. An explicit branch connection splits the host at the junction. Merely crossing
   unrelated wires geometrically does not connect them.
5. Junctions follow actual visible divergence. Shared coincident prefixes must
   not become duplicate conductors. Nested branches must retain their connection
   when a shared prefix collapses or is reparented.
6. Moving a port/module or an attached edge preserves a one-cell outward
   horizontal stub where necessary, so a new vertical segment does not hide
   along the module frame.
7. Restore the affected component's drag-start snapshot before applying each
   absolute mouse offset. Incremental mutation caused drift and lag in earlier
   implementations. Undo/redo includes affected branch geometry.
8. A completely detached physical wire component can move as a whole with
   Alt+drag. Ordinary segment dragging retains edge-editing behavior.
9. Deleting a module preserves its wires and labels as loose ends. Placing a port
   on a loose end reconnects after the completed move/edit. Allow erroneous
   connections to be edited/saved; highlight affected ports/ends red with useful
   diagnostics instead of preventing the user from finishing the action.
   Generation still reports blocking errors.
10. Width, signedness and direction diagnostics are not all necessarily fatal:
    respect current validation rules, including stricter conflicts for shared
    inline declarations.
11. Labels can be grabbed by their entire body and dragged while the mouse button
    remains held, even when the cursor is away from the wire.

### Endpoint and junction regressions fixed in 1.2.1–1.2.2

- Joining a second wire to a free end consumes the free-end marker: two incident
  rays show a plain bend/continuation, not a junction dot plus an open circle.
- Three or more incident rays show one dot, including nested attachments at the
  same physical point. Unrelated coincident wires remain separate.
- A consumed endpoint is no longer offered as a free-end drag/extend target.
- Left and right branches attached at a former free end move independently,
  regardless of attachment order.
- The remembered position of that old endpoint must not limit future movement.
  Extend the host when necessary; remove obsolete tails when all arms move away.
- Delete on a selected free terminal edge deletes only that edge, preserving the
  remaining wire, labels and connections. Deleting the only edge deletes the wire.
  This is not a promise of arbitrary internal-edge deletion.
- Marker behavior must match in the viewport and exported PNG and survive
  deletion, repeated movement and undo/redo.

The original six movement examples covered moving either horizontal arm of a T
up/down and moving its vertical branch left/right, including reaching a host
corner. Preserve their regression tests; this is local manual routing, not a
general optimal autorouter.

## Rendering and performance

- Retain QGraphics scene/items during navigation and dragging. Update affected
  geometry; avoid full scene reconstruction or full electrical analysis per frame.
- Rebuild electrical/group indexes at completed edits as appropriate.
- Keep segment item objects alive during a drag so the mouse grab is not lost.
- Grid modes: Dots / Lines / Off, persisted between launches. Snap remains 20 units.
  Cached/tiled background rendering resolved the reported full-screen slowdown.
- The user reported about 60 updates/second across grid modes after optimization;
  this is a report from their setup, not a universal performance guarantee.
- Middle-button panning uses normal cursor/screen bounds. Infinite cursor
  wrapping was tried and explicitly removed.
- Text scales continuously with zoom, without a minimum rendered size.
- Green selection borders differ from group frames and I/O frame colors.
  Draw module borders above headers for a consistent perimeter.
- Net-label backgrounds are transparent to avoid covering adjacent transforms.
- Standard icons should remain legible on a dark theme. Add-element buttons keep
  the intuitive "+" prefix; Fit stays near zoom controls.
- No debug FPS/timing indicator in the full editor.
- Dialogs open centered in the active program area; action buttons stay visible
  independently of scrollable content.

## Save/export workflow

- Separate Save and Save As for .vsch, with the established backup behavior.
- Export writes HDL immediately to the remembered destination and gives a small
  notification. Ask for a destination only when needed; Export As changes it.
- Show the selected output path in the toolbar. Its filename determines the top
  module name and must be a valid HDL identifier.
- Preview HDL is a separate, on-demand action, not an obligatory export step.
- Export PNG covers the entire schematic, not just the viewport, and excludes
  selection/resize indicators. Current resolution limits are documented in README.
- Preserve the export destination through ordinary undo/redo operations.

## GitHub-hosted Windows builds (2026-10-05)

- `.github/workflows/build-windows.yml` builds on Windows Server 2022 x64 with
  Python 3.12. Source/dependency/example/workflow/checkout-attribute changes on
  main trigger it; workflow_dispatch permits manual builds.
- The model suite and all six Qt smoke scripts have passed on the Windows runner.
  The model run reports 166 tests, including 12 skips for unavailable optional
  HDL compiler dependencies. This does not replace interactive user acceptance
  testing of the packaged executable.
- PyInstaller produces the one-file windowed EXE. The workflow uploads
  `VerilogCanvasQt-windows-x64` with the EXE, SHA256SUMS.txt and BUILD_INFO.txt,
  retaining artifacts for 30 days. README explains downloading/manual triggering.
- Actions are pinned by commit; repository permission is contents:read.
  No signing or automatic GitHub Release publication is configured.
- **Keep `*.vsch -text` in .gitattributes.** These files contain byte-counted
  HDL records. Windows Git newline conversion corrupted example records and
  caused a modal load error during the first CI attempt.
- Export path assertions compare resolved Path objects, because textual
  temporary paths and their canonical Windows representation can differ.
- Qt checks are separate steps with two-minute limits so an unexpected modal
  dialog cannot leave the entire build waiting indefinitely.

## Continuation checklist

At this handoff the latest wire fixes were accepted by the user; no additional
specific code change is pending. Project context is preserved here and Windows CI is now configured.

For the next task: read this file and README, inspect current source/commits,
reproduce the new report on an example or a copy of the user's schematic, make a
scoped change, and run the relevant checks. Record significant decisions and
remaining limitations here. For a new chat the user can say:
"Read PROJECT_CONTEXT.md in R0SAB/VerilogCanvas and continue from the current code."

This document preserves decisions; it does not replace unavailable screenshots,
private schematics or the full original conversation.
