# Disepshun

Disepshun is a Python 3 Panda3D obby game with an in-game map editor.

## Setup

Requires Python 3.12 (64-bit) and Windows or Linux with OpenGL graphics.

Install dependencies:

```sh
python -m pip install -r requirements.txt
```

- Windows: `Run.cmd` or `py Main.py`
- Linux: `./Run.sh` or `python3 Main.py`

## Controls

| Key | Action |
| --- | --- |
| WASD / Mouse | Move / look |
| Space | Jump / ascend while flying |
| Left / Right Shift | Crouch / fall faster / descend while flying |
| Right / Left click | Place / delete blocks; tool actions listed below |
| Mouse wheel | Adjust build distance |
| 1-5 | Blocks: white, gray, lethal red, checkpoint green, trampoline blue |
| Q | Switch between Blocks and Tools hotbars |
| Tab | Switch Select / Tinker for Waypoint and Selection |
| LCtrl+Z / LCtrl+Y | Undo / redo up to 100 map edits |
| - / = | Adjust the active tool's property |
| Z / X | Decrease / increase trampoline maximum height |
| [ / ] | Decrease / increase fly speed |
| F / G | Toggle flight / invincibility |
| Esc | Open / close Settings |

Ctrl shortcuts use **Left Ctrl**. Tool controls also appear in the HUD.

## Editor tools

Press **Q**, then **1-6** to choose a tool. Left click selects or deselects
objects in Select mode. **Tab** switches Waypoint and Selection to Tinker mode;
other tools allow selection and editing together.

| Slot | Tool | Controls |
| --- | --- | --- |
| 1 | Waypoint | In Tinker: right click adds a waypoint, left click removes the last; - / = adjusts speed; L toggles loop / back-and-forth motion |
| 2 | Trampoline | Select blue blocks; - / = adjusts bounce; Z / X adjusts maximum height |
| 3 | Checkpoint | Select green blocks; - / = turns spawn facing by 15 degrees; Enter uses your look direction |
| 4 | Grouping | Select at least two blocks, then tap LCtrl to group; tap again on a complete group to ungroup |
| 5 | Selection | Select blocks, then use the controls below in Tinker mode |
| 6 | Fill | Right click two corners to fill a box; left click cancels; - / = chooses material or checkers; H toggles Solid / Hollow |

Selecting a grouped block selects its group. Trampoline and Checkpoint select
only matching blocks within that group. Deleting or cutting a group member
affects the entire group.

### Selection controls

| Key | Action |
| --- | --- |
| LCtrl+A / LCtrl+D | Select all / clear in Select mode |
| Right click | Move the selection pivot to the preview |
| Arrow keys | Move along world X/Y |
| Page Up / Page Down | Move vertically |
| E / T | Rotate horizontally / vertically by 90 degrees |
| LCtrl+C / LCtrl+X / LCtrl+V | Copy / cut / paste at the preview |
| Delete | Delete selected objects |

The cyan point marks the selection pivot. **Use Last Selected as Pivot** in
Settings chooses the last selected block instead of the selection center.
The last block is also used when the center would put static blocks off-grid.
Moving paths transform with their blocks. Overlapping or out-of-bounds edits
are rejected.

Fill skips occupied blocks and the player's space. Each box is limited to
32,768 cells. Map edits, including fills and tool properties, support undo/redo.

## Saves and settings

- Map: `data/map_save.dmf`
- Settings: `data/settings.json.gz`
- New maps start from `assets/default_map.dmf`.

Legacy `.txt` and `.dmap` saves migrate automatically. **Convert legacy maps**
in Settings converts other maps in `data/` to `.dmf`, keeping the originals.

Settings includes sound, particles, previews, shaders, HUD visibility, and
Discord Rich Presence. Discord desktop must be running with activity sharing
enabled; activity, block count, elapsed time, and icon can be toggled individually.

The first-launch graphics notice lists detected GPUs and opens Windows graphics
settings to choose an app GPU. Restart the game after changing the preference.

## Verification

```sh
python tests/test_regressions.py
python tests/benchmark_performance.py
```

The regression suite checks physics, editor actions, saves, and migrations.
The benchmark measures individual CPU workloads rather than overall FPS.