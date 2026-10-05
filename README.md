# VerilogCanvas Qt 1.2.2

The full native Qt edition of VerilogCanvas. The retained scene and cached grid
from the performance preview now support the complete editing workflow. HDL import and generation retain the established behavior; routing now preserves outward port stubs and shared junctions.
The interface is English.

## Run on Windows

1. Install Python 3.12 or newer with the Python Launcher (`py`).
2. Extract the archive into its own folder.
3. Run `run_qt_windows.bat`. First launch installs PySide6 in `.venv-qt`.
4. Open an existing `.vsch` or create a new schematic.

A schematic can also be dropped onto the batch file or passed to the EXE.

## Build the standalone EXE

Run `build_qt_windows.bat`. It installs dependencies, runs model and Qt interface
checks, and builds `dist\VerilogCanvasQt.exe` using PyInstaller.

The EXE includes Python and Qt; the target machine needs neither installed.
Single-file packaging extracts the required libraries at startup. The Qt bundle
will be larger than the old Tkinter EXE. Build on Windows: the release was checked
with Qt's offscreen platform on Linux, not as a Windows binary.

## Build and publish on GitHub

Builds run **only manually**. Open **Actions > Build Windows EXE > Run workflow**,
select the source branch and enter a new release tag (for example `v1.2.2`).
Source changes and pushes do not start a build.

The Windows x64 runner tests the model and all six Qt checks, then builds the
standalone executable. After success it publishes a GitHub Release containing:

- `VerilogCanvasQt.exe`: the standalone application, downloaded directly.
- `VerilogCanvas-source.zip`: tracked sources from the exact commit built,
  with a `VerilogCanvas/` root folder.
- `SHA256SUMS.txt` and `BUILD_INFO.txt`: checksums and build details.

Download these files from the repository's **Releases** page. They are release
assets, not temporary Actions artifacts. Existing tags are rejected to avoid
replacing a published version; choose a new tag for each release. The release
is prepared as a draft and published only after all assets upload successfully.
If upload/publication fails, inspect the draft before retrying.

The workflow uses Python 3.12 and the built-in GitHub token with
`contents: write` permission for release publication. No personal token is
required. Executables are unsigned.

## Editing

- Add module templates, import interfaces from `.v` / `.sv`, or add Inline HDL.
  Import supports ANSI and non-ANSI port declarations, parameters, signed ports,
  packed/unpacked dimensions and ignores output initializers.
- Double-click blocks to edit. Port lists use `[7:0]data` or
  `logic signed [WIDTH-1:0]data`; one declaration per line. Parameter values are
  displayed in the block, and resolved values appear in port dimensions.
- Input transforms use `port = ($ == MOD_AM) ? 1 : 0`. `$` is the connected
  signal. Declare enums/localparams in **Declarations** and choose SystemVerilog.
- Inline HDL has an orange frame. Declare its input/output ports, then enter the
  body without a module wrapper. Ports are generated on Apply; removed connected
  ports can be mapped to replacements. Code is inserted into the shared top-level
  scope without generated prefixes. Raw HDL remains readable inside `.vsch`.
- Drag module corners to resize. Group comments always show a corner resize grip. Select an ordinary comment
  to expose its resize handle. Top-level I/O symbols have a fixed appearance and size.
- Drag empty space to select an area; drag a selected object to move the selection.
  Group comments contain modules, I/O and ordinary comments. Moving a member
  moves its group; Ctrl+drag moves just the member. Ctrl+click followed by Copy
  copies only that member. Selecting another group member moves the green
  selection indication to that member.
- Copy/paste a group includes internal wires, labels and comments, and assigns
  unique instance, top-level port and label names. Delete removes selected objects;
  deleting a group frame alone does not delete its contents.
- Ordinary comments stay out of HDL. Group comments produce section headings;
  group-local nets are emitted before their first instance. Both captions wrap.

## Wiring

Click a port to start. Click bends, then a destination port or an existing wire.
Enter or double-click finishes an unconnected end. Esc cancels. The committed
route follows the displayed preview.

Each straight segment between corners/junctions has its own scene object.
Click and drag to move only that segment perpendicular to its direction; it alone
is highlighted green. Connecting a branch splits the host segment at the junction.
Dots mark actual divergence: coincident prefixes of a host and branch are stored
and drawn once. Drag junction dots along the host wire. Drag an
open end to reposition it, or click it to extend an attached dangling wire.
Use Alt+drag to move a completely detached wire component as a whole.

Double-click a wire or use **Net Label** to name it. Matching labels connect
separate wires electrically. Drag a label by any part of its body to slide it
along the wire or transfer it to another wire. **Edit > Reset Wire Route** removes
manual bends from a selected attached wire.

Deleting a block preserves its wires, free ends and labels. Placing a compatible
port exactly on a free end reconnects it after the move/edit. Invalid connections
can still be made and saved: affected ports/ends turn red, with details on hover.
Repair them through the properties editor; generation reports blocking errors.

## Save and export

- **Save** / Ctrl+S updates the current `.vsch`; **Save As** / Ctrl+Shift+S chooses
  another schematic file. Save retains the existing backup-file behavior.
- **Export** / Ctrl+E writes HDL immediately. First use asks for a `.v` / `.sv`
  destination; later uses overwrite that remembered destination with a small
  notification. **Export As** / Ctrl+Shift+E changes the destination.
- The output path is shown in the toolbar. Its filename determines the top module
  name and must be a valid HDL identifier. Changing language may require choosing
  a matching file extension. The output path is retained in the schematic.
- **Preview HDL** / Ctrl+P opens a separate, read-only text window.
- **Export PNG** renders the whole schematic, regardless of the viewport. The
  image excludes selection/resize indicators; the selected grid mode is included.
  Resolution is up to 2 pixels per scene unit, capped at 32 megapixels / 16384 pixels
  per side to bound memory usage.
- Undo/redo: Ctrl+Z / Ctrl+Y. Esc also cancels a drag.

## Navigation and grid

Ctrl+wheel zooms about the cursor. Wheel scrolls vertically; Shift+wheel scrolls
horizontally. Hold the middle button to pan within normal cursor/screen bounds.
Home / Fit Diagram fits all objects; the fit button is beside the zoom controls.

**Grid: Dots / Lines / Off** is retained between launches. Grid choice affects
appearance only; coordinates still snap to 20 units. Dots use a repeating texture
anchored to scene coordinates; the view caches its background for panning.
Text scales uniformly with geometry, without a minimum display size.

Scene objects persist during navigation and dragging. Only affected geometry is
updated; electrical and group indexes are rebuilt at edit completion. The status bar shows the current zoom; performance instrumentation is hidden.

## Validation and source layout

The model suite contains 166 tests. Additional Qt checks exercise real mouse
input, displayed/committed routes, branches, labels, resizing, deletion/replacement,
error highlighting, groups, copy/paste, dialogs, history, save/export, PNG, cached
grid alignment and unchanged scene objects during movement. The supplied existing
22-block / 58-wire schematic was also opened and exercised.

```
python -m unittest discover -s tests -q
python tests/qt_preview_smoke.py
python tests/qt_grid_smoke.py
python tests/qt_editor_smoke.py
python tests/qt_segments_smoke.py
python tests/qt_junction_markers_smoke.py
python tests/qt_consumed_tips_smoke.py
```

For headless Linux set `QT_QPA_PLATFORM=offscreen`.

- `qt_editor.py`: full application, actions and interactions (entry point).
- `qt_dialogs.py`: native property/source dialogs.
- `qt_app.py`: retained scene and cached viewport shared with the preview tests.
- `model.py`: schematic, routing, net validation and HDL generation.
- `hdl_import.py`, `inline_hdl.py`: HDL interfaces and inline logic.
- `schematic_text.py`, `recover_hdl.py`: plain-text source records and recovery.
- `export_cli.py`: command-line HDL export.

The old Tkinter editor is not required to run this edition.

## Changes in 1.1

- Transparent net-label backgrounds preserve nearby transform annotations.
- Group resize grips work without selecting the frame; resizing leaves contents in place.
- Module properties no longer contain numeric frame-size fields.
- Export/preview buttons precede the output-path field; add buttons have a + prefix.
- Icons follow the system text palette for contrast on dark/light themes.
- Debug timing/readout removed from the full editor.
- Vertical bends at attached ports keep a one-cell outward horizontal stub.
- Dragging a straight run moves its junctions together; redundant collinear bends
  are removed. Junctions stay on the visible host span when it shortens, instead
  of leaving doubled-back tails. Geometric crossings do not create connections.

## Changes in 1.2

- Straight segments are individual hit-tested/painted objects, split at corners
  and junctions. Dragging a segment no longer moves the entire collinear run.
- Implements all six moves in the supplied three-column diagram: both horizontal
  halves move independently; the vertical branch slides across the trunk.
- Shared branch prefixes are collapsed to one conductor. The junction follows
  actual divergence, including when the branch reaches a trunk corner. Nested
  branches on a collapsed prefix retain their connection to the shared host.
- Segment drags restore their local component snapshot before each mouse update,
  avoiding cumulative drift; undo/redo includes all affected junction geometry.
- Port hover uses a standard arrow cursor. Alt+drag preserves whole-component
  movement for completely detached wires.
- Additional tests cover the six illustrated moves in both branch orientations,
  nested and fully overlapping branches, actual mouse drags, selection and history.

## Changes in 1.2.1

- Connecting to a loose endpoint removes its open-circle indicator. Two rays
  make an ordinary bend/continuation; three or more show one junction dot.
- Multiple or nested branch attachments at the same physical point share one
  marker. Coincident unrelated wires remain separate. Markers update after
  movement, deletion and undo/redo and are also used by PNG export.
- Connected former endpoints no longer offer the free-end drag/extend action.

## Changes in 1.2.2

- Branches attached to a formerly loose endpoint move independently, including
  nested attachment order. A consumed endpoint can extend beyond its original
  position; its obsolete tail is trimmed when all attached arms move away.
- Delete on a selected free terminal segment removes that edge only and leaves
  the rest of the wire, labels and connections intact. Removing the sole remaining
  edge deletes the wire. Other wire deletion behavior is unchanged.
- Regression checks cover repeated drags, both attachment orders, HDL connectivity,
  terminal-edge deletion and undo/redo.
