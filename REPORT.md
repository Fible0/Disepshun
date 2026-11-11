# Disepshun: issues and likely performance gains

Review of the tree at `8f5e286`. Nothing in the game was changed.

**How the numbers were obtained.** The existing suite passes (102/102) and the existing benchmark runs clean. The timings below come from throwaway probes that drive the real classes through the `tests/test_regressions.py` fixtures, on Python 3.14 / Panda3D 1.10.15. Render timings used an offscreen buffer with software GL (llvmpipe), so treat them as ratios, not absolute frame times. Items marked *(by reading)* were not executed.

**Overall picture.** Steady-state play on a static map is cheap: collision queries, the glow scan, mover stepping and chunk culling are all already well under a millisecond at 16,000 blocks. The cost is concentrated in three places: the editor with large selections, maps with many moving blocks, and full-map work done on the main thread for every small edit.

## Performance gains, largest first

### P1. A large selection costs about 20 ms every frame, even when idle

With 16,000 blocks selected (Ctrl+A) and nothing changing:

| Per-frame call | Cost |
| --- | --- |
| `refresh_object_selection` (`editor_tools.py:85`, called from `Main.py:728`) | 7.5 ms |
| `draw_selection_center` (`editor_tools.py:173`, called from `Main.py:785`) | 12.1 ms |

Both rescan the whole selection each frame: the first re-validates every node and rebuilds two sets, the second re-reads every position and averages them. That caps the editor near 50 FPS on its own.

- Fix: run `refresh_object_selection` only when the selection or the block set changes (a dirty flag set by select, delete, undo and tool switch).
- Fix: cache the pivot and recompute only when the selection changes or it contains a moving block.

`draw_selection_center` also degrades quadratically when the selection is all movers, because `any(not find_mover(c) ...)` never short-circuits: 2,000 selected movers cost 61 ms per frame.

### P2. `find_mover` and `self.cubes` are linear scans inside loops

`WorldManager.find_mover` (`world_manager.py:332`) walks the mover list comparing NodePaths, and `self.cubes` is a list that is tested with `in` and edited with `.remove()`. Both sit inside per-block loops, so bulk operations go quadratic:

| Operation on a 16,000-block map | Time |
| --- | --- |
| Delete the 4,000 most recently placed blocks | 1,296 ms |
| Delete the other 12,000 (front of the list, best case) | 116 ms |
| Move a 16,000-block selection one cell | 404 ms |
| Undo that move | 449 ms |
| Fill 8,000 cells, no movers in the map | 158 ms |
| Fill 8,000 cells, 200 movers elsewhere in the map | 683 ms |

- Fix: keep a `node -> mover` dict (or a Python tag on the node) so `find_mover` is O(1). It is called from `transform_selection` (four times per block), `EditHistory.capture`, `update_cube_faces`, `ensure_selected_movers`, `select_object` and `draw_selection_center`.
- Fix: make `self.cubes` a dict or set (insertion-ordered dict keeps save order). `remove_block`, `convert_to_mover` and `update_god_collision` then stop scanning.
- Fix: `unregister_cube` (`world_manager.py:248`) does `in` plus `.remove()` on a per-chunk list; a per-chunk set or dict removes that scan too.
- Fix: `fill_corner` (`editor_tools.py:429`) tests every cell against every mover. Bucket mover positions by cell once before the loop, as `valid_positions` already does.

### P3. Every small edit serialises the whole map on the main thread

`save_map` builds the full text snapshot synchronously before handing it to the writer thread: 35.6 ms for 16,000 blocks, scaling linearly. Only block placement, fill, checkpoint activation and undo/redo go through the debounced `queue_save`. Everything else calls `save_map` directly:

- Held left-click delete repeats every 0.1 s, so each repeat stalls about 38 ms (`Main.py:863`).
- Holding `-`/`=` or `Z`/`X` on a mover or trampoline does the same every 0.1 s (`Main.py:491`, `497`, `506`).
- Every `commit_editor` call (move, rotate, group, paste, checkpoint turn) at `editor_tools.py:233`.

Moving one block on a 16,000-block map takes 61 ms: 35 ms of serialisation plus 23 ms in `valid_positions`.

- Fix: route all of these through `queue_save`. The exit path already flushes.
- Fix: `valid_positions` (`editor_tools.py:301`) rebuilds a spatial hash of every block per call. Static blocks are already indexed in `cube_map`; only movers need bucketing.
- Smaller: `_threaded_save` gzips and fsyncs a snapshot even when a newer one is already queued. Skipping when `gen < self.save_gen` avoids redundant writes during held keys.

### P4. Each moving block is drawn as six separate cards

`update_cube_faces` (`world_manager.py:351`) gives every mover a `face_geom` with six copied `CardMaker` nodes, so each moving block is six draw calls and seven scene nodes. Blocks attached to a mover become movers themselves, so a moving structure multiplies this quickly.

| 2,000 movers, offscreen render | Shaders on | Shaders off |
| --- | --- | --- |
| Six cards each (current) | 30.5 ms/frame | 20.0 ms/frame |
| One merged geom each (`flattenStrong` on `face_geom`) | 10.8 ms/frame | 7.7 ms/frame |

- Fix: build one 24-vertex cube geom once and instance it per mover, restyling the single node. About a 3x cut in mover render cost.
- Further: blocks that share a path and speed move in lockstep. Parenting them under one moving node and merging their geometry would make a moving structure one draw call and one position update.

### P5. Per-frame mover cost in physics and stepping

Every collision query loops over all movers with `getPos(self.render)` (`player_physics.py:99`), and a frame makes four to six queries. `update_world` then steps each mover in Python.

| Movers | `physics.update` while walking | `update_world` |
| --- | --- | --- |
| 0 | 0.06 ms | n/a |
| 200 | 0.49 ms | 0.5 ms |
| 2,000 | 4.53 ms | 5.6 ms |

- Fix: `update_world` already reads every mover position each frame. Store them in a cell-bucketed dict there and have `get_contacts` and `vertical_step` look up only nearby cells, as they do for static blocks.

### P6. Undo history is bounded by count, not size

One 16,000-block move retains 22.8 MB in the undo stack (a `before` and an `after` dict per block). The limit is 100 entries, so repeated moves of a large selection can hold over 2 GB.

- Fix: cap the stack by total captured blocks as well as entry count, or store states as compact tuples.
- Related: `_restore` (`edit_history.py:51`) deletes and recreates every affected block instead of patching position and tags, which is why undoing a move costs as much as the move.

### P7. Smaller wins

- **Uncapped frame rate.** `config.py` sets `sync-video 0` with no limiter, so the game renders flat out, including in the settings menu and when unfocused (`Main.py:644` skips the logic, not the rendering). A VSync or FPS-cap setting, plus a low cap while paused or unfocused, cuts GPU load and heat. *(by reading)*
- **Picking ray is infinite.** The per-frame pick uses a `CollisionRay`, although hits beyond `build_dist` (20 at most) are discarded. A `CollisionSegment` of that length took 0.13 ms against 0.52 ms for the ray in a grazing view over 16,000 blocks.
- **Sky sphere is redundant.** `create_sky` loads a model and draws a black sphere over a black clear colour (`world_manager.py:147`, `Main.py:26`). *(by reading)*
- **Select-all rebuilds every chunk mesh** (177 ms for 16,000 blocks, spread across frames by the 2.5 ms budget). A separate highlight overlay would avoid remeshing for a colour change; only worth doing if selection lag is noticeable after P1 and P2.
- **Packaged start-up.** `Build.cmd` uses one-file mode with `--collect-all panda3d`, so the 47 MB executable unpacks to a temp folder on every launch. One-folder mode starts faster, and collecting only the Panda modules in use shrinks it. *(by reading)*

### Checked and not worth changing

- Collider nodes in the scene graph add no measurable cull cost (2.60 ms with them, 2.53 ms hidden): Panda prunes subtrees with nothing renderable.
- Contacts (0.006 ms), glow scan (0.15 ms every 0.2 s), mover path caching and bloom input updates are already fast.
- The X11 icon pixel loop costs 31 ms once at start-up.

## Issues

### I1. A crash exits silently and can drop the last edits

`Main.py:866-869` catches any exception from `app.run()`, prints the traceback and ends. *(by reading)*

- The packaged build is `--windowed`, so there is no console: the game just disappears with no log.
- `flush_saves` is not called on that path. Writers already started finish, but an edit still waiting in the `queue_save` debounce, or marked dirty for retry, is lost.
- Fix: write the traceback to a log file in `DATA_DIR` and call `self.world.flush_saves()` in a `finally`.

### I2. Queued saves and save errors stall while paused or unfocused

`retry_save` and the save-error notice are at the end of `update` (`Main.py:733`), after the early returns for "not focused" (`:644`) and "paused" (`:659`). Place a block and press Esc or alt-tab within 0.35 s, and the write waits until play resumes. A failed save is also not retried in that state. *(by reading)*

- Fix: move the save retry above those returns.

### I3. Jump and trampoline heights depend on frame rate

Physics runs on the variable frame `dt` with gravity applied before the move. From the game's own stepping formula (`sim_bounces`), a standing jump peaks at 1.50 at 30 FPS, 1.57 at 60 and 1.62 at 240. Trampoline chains compound the difference, and the bounce ghosts are drawn for the builder's current average FPS (`Main.py:226`). With the frame rate uncapped, a course tuned on one machine can play differently on another.

- Fix: step physics and movers on a fixed timestep (for example 120 Hz with an accumulator). The ghosts then need no FPS input.

### I4. Falling forever in god mode gets slower and slower

With invincibility on and the visual floor off, nothing respawns the player below z = -20 and there is no terminal velocity. Below z = -1000, `get_contacts` reports out-of-bounds, `vertical_step` finds no ground and keeps falling (`player_physics.py:204-213`). The number of vertical sub-steps is `|vz*dt| / 0.25`, so it grows without limit: roughly 800 sub-steps per frame after ten minutes at 60 FPS, each looping over all movers. *(by reading)*

- Fix: clamp `vz` to a terminal velocity and stop or respawn at the lower bound.

### I5. The GPU notice shows Windows-only instructions on Linux

`check_startup_gpu` (`Main.py:333`) runs on every platform on first launch. On Linux the adapter list is empty, so the dialog says "Could not enumerate other GPUs" above steps for Windows Settings. *(by reading)*

- Fix: skip the notice when `os.name != 'nt'`.

### I6. A v3 map with one bad record refuses to load at all

Properties are stored as a list parallel to the block order. If `parse_map` rejects any record (bad value, duplicate position), the counts no longer match and `load_map` stops with "Map properties do not match its objects" (`world_manager.py:690`): empty world, saving disabled. The backup-and-load-the-rest branch below it can therefore only run for legacy maps. That early return also skips the `print` that the other failure paths have. *(by reading)*

- Fix: store group and heading on each record, or keep the property index alongside each parsed record so rejected lines drop their own entry.

### I7. The 47 MB executable is committed to git

`Disepshun.exe` is tracked, and `Build.cmd` writes it into the repo root. `.git` is 49 MB, of which the source history is about 0.5 MB; each rebuild committed adds another 47 MB permanently.

- Fix: publish builds as release assets, and add `Disepshun.exe` and `.pyinstaller-build/` to `.gitignore`.

### I8. Minor

- **Preview normals.** `CUBE_FACES` in `Main.py:188` rotates the -Y face 180° and the +Y face 0°, the opposite of `update_cube_faces`. The preview and bounce ghosts are two-sided so they still draw, but with Preview Shading on those two faces are lit as if facing the other way. *(by reading)*
- **Dead code.** `update_neighbor_visibility`, `handle_sel`, `GameUI.toggle_gui`, `gpu_recommendation` / `check_renderer` (tests only), the `"Hide Low Power GPU Warning"` setting, the `wait_timer` mover field, and the `chunk_` name branches at `Main.py:696-706` and `:854-860` (chunk meshes have their collide mask off, so the ray never returns them).
- **Duplicate sound loading.** `PlayerPhysics` loads `respawn.mp3` and `checkpoint.mp3` itself and repeats the sound-enabled check, instead of using `play_sfx`.
- **Empty bookkeeping grows.** `unregister_cube` on a mover creates an empty `chunk_contents` entry for whichever chunk it happens to be in, and empty `chunk_colliders_*` nodes are never removed. Harmless, but it accumulates over a long session.
- **Launchers.** `Main.py` starts the game at import with no `__main__` guard, which is why the tests have to extract classes through `ast`. `Run.cmd` and `Run.sh` use whatever Python is the default rather than the 3.12 the README requires (the suite does pass on 3.14).
- **`config.py`.** It is a star-import that also performs process-wide side effects at import (DPI awareness, creating a graphics pipe, PRC settings) and supplies `os`, `math`, `threading` and `random` to every module implicitly.

## Suggested order

1. P2 (dict-backed movers and cubes): small change, removes the worst stalls, and makes P1 and P5 simpler.
2. P1 and P3: dirty-flag the selection work and send every edit through `queue_save`.
3. I1 and I2: crash log, flush on crash, save retry while paused.
4. P4: single-geom movers.
5. I3 if cross-machine consistency of courses matters; the rest as convenient.
