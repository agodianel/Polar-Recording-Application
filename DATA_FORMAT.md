# PolarRecorder Data Format & Extraction Guide

This document explains exactly how the data from the Polar H10 is extracted, what each file contains, and which metrics are measured by the hardware versus calculated by our software.

## 📁 Output Structure

When you click "Start recording", the application creates a new folder inside the `recordings/` directory (or the output folder you chose):

* If you entered a **session label** (e.g. `P01 - Seat Rest`), the folder is named after it. If that folder already exists, the start timestamp is appended (`P01 - Seat Rest_20260424_141011`) so no session is ever overwritten.
* Otherwise the folder is named `<model>_<device id>_<timestamp>`, where the device ID is the last part of the strap's Bluetooth name.

The data files inside always use the standard `<model>_<device id>_<timestamp>` names.

Example session directory:
```text
recordings/P01 - Seat Rest/
├── Polar_H10_16E0A933_20260424_141011_ECG.txt
├── Polar_H10_16E0A933_20260424_141011_ACC.txt
├── Polar_H10_16E0A933_20260424_141011_HR.txt
├── Polar_H10_16E0A933_20260424_141011_RR.txt
├── MARKER_20260424_141011.txt
└── session_metadata.json
```

All data files use a **semicolon-separated values (CSV)** format to maintain compatibility with standard research tools and the Android Polar Sensor Logger app.

Only the streams that actually started on the strap get a file; `session_metadata.json` records which ones those were.

---

## 📊 File Breakdown

### 1. `..._ECG.txt` (Electrocardiogram)
**Source:** Raw hardware data from Polar H10 (130 Hz, 14-bit resolution).
*   **Phone timestamp:** PC wall-clock time of the sample. The strap sends samples in packets of ~73; the packet's arrival time is assigned to its last sample, and earlier samples are spaced backwards at the sample interval.
*   **sensor timestamp [ns]:** The strap's high-precision clock, one value per sample (see *Synchronization* below).
*   **timestamp [ms]:** Time since the first ECG sample of the session, derived from the sensor timestamps.
*   **ecg [uV]:** The raw electrical potential measured in microvolts.

### 2. `..._ACC.txt` (Accelerometer)
**Source:** Raw hardware data from Polar H10 (25/50/100/200 Hz, 16-bit resolution, ±2/4/8 G).
*   **Phone timestamp:** PC wall-clock time of the sample, interpolated within each packet like ECG.
*   **sensor timestamp [ns]:** The strap's clock, one value per sample.
*   **X [mg], Y [mg], Z [mg]:** The acceleration forces along the 3 axes, measured in milli-g (where 1000 mg = 1G or 9.81 m/s²).

### 3. `..._RR.txt` (RR Intervals)
**Source:** Calculated directly on the Polar H10 hardware.
*   **Phone timestamp:** PC wall-clock time the heart rate notification carrying this interval arrived (one notification can carry several intervals).
*   **RR-interval [ms]:** The time elapsed between two consecutive heartbeats (R-peaks in the ECG), rounded to the nearest millisecond. The strap measures it in 1/1024 s units. This is an event-based stream: a line is only written when a heartbeat happens.

### 4. `..._HR.txt` (Heart Rate & HRV)
**Source:** A mix of hardware data and software calculations.
*   **Phone timestamp:** PC wall-clock time.
*   **HR [bpm]:** The Beats Per Minute calculated by the Polar H10 hardware.
*   **HRV [ms]:** **(Calculated by Software)** Heart Rate Variability. The Python app calculates the RMSSD (Root Mean Square of Successive Differences) over a rolling 30-beat window of RR intervals. Empty until two intervals have been received.
*   **Breathing interval [rpm]:** Intentionally left blank (e.g., `;;` in the CSV). Calculating this requires complex Digital Signal Processing (ECG-Derived Respiration) which the Polar SDK does not natively provide.

### 5. `MARKER_...txt`
**Source:** User input (and the app, on connection loss).
*   **Phone timestamp:** PC wall-clock time the marker was placed.
*   **Marker start/stop:** The marker type followed by a space and the optional label:
    *   `MARKER_START` / `MARKER_STOP` — start and end of a segment (the "Start segment" / "End segment" button), same as the Android app.
    *   `MARKER_EVENT` — a single event ("Add marker").
    *   `MARKER_EVENT connection lost` — written automatically if the strap disconnected during the recording.

### 6. `session_metadata.json`
**Source:** Software generated. Written when the recording starts and updated when it stops, so even an interrupted session documents its configuration.
*   `label` — the session label, if any.
*   `device` — name, Bluetooth address, model, device ID and battery level at the start.
*   `session` — start and end time, duration, and `end_reason`: `user` (stopped normally), `disconnected` (user disconnected while recording), `connection_lost`, `write_error` (disk full or not writable) or `app_closed`. `end` is `null` if the app crashed.
*   `streams` — the configuration of the streams that actually ran (e.g. ACC 200 Hz / ±8 G) and their total sample counts.
*   `markers` — every marker with its timestamp, type and label.

---

## ⚙️ Data Extraction Architecture

The data extraction relies on a combination of the `polar-python` library and custom asynchronous buffering:

1. **Bluetooth Streaming:** The Polar H10 utilizes a proprietary PMD (Polar Measurement Data) protocol. The app subscribes to the BLE "Control Point" and "Data" characteristics to request these specific streams, and checks the strap's response to each request. A stream the strap rejects (or doesn't answer within 10 s) is reported in the Log and left out of the recording.
2. **Asynchronous Handling:** Data packets arrive at high speeds (especially ACC at 200Hz). The app uses an asynchronous event loop (`qasync`) so that receiving Bluetooth data does not freeze the User Interface.
3. **Write Buffering:** To keep disk writes efficient, the `writer.py` module buffers incoming rows in memory and writes them out every 1.0 seconds (or every 100 rows, whichever comes first). Markers are written to disk immediately. If the app crashes, at most about one second of data is lost.
4. **Synchronization:** Because the Bluetooth transmission takes time, the absolute `Phone timestamp` reflects when data arrived at the PC (with the per-packet interpolation described above). For research-grade timing, rely on the `sensor timestamp [ns]`, which is immune to Bluetooth lag:
    *   The strap stamps each packet with the time of its **last** sample (the Polar BLE SDK convention); the app derives the earlier samples' timestamps backwards from it.
    *   The sample spacing is measured from the gap between consecutive packets, so it follows the strap's real clock (e.g. ~130.2 Hz rather than exactly 130 Hz). It falls back to the nominal rate for the first packet and after a dropped packet.
    *   ECG and ACC use the same convention, so their sensor timestamps can be aligned directly.
    *   The H10 clock is not set to real time; it typically reads a date around 2019. Use sensor timestamps for *relative* timing between samples and streams, and the phone timestamp for wall-clock time.
