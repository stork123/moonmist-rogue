# Moonmist — Visual Mapper

A Rogue-style visual mapper for Infocom's **Moonmist** (1986), a gothic mystery adventure by Stu Galley and Geoffrey C. Longman. Explore Tresyllian Castle on a moonlit night with an interactive map that reveals rooms as you discover them.

![Moonmist Visual Mapper](https://img.shields.io/badge/Z--machine-v3-blue) ![Flask](https://img.shields.io/badge/Flask-server-green) ![dfrotz](https://img.shields.io/badge/dfrotz-backend-orange)

## Features

- **Rogue-style map** — rooms render as walled tiles on a canvas, connected by corridors
- **Fog of war** — unvisited rooms are nearly invisible; you reveal the castle as you explore
- **Click to move** — click an adjacent room on the map, or use N/S/E/W/U/D keys
- **Live game panel** — room descriptions, items, exits, and command input alongside the map
- **Time display** — Moonmist uses a clock (hours:minutes) instead of a score; the status bar shows the in-game time
- **Multi-session** — each player gets their own dfrotz process via session IDs
- **Save/Restore** — save and restore your game state per session

## Architecture

```
Browser  →  POST /api/command  →  Flask  →  dfrotz subprocess  →  response JSON
```

- `server.py` — Flask server managing a pool of `DfrotzSession` objects (one dfrotz process per player)
- `index.html` — the visual client (canvas map + game panel), works in both Flask and Electron modes
- `MOONMIST.DAT` — the Z-machine story file (Z-machine v3, Release 9)
- `moonmist_data.json` — room map data (positions, exits, objects) parsed from the ZIL source

## Running Locally

```bash
pip install flask
python server.py
# Open http://localhost:5000
```

Requires `dfrotz` (or `dfrotz.exe` on Windows) in PATH, or set `DFROTZ_CMD` env var.

## Docker

```bash
docker compose up -d
# Open http://localhost:5003
```

## Map Data

Room positions, exits, and objects were parsed from the ZIL source at [historicalsource/moonmist](https://github.com/historicalsource/moonmist) using directional BFS layout. The castle has 56 rooms across two connected components (the main castle and a secret tomb).

## Credits

- Moonmist © 1986 Infocom, Inc. — designed by Stu Galley and Geoffrey C. Longman
- [dfrotz](https://github.com/DavidGriffith/frotz) — dumb frotz Z-machine interpreter
- ZIL source: [historicalsource/moonmist](https://github.com/historicalsource/moonmist)
