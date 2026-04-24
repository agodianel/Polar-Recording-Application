# PolarRecorder

**Professional-grade Polar H10 ECG band data acquisition & live visualization for PC.**

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey)

## Features

- **🔌 BLE Connection** — Auto-discover and connect to Polar H10 devices
- **⚡ ECG Recording** — 130 Hz, 14-bit, µV values
- **📐 Accelerometer** — 25/50/100/200 Hz, ±2/4/8G, 3-axis (mG)
- **❤️ Heart Rate & HRV** — Real-time BPM + RR intervals (ms) + **RMSSD HRV** calculation
- **📊 Live Visualization** — GPU-accelerated real-time charts (pyqtgraph)
- **🏷️ Markers** — Annotate events during recording sessions with one-click markers
- **📁 Compatible Output** — CSV format matching Polar Sensor Logger (Android) for research pipelines
- **📋 Session Metadata** — JSON file with device info, config, and statistics
- **🌙 Dark Theme** — Premium research-grade UI with responsive layout

## Requirements

- Python 3.10+
- Bluetooth Low Energy (BLE) adapter
- Polar H10 chest strap

## Installation

We recommend using [uv](https://github.com/astral-sh/uv) for fast dependency management:

```bash
# Clone the repository
git clone <repo-url>
cd PolarRecorder

# Install dependencies and run
uv run main.py
```

*Or using standard pip:*
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

## 🐧 Linux / BlueZ Requirements
The Polar H10 uses `indicate` properties. On Linux/BlueZ, **you must pair the device** before starting data streams to avoid connection hangs.
1. The app will attempt to auto-pair on the first connection.
2. If it fails, pair manually via `bluetoothctl`:
   ```bash
   bluetoothctl
   scan on
   pair <DEVICE_MAC>
   trust <DEVICE_MAC>
   ```

## 🪟 Windows Requirements
The application is fully compatible with Windows 10 and 11.
1. **Bluetooth Pairing:** When you click "Connect", Windows may show a notification: *"A device wants to pair"*. You **must** click this notification and allow pairing for the data streams (ECG/ACC) to work.
2. **Privacy Settings:** Ensure "Bluetooth" access is enabled in *Windows Settings > Privacy & Security*.

## Usage

1. **Scan** — Click "Scan for Devices" to discover your Polar H10
2. **Connect** — Select the device and click "Connect" (Accept any OS pairing prompts)
3. **Configure** — Enable/disable ECG, ACC, HR streams and set sample rates
4. **Record** — Click "Start Recording" to begin saving data to the `./recordings` folder
5. **Annotate** — Add markers during recording to flag events
6. **Stop** — Click "Stop Recording" to save and finalize the session

## Output Format

Output files are saved to the `recordings/` directory by default:

```
recordings/
└── Polar_H10_16E0A933_20260424_141011/
    ├── Polar_H10_16E0A933_20260424_141011_ECG.txt
    ├── Polar_H10_16E0A933_20260424_141011_ACC.txt
    ├── Polar_H10_16E0A933_20260424_141011_HR.txt
    ├── Polar_H10_16E0A933_20260424_141011_RR.txt
    ├── MARKER_20260424_141011.txt
    └── session_metadata.json
```

### File Formats

**ECG** (semicolon-separated):
```
Phone timestamp;sensor timestamp [ns];timestamp [ms];ecg [uV]
2026-04-24T14:10:15.270;599616050941733632;0.0;8575
```

**ACC** (semicolon-separated):
```
Phone timestamp;sensor timestamp [ns];X [mg];Y [mg];Z [mg]
2026-04-24T14:10:20.058;599616065136175104;-953;63;425
```

**HR** (semicolon-separated):
*Note: HRV column uses RMSSD calculated over a 30-beat rolling window.*
```
Phone timestamp;HR [bpm];HRV [ms];Breathing interval [rpm];
2026-04-24T14:10:16.752;64;42.5;;
```

**RR** (semicolon-separated):
```
Phone timestamp;RR-interval [ms]
2026-04-24T14:10:16.752;937
```

## Architecture

```
PolarRecorder/
├── main.py                    # Entry point
├── requirements.txt           # Dependencies
├── polar_recorder/
│   ├── app.py                 # QApplication + qasync setup
│   ├── ble/
│   │   ├── scanner.py         # Device discovery (bleak)
│   │   ├── device.py          # Connection & stream management (BleakClient injection)
│   │   └── data_models.py     # Data classes for stream data
│   ├── recording/
│   │   ├── session.py         # Recording session lifecycle & HRV calc
│   │   └── writer.py          # Buffered CSV file writers
│   └── ui/
│       ├── main_window.py     # Main window orchestration
│       ├── connection_panel.py # Device scanner & connection UI
│       ├── recording_panel.py  # Recording controls & stats
│       ├── live_charts.py     # Real-time charts (pyqtgraph)
│       └── styles.py          # Premium Dark Theme
└── recordings/                # Local data storage (Git ignored)
```

## Technology Stack

| Component | Library | Purpose |
|-----------|---------|---------|
| BLE | `polar-python` + `bleak` | Polar H10 BLE protocol |
| GUI | `PySide6` (Qt6) | Native desktop UI |
| Charts | `pyqtgraph` | GPU-accelerated real-time plotting |
| Async | `qasync` | Bridge asyncio ↔ Qt event loop |
| Data | `numpy` | High-performance HRV calculations |

## License

MIT License — See [LICENSE](LICENSE) for details.

## Acknowledgments

- [polar-python](https://github.com/zHElEARN/polar-python) — Polar BLE protocol library
- [bleak](https://github.com/hbldh/bleak) — Cross-platform BLE library
- [Polar BLE SDK](https://github.com/polarofficial/polar-ble-sdk) — Official Polar developer resources
