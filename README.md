# Disepshun

Disepshun is a vibe-coded Python 3 Panda 3D obby game.

## Requirements

- Python 3.12 (64-bit)
- Dependencies: `python -m pip install -r requirements.txt`
- Windows or Linux with OpenGL graphics

## Running

- Windows: `Run.cmd` (or `py Main.py`)
- Linux: `./Run.sh` (or `python3 Main.py`)

Rendering is uncapped: in-game VSync is disabled and the clock runs in normal mode.

## Controls

| Key | Action |
| --- | --- |
| WASD / Mouse | Move / look |
| Space | Jump |
| Left / Right Shift | Crouch (descend while flying) |
| Right click | Place block / add waypoint |
| Left click | Delete block / select |
| Mouse wheel | Build distance |
| 1-5 | Block type: white, gray, red (lethal), green (checkpoint), blue (trampoline) |
| Q | Switch hotbar (blocks / tools) |
| Tab | Switch between Select and Tinker for Waypoint / Selection |
| LCtrl+Z / LCtrl+Y | Undo / redo map edits |
| - / = | Adjust mover speed, trampoline bounce, or checkpoint facing |
| Z / X | Adjust trampoline max height |
| [ / ] | Adjust fly speed |
| R | Undo last waypoint |
| F | Toggle fly |
| G | Toggle invincibility (God mode) |
| Esc | Settings menu |

## Editor tools

Press **Q** to open Tools, then **1-5** for Waypoint, Trampoline, Checkpoint,
Grouping, or Selection. Blue trampoline blocks remain in the Blocks bar and now
place/delete like ordinary blocks. The separate Trampoline tool edits bounce and
maximum height on selected static or moving trampolines. The hotbar keeps its
original compact layout; switching items briefly shows the item name, then fades it.

Waypoint and Selection start in **Select** mode. Left click adds/removes objects;
Selection also allows LCtrl+A / LCtrl+D to select all or clear. **Tab** switches
these two tools to **Tinker**, locking selection while editing, and back again.
Checkpoint, Trampoline and Grouping allow selecting and editing together without
modes. Their HUDs show selection and editing controls at the same time.
Selecting a static block with Waypoint does not convert it into a mover until you edit it.

Selecting a grouped block selects the whole group. Trampoline selects only its
trampolines, and Checkpoint only its checkpoints. Selection colors are restored:
Waypoint violet, Trampoline amber, Checkpoint cyan, Grouping lime, and Selection
pink. These highlights apply to ordinary and glowing blocks and clear on
deselection. Glowing blocks combine shaded faces with
broad colored bloom halos and nearby light spill. Four pooled lights provide
the spill without creating a light for every block. The bloom mask is applied to hazards and checkpoints, so
ordinary white/gray blocks stay sharp. Kill blocks have stronger red halos and
light spill; checkpoint glow is unchanged. The Shaders setting controls this effect.

The Checkpoint tool selects green checkpoint blocks. Use **- / =** to turn the
spawn facing in 15-degree increments, or **Enter** to use your current horizontal
look direction. Every selected checkpoint has a solid yellow arrow showing the
saved facing, including moving checkpoints.
Arrows have dark outlines, hover above the blocks, and grow with viewing distance
to stay readable. Facing applies on
respawn and when reopening a map with an active checkpoint.

Grouping allows selecting and grouping together. Select objects, then tap and release
**LCtrl** by itself to group them. If the selection is already one complete group,
the same key ungroups it. Ctrl chords cancel that tap, so LCtrl+Z/Y can undo/redo
without accidentally grouping. Grouping has no clipboard or transform actions.

Selection has these controls (selection actions in Select mode, editing actions
in Tinker mode). Group/ungroup commands belong exclusively to Grouping:

| Key | Action |
| --- | --- |
| Left click | Add/remove an object or its entire group from selection |
| Right click | Move the active selection pivot to the preview |
| Arrow keys | Move one unit along world X/Y |
| Page Up / Page Down | Move one unit vertically |
| E | Rotate 90 degrees around world Z at the active selection pivot |
| LCtrl+C / LCtrl+X / LCtrl+V | Copy / cut / paste at the preview |
| Delete | Delete the selection |
| LCtrl+A / LCtrl+D | Select all / clear selection |

All in-game Ctrl shortcuts require **Left Ctrl**; Right Ctrl does not activate
them. **LCtrl+Z / LCtrl+Y** undo/redo the last 100 map edits in this session,
including placement, group deletion, group/ungroup, paste, transforms, tool
properties, and waypoint editing. A new edit clears the redo branch. Runtime
power toggles and settings changes are outside map-edit history.

The Selection Tool uses one **cyan waypoint-style point** for both its center
and pivot. That point stays at the active edit reference and follows moving
selections; there are no separate center/pivot markers.

**Use Last Selected as Pivot** replaces **Relative Waypoints**, preserving the
saved value. When off, Waypoint offsets and Selection move/rotate/paste use the
selection center; when on, they use the last selected block. If the center would
put static cubes off the unit grid, the last block is used automatically. The
shared center/pivot point shows that same reference in either case.

A group behaves as one selection while keeping each member's material, collider,
checkpoint facing, trampoline settings, and moving path. Copied groups receive
new identities. Deleting or cutting any group member deletes/cuts the entire
group, including moving members and checkpoints. Undo restores their properties
and checkpoint identity. Transformations update moving origins and waypoints too. Edits
that would overlap other objects or leave the map bounds are rejected together.
Static cubes stay on the unit grid; rotation changes their arrangement and
checkpoint facing. Tools use their own selection colors to mark selected blocks.

## Map format and conversion

The game saves `data/map_save.dmf`: a `DMAP3` signature followed by gzip-compressed
UTF-8 JSON with a version, validated block/path records, group IDs, and checkpoint
headings. Writes still use a temporary file and atomic replacement. Rapid block
placements and checkpoint activations batch saves over 0.35 seconds; exiting
always flushes the latest pending state. Compression runs on the save writer,
and edit-time mesh rebuilding has a frame budget. Legacy text
maps remain readable. When no compressed save exists, the game loads
`data/map_save.txt`, keeps a timestamped backup, and automatically saves the new
format. Once present, the compressed save takes priority. Previous `.dmap` saves also
load and migrate to `.dmf`, preserving their contents.

Settings also contains **Convert legacy maps**, which converts valid `.txt` maps
and previous `.dmap` maps in `data/` to matching `.dmf` files. It preserves originals and skips destinations
that already exist and maps containing invalid records. A sample 900-block map
uses about 86% less space than the prior text format.

## Discord Rich Presence

The integration uses [PyPresence](https://qwertyquerty.github.io/pypresence/html/doc/presence.html)
and Disepshun's fixed public Application ID, **1566233876823678996**. The ID editor
and environment override are removed; old saved ID values are ignored. No bot
token or client secret is used. The Discord desktop client must be running, with
activity sharing enabled in Discord.

Settings has **Discord Rich Presence** to switch sharing off entirely, plus
independent switches for **Discord Show Activity** (current tool/building/settings),
**Discord Show Block Count**, **Discord Show Time** (elapsed session time), and
**Discord Show Icon**. These preferences save between launches. Hiding a field
removes it from the next presence update; disabling all four still lets Discord
show the game name. Turn off Discord Rich Presence to clear the game's presence.
The worker updates every 15 seconds, wakes immediately when a preference changes,
and reconnects after Discord becomes available. Its connection status remains
visible in Settings. Turning presence off hides its four display switches and
status row; turning it back on restores their saved values. The scrollable menu
ends at the last visible control without reserving empty rows.

An Application ID is a public identifier, suitable for including in the game.
Bot tokens and client secrets are private credentials. A Discord application is
the registered container for features such as game presence and bots. A bot is
an automated Discord account that can respond to commands or server events;
Disepshun's presence only tells your local Discord client what game information
to display on your profile. Creating the application does not require running a bot.

The uploaded General Information app icon is reused through its public Discord
CDN URL as the presence's large image. Uploading an app icon alone did not work
with the earlier implementation because it did not send an image field. Rich
Presence art assets are separate uploads referenced by their asset keys. If the
app icon is replaced later, update the image reference in `disepshun/presence.py`.

The original walking, jumping, respawning, checkpoint, breaking, placing, and
settings-toggle MP3s are preserved, including their original playback timing.
Other actions use distinct glass drops, wooden knocks, metal latches, rubber
impacts, radio clicks, paper-like friction, wind swishes, motor blips, and chimes. Settings switches use their original on/off toggle sound and pitches.
Two universal cues indicate enabling/disabling Flight or Invincibility. A
separate landing impact changes pitch and volume with the height of the fall;
standing contacts do not repeat it, and trampoline bounces keep their own cue.
Each numerical adjustment uses the same cue in either direction, pitched higher
for increases and lower for decreases, with subtle variation. This applies to
flight speed, mover speed, trampoline bounce/height, and checkpoint turning. Landing audio waits briefly and
is suppressed when jumping on contact or immediately afterward.
Trampoline height uses its restored original cue with playback variation. Ungrouping has a longer metallic
ring. All effects receive subtle random pitch and volume variation, including
respawn; checkpoint activation retains its existing pitch progression without
random variation. The Sound setting controls all effects. A checkpoint remains active while you
still touch it, even when straddling two blocks; repeated contact cannot retrigger
it. Checkpoint particle bursts share a bounded node budget.

## GPU startup notice

On Windows 10 version 1803 or newer, startup compares the active Panda3D renderer
with Windows' hardware GPU preference order. If a known lower-priority GPU is in
use and a different high-performance GPU is available, a modal shows both names.
Unknown renderers, unsupported enumeration, software adapters, and single-GPU
systems do not trigger it.

**Use better GPU** opens **Settings > System > Display > Graphics** and shows the
exact executable to add. Source builds use the Python executable running the
game. Choose **Options > High performance**, select the recommended GPU, save,
and restart Disepshun. The running renderer cannot switch GPUs in place. If the
Settings link fails, the modal still gives the manual path and instructions.
**Close** or **Esc** dismisses it for the current launch. **Never show this again**
saves the preference immediately. Otherwise the check runs again on every launch
and stops showing the notice once the better GPU is in use. Gameplay pauses while
the notice is open.

## Verification

Run `python tests/test_regressions.py` for physics, editor, save, corruption, and
migration checks. These checks use temporary maps.
