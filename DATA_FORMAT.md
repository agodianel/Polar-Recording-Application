# PolarRecorder Data Format & Extraction Guide

This document explains exactly how the data from the Polar H10 is extracted, what each file contains, and which metrics are measured by the hardware versus calculated by our software.

## 📁 Output Structure

When you click "Start Recording", the application creates a new folder inside the `recordings/` directory based on the device MAC address and the exact timestamp.

Example session directory:
```text
recordings/Polar_H10_16E0A933_20260424_141011/
├── Polar_H10_16E0A933_20260424_141011_ECG.txt
├── Polar_H10_16E0A933_20260424_141011_ACC.txt
├── Polar_H10_16E0A933_20260424_141011_HR.txt
├── Polar_H10_16E0A933_20260424_141011_RR.txt
├── MARKER_20260424_141011.txt
└── session_metadata.json
```

All data files use a **semicolon-separated values (CSV)** format to maintain perfect compatibility with standard research tools and the Android Polar Sensor Logger app.

---

## 📊 File Breakdown

### 1. `..._ECG.txt` (Electrocardiogram)
**Source:** Raw hardware data from Polar H10 (130 Hz, 14-bit resolution).
*   **Phone timestamp:** The absolute wall-clock time the packet was received by the PC.
*   **sensor timestamp [ns]:** The high-precision nanosecond hardware clock from the H10 strap.
*   **timestamp [ms]:** Relative offset in milliseconds.
*   **ecg [uV]:** The raw electrical potential measured in microvolts.

### 2. `..._ACC.txt` (Accelerometer)
**Source:** Raw hardware data from Polar H10 (up to 200 Hz, 16-bit resolution).
*   **Phone timestamp:** PC wall-clock time.
*   **sensor timestamp [ns]:** High-precision hardware clock.
*   **X [mg], Y [mg], Z [mg]:** The acceleration forces along the 3 axes, measured in milli-g (where 1000 mg = 1G or 9.81 m/s²).

### 3. `..._RR.txt` (RR Intervals)
**Source:** Calculated directly on the Polar H10 hardware.
*   **Phone timestamp:** PC wall-clock time.
*   **RR-interval [ms]:** The exact time elapsed between two consecutive heartbeats (R-peaks in the ECG). This is an event-based stream (it only records a line when a heartbeat happens).

### 4. `..._HR.txt` (Heart Rate & HRV)
**Source:** A mix of hardware data and software calculations.
*   **Phone timestamp:** PC wall-clock time.
*   **HR [bpm]:** The Beats Per Minute calculated by the Polar H10 hardware.
*   **HRV [ms]:** **(Calculated by Software)** Heart Rate Variability. The Python app calculates the RMSSD (Root Mean Square of Successive Differences) over a rolling 30-beat window of RR intervals.
*   **Breathing interval [rpm]:** Intentionally left blank (e.g., `;;` in the CSV). Calculating this requires complex Digital Signal Processing (ECG-Derived Respiration) which the Polar SDK does not natively provide.

### 5. `MARKER_...txt`
**Source:** User input.
*   Records the exact timestamp and label of any markers you place during the recording session via the UI.

### 6. `session_metadata.json`
**Source:** Software generated.
*   A summary file containing the device firmware details, the exact sample rates configured (e.g., ACC set to 200Hz / 8G), total session duration, and the total sample counts for each data stream.

---

## ⚙️ Data Extraction Architecture

The data extraction relies on a combination of the `polar-python` library and custom asynchronous buffering:

1. **Bluetooth Streaming:** The Polar H10 utilizes a proprietary PMD (Polar Measurement Data) protocol. The app subscribes to the BLE "Control Point" and "Data" characteristics to request these specific streams.
2. **Asynchronous Handling:** Data packets arrive at high speeds (especially ACC at 200Hz). The app uses an asynchronous event loop (`qasync`) so that receiving Bluetooth data does not freeze the User Interface.
3. **Write Buffering:** To prevent the app from slowing down your hard drive, the `writer.py` module stores incoming data in memory. Every 1.0 seconds (by default), it flushes the entire buffer to the `.txt` files on your disk in one efficient operation.
4. **Synchronization:** Because the Bluetooth transmission takes time, the absolute `Phone timestamp` is recorded the moment the data arrives. For research-grade timing, you should rely on the `sensor timestamp [ns]` which is immune to Bluetooth lag.
