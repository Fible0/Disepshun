# Disepshun

A Panda3D obby game with an in-game map editor.

## Setup

Requires Python 3.12 (64-bit) and Windows or Linux with OpenGL graphics.

Install dependencies:

```sh
python -m pip install -r requirements.txt
```

Run the game:

- Windows: `Run.cmd` or `py -3.12 Main.py`
- Linux: `./Run.sh` or `python3.12 Main.py`

`Build.cmd` builds a Windows executable into `dist\Disepshun\`; share that whole folder.

## Controls

| Key | Action |
| --- | --- |
| WASD / Mouse | Move / look |
| Space | Jump / ascend (flying) |
| Shift | Crouch / fall faster / descend (flying) |
| Right / Left click | Place / delete blocks, or tool action |
| Mouse wheel | Build distance |
| 1-5 | Blocks: white, gray, lethal, checkpoint, trampoline |
| Q | Toggle Blocks / Tools hotbar |
| Tab | Select / Tinker mode (Waypoint, Selection) |
| LCtrl+Z / LCtrl+Y | Undo / redo (up to 100 edits) |
| - / = | Active tool property |
| Z / X | Trampoline max height |
| [ / ] | Fly speed |
| F / G | Flight / invincibility |
| Esc | Settings |

## Editor tools

Press **Q**, then **1-6**. Left click selects or deselects in Select mode.

| Slot | Tool | Controls |
| --- | --- | --- |
| 1 | Waypoint | Tinker: right click adds, left click removes last; - / = speed; L loop / back-and-forth |
| 2 | Trampoline | Select blue blocks; - / = bounce; Z / X max height |
| 3 | Checkpoint | Select green blocks; - / = turn spawn facing 15°; Enter uses look direction |
| 4 | Grouping | Select 2+ blocks, tap LCtrl to group; tap again on a complete group to ungroup |
| 5 | Selection | Select blocks, then use the controls below in Tinker mode |
| 6 | Fill | Right click two corners; left click cancels; - / = material or checkers; H solid / hollow |

Selecting a grouped block selects the whole group (Trampoline and Checkpoint
select only matching blocks in it). Deleting or cutting a group member affects
the whole group. Fill is capped at 32,768 cells.

### Selection controls

| Key | Action |
| --- | --- |
| LCtrl+A / LCtrl+D | Select all / clear (Select mode) |
| Right click | Move pivot to preview |
| Arrows / PgUp / PgDn | Move X/Y / vertically |
| E / T | Rotate 90° horizontally / vertically |
| LCtrl+C / X / V | Copy / cut / paste |
| Delete | Delete selection |

## Files

- Map: `%LOCALAPPDATA%\Disepshun\map_save.dmf` on Windows (new maps start from `assets/default_map.dmf`)
- Settings: `%LOCALAPPDATA%\Disepshun\settings.json.gz` on Windows

Both Python runs and packaged executables use the same save folder.
On other platforms, saves use `$XDG_DATA_HOME/Disepshun`, defaulting to `~/.local/share/Disepshun`.
Open `%LOCALAPPDATA%\Disepshun`
in File Explorer to access these files. Close the game before replacing the map.
Bundled assets, including the default map, ship inside the build folder.
If the game crashes, details are appended to `crash.log` in the same save folder.

Legacy `.txt` / `.dmap` saves migrate automatically.

## Tests

```sh
python tests/test_regressions.py
python -m unittest discover -s tests
python tests/benchmark_performance.py
```
