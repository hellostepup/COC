# COC Farming & Upgrade Manager

A Windows desktop app for managing several Clash of Clans accounts: resource targets, upgrade queues,
builders, account rotation, and attack suggestions taken from BlueStacks screenshots.

**Loop:** Resource Farming → Target Completion → Building Upgrade → Next Account → Repeat.

The app only reads and suggests. It sends **no input** to BlueStacks or the game. You do the
searching, troop deployment, ending battles, starting upgrades and switching accounts yourself,
as Supercell's rules require. The fully automated loop exists only in the **Simulation** page,
which runs against a mock game.

## Stack
| Part | Tech |
|---|---|
| Desktop shell | Electron 33 (starts the backend, Windows toast notifications) |
| UI | React 18 + Tailwind CSS (Vite) |
| Backend | Python + FastAPI, SQLite (`%APPDATA%\COCManager\coc_manager.db`) |
| Vision | OpenCV, optional YOLO (ultralytics), optional Tesseract OCR |

## Run on Windows
1. Install Python 3.9+ and Node.js 18+.
2. `scripts\setup_windows.bat` (one time)
3. `scripts\start_windows.bat`
4. Optional OCR: install [Tesseract for Windows](https://github.com/UB-Mannheim/tesseract/wiki) and add it to PATH.

Build an installer: `scripts\build_installer.bat`. It packages the backend with PyInstaller, then
builds an NSIS `.exe` into `frontend\release`.

Dev mode (any OS): `cd backend && .venv/bin/python run.py`, then `cd frontend && npm run dev`, and open http://localhost:5173.

## Features → where they live
| Requirement | Where |
|---|---|
| 4+ accounts, each with its own targets, queue and settings | Sidebar → account page |
| Priority % per resource, objective, minimum targets, troops, defense avoidance | Account → Farming Strategy |
| Upgrade queue (name, levels, costs, time, builders, priority, status) | Account → Upgrade Queue |
| Remaining resources per task and for the whole queue | Queue rows and the Resources panel |
| Sequential queue: if #1 is blocked, #2 can still be ready (loot is set aside so two tasks never share it) | `backend/app/planner.py` `plan_queue` |
| Walls: many segments in one task, each paid with Gold **or** Elixir; shows how many you can do now and how much loot the rest needs | Upgrade with category "wall" → "I upgraded walls" |
| Keep farming until storage is full once every upgrade is done | Account → Farming Strategy checkbox |
| "I started it" → In Progress → auto-completes when the timer ends | Queue buttons; backend checks every 30 s |
| Account status (Farming Required, Upgrade Ready, Builder Busy, Storage Full, Target Completed, All Completed…) | Status chips |
| Rotation: next recommended account | Dashboard → Account Rotation |
| Desktop notifications (target reached, builder available, storage almost full, upgrade completed, ready for next upgrade, resource required) | Fire once when a condition turns on |
| Battle screenshot → resource buildings, sides, defenses, target group, deploy points | AI Vision → Battle layout |
| Read resource counters and builders → confirm → update account | AI Vision → Home village |
| Check which account is open after switching | AI Vision → Verify account |
| Manual correction of every detection | AI Vision (click to add, select to relabel or delete) |
| Mock environment + four-account workflow test | Simulation page, `backend/app/simulation.py` |
| Backup / restore, error logs, settings | Settings |

## About the AI detector
There is no trustworthy public model for COC buildings, so the app ships without one and improves as you use it:
1. **Manual**, from day one: mark buildings on the screenshot, then press Analyze.
2. **Templates**: put PNG crops of buildings in `%APPDATA%\COCManager\templates\<label>\` (for example `gold_storage\lvl12.png`). OpenCV template matching then finds them.
3. **YOLO**: every corrected screenshot becomes a labelled sample. Use Settings → Export YOLO dataset, then
   `pip install ultralytics` and `python backend\train_yolo.py`. The model is used automatically once
   `models\coc_buildings.pt` exists.

Detections below 50% confidence are dashed and flagged for review. OCR values are never saved until you confirm them.

## Tests
`cd backend && .venv/bin/python -m pytest` runs 25 tests, covering the acceptance criteria: account isolation,
remaining-cost maths, the priority queue, walls paid with Gold or Elixir, notifications, rotation, persistence across
restart, database migration, layout analysis, manual correction, backup/restore, and the full four-account simulation.

The starter accounts' upgrade costs and durations are placeholders. Edit them to match the in-game upgrade screen.
