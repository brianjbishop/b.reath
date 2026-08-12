# breath-choir-aug-13

Breath-driven MIDI tooling for the **TOTEM** iOS app: a **Breath → MIDI** controller and an optional **standalone breath viewer**. Both use **Dear PyGui** for the UI (no Qt), which keeps the stack consistent and avoids common macOS Qt platform plugin issues.

## What’s in this folder

| Piece | Purpose |
|--------|--------|
| **`breath_midi/`** | Main app: TOTEM breath over **BLE** or **OSC**, signal processing, triggers, MIDI out. UI is one Dear PyGui window (live monitor, plot, tabs for Input / Detection / MIDI / Triggers). |
| **`config.toml`** | Controller settings (input, signal, detection, MIDI, triggers). |
| **`totem_ble_viewer.py`** | Optional **viewer-only** script: same TOTEM BLE/OSC protocols, scrolling plot—useful when you only want to monitor breath, not drive MIDI. |
| **`Start.command`** | Double-click launcher (macOS): `cd` here, activates `.venv`, runs `python -m breath_midi.app`. |

## Prerequisites

- macOS (BLE uses **CoreBluetooth** via **bleak**).
- Python **3.11+** (3.12 recommended; match what you used to create `.venv`).
- TOTEM iOS app with **BLE** or **OSC** breath streaming enabled as needed.

## Setup

From this directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

To refresh an existing venv to match `requirements.txt`:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

You can remove old Qt/plot-only packages if they are still present:

```bash
pip uninstall -y PySide6 pyqtgraph PyQt6 numpy pyside6-essentials pyside6-addons shiboken6
```

(Only run `pip uninstall` for packages you no longer need elsewhere.)

## Run — Breath → MIDI (main app)

```bash
source .venv/bin/activate
python -m breath_midi.app
```

Or:

```bash
.venv/bin/python -m breath_midi.app
```

### Double-click (macOS)

Make `Start.command` executable once (`chmod +x Start.command`), then open it in Finder.

## Run — Viewer only

```bash
source .venv/bin/activate
python totem_ble_viewer.py
```

## Using TOTEM with this project

### Bluetooth

- In **Input**, choose **ble**, **Scan**, pick a device, **Connect** (or rely on `config.toml` `ble_auto_connect` / `ble_address` when using the controller).
- Enable **BLE Breath Streaming** in the TOTEM app; Bluetooth on the Mac must be on.

### OSC

- In **Input**, set **osc**, **OSC port** (default **8000**), optionally **Source filter** (`all` or a device UUID).
- Use **Listen (OSC)** / **Stop OSC** as needed; point the iPhone app to this Mac’s **LAN IP** and the same port (**not** `127.0.0.1` on the phone).
- Phone and Mac should be on the same Wi‑Fi.

## Features (Breath → MIDI)

- Live **processed** breath trace (about **15 seconds**) in the left panel.
- Connection status and **RX rate** in the live monitor.
- **MIDI** output via **mido** / **python-rtmidi**; refresh MIDI ports from the **MIDI** tab.
- **Auto-save** writes `config.toml` when you change parameters (toggle in the toolbar).

## BLE protocol (TOTEM breath characteristic)

- **Service UUID:** `E4BE43E9-BFC5-49BE-B072-3622A0CE8410`
- **Breath characteristic UUID:** `2C9E2E89-C488-4B7E-A6AB-5C37A99916DB`

Each notification is **28 bytes**:

| Offset | Size | Type | Description |
|--------|------|------|-------------|
| 0 | 16 | bytes | Device UUID (raw) |
| 16 | 8 | Float64 BE | Timestamp (session-relative) |
| 24 | 4 | Float32 BE | Breath value (0.0–1.0) |

## OSC protocol

UDP packets with OSC messages:

- **Address:** `/breath_value/<device-uuid>`
- **Arguments:** one float, breath value **0.0–1.0**

## Dependencies (`requirements.txt`)

| Package | Purpose |
|---------|---------|
| `bleak` | BLE (CoreBluetooth on macOS) |
| `dearpygui` | UI and real-time plot |
| `mido` | MIDI message helpers |
| `python-rtmidi` | MIDI I/O |
| `tomli-w` | Write `config.toml` |
