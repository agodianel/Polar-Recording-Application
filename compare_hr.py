"""Compare HR from Polar H10 firmware vs HR computed from ECG R-peak detection.

Uses Pan-Tompkins-inspired QRS detection for robust R-peak finding.
"""

import csv
import sys
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt, find_peaks


USAGE = "usage: python compare_hr.py <session folder>"


def read_ecg(path: Path):
    timestamps = []
    ecg = []
    with open(path) as f:
        reader = csv.reader(f, delimiter=";")
        next(reader)
        for row in reader:
            if len(row) < 4:
                continue
            ts_ns = int(row[1])
            ts_sec = ts_ns / 1e9
            uv = float(row[3])
            timestamps.append(ts_sec)
            ecg.append(uv)
    t = np.array(timestamps, dtype=np.float64)
    ecg = np.array(ecg, dtype=np.float64)
    t -= t[0]
    return t, ecg


def read_hr(path: Path):
    from datetime import datetime
    times = []
    hrs = []
    with open(path) as f:
        reader = csv.reader(f, delimiter=";")
        next(reader)
        for row in reader:
            if len(row) < 2:
                continue
            ts = datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%S.%f")
            hr = float(row[1])
            times.append(ts)
            hrs.append(hr)
    t0 = times[0]
    t_sec = np.array([(t - t0).total_seconds() for t in times], dtype=np.float64)
    return t_sec, np.array(hrs, dtype=np.float64)


def bandpass_filter(signal, fs, low=5.0, high=15.0, order=4):
    """Narrow bandpass for QRS enhancement (5-15 Hz typical for Pan-Tompkins)."""
    nyq = 0.5 * fs
    b, a = butter(order, [low / nyq, high / nyq], btype="band")
    return filtfilt(b, a, signal)


def detect_r_peaks(ecg, fs=130.0):
    """Pan-Tompkins inspired QRS detection."""
    # Bandpass filter 5-15 Hz
    filtered = bandpass_filter(ecg, fs, low=5.0, high=15.0)

    # Rectify
    rectified = np.abs(filtered)

    # Moving average integration window (~150ms)
    window = int(0.150 * fs)
    integrated = np.convolve(rectified, np.ones(window) / window, mode="same")

    # Find peaks on the integrated signal
    # Use a refractory period of 200ms (max HR ~300 BPM)
    min_distance = int(0.200 * fs)

    # Adaptive threshold: running estimate
    peaks, props = find_peaks(
        integrated,
        distance=min_distance,
        prominence=np.percentile(integrated, 80) * 0.3,
        height=np.percentile(integrated, 85),
    )

    return peaks, filtered, integrated


def compute_hr_from_rr(rr_intervals_s):
    return 60.0 / rr_intervals_s


def main():
    if len(sys.argv) != 2:
        sys.exit(USAGE)
    base = Path(sys.argv[1])
    ecg_path = list(base.glob("*_ECG.txt"))[0]
    hr_path = list(base.glob("*_HR.txt"))[0]

    print(f"ECG: {ecg_path}")
    print(f"HR:  {hr_path}")

    # ── Load data ──
    t_ecg, ecg_uv = read_ecg(ecg_path)
    t_hr, hr_firmware = read_hr(hr_path)

    # ── Exclude first 30s ──
    trim_start = 30.0
    ecg_mask = t_ecg >= trim_start
    t_ecg = t_ecg[ecg_mask] - trim_start
    ecg_uv = ecg_uv[ecg_mask]
    hr_mask = t_hr >= trim_start
    t_hr = t_hr[hr_mask] - trim_start
    hr_firmware = hr_firmware[hr_mask]

    fs = 130.0
    duration = t_ecg[-1]
    print(f"ECG duration (after excluding first 30s): {duration:.1f}s, samples: {len(ecg_uv)}")
    print(f"HR samples: {len(hr_firmware)}, range: {hr_firmware.min():.0f}-{hr_firmware.max():.0f} BPM")

    # ── R-peak detection ──
    peaks, filtered, integrated = detect_r_peaks(ecg_uv, fs=fs)
    peak_times = t_ecg[peaks]

    if len(peaks) < 3:
        print(f"Only {len(peaks)} R-peaks detected")
        return

    # ── Compute RR intervals and filter physiologically impossible outliers ──
    rr_intervals = np.diff(peak_times)

    # Physiological limits: 30-200 BPM → 300-2000ms RR
    valid_mask = (rr_intervals >= 0.3) & (rr_intervals <= 2.0)
    n_rejected = (~valid_mask).sum()
    rr_valid = rr_intervals[valid_mask]
    peak_times_valid = peak_times[1:][valid_mask]

    hr_ecg = compute_hr_from_rr(rr_valid)
    # 7-beat moving average; divide by the per-point window size so the
    # zero-padded edges don't drag the first/last values toward 0
    kernel = np.ones(7)
    hr_ecg_smooth = (np.convolve(hr_ecg, kernel, mode="same")
                     / np.convolve(np.ones_like(hr_ecg), kernel, mode="same"))

    # Interpolate Polar HR to ECG beat times for comparison
    hr_polar_at_ecg = np.interp(peak_times_valid, t_hr, hr_firmware)

    print(f"\nR-peaks detected: {len(peaks)}")
    print(f"  Rejected RR outliers: {n_rejected}")
    print(f"  Valid beats for HR: {len(rr_valid)}")
    print(f"  Mean RR: {rr_valid.mean() * 1000:.1f} ms "
          f"(SD: {rr_valid.std() * 1000:.1f} ms)")
    print(f"\nHR from ECG:  {hr_ecg.mean():.1f} ± {hr_ecg.std():.1f} BPM "
          f"(range {hr_ecg.min():.0f}-{hr_ecg.max():.0f})")
    print(f"HR from Polar: {hr_firmware.mean():.1f} ± {hr_firmware.std():.1f} BPM "
          f"(range {hr_firmware.min():.0f}-{hr_firmware.max():.0f})")

    bias = hr_ecg.mean() - hr_firmware.mean()
    diffs = hr_ecg - hr_polar_at_ecg
    rmse = np.sqrt(np.mean(diffs ** 2))
    mae = np.mean(np.abs(diffs))
    print(f"\nECG vs Polar:")
    print(f"  Mean bias: {bias:+.2f} BPM")
    print(f"  RMSE: {rmse:.2f} BPM")
    print(f"  MAE:  {mae:.2f} BPM")

    # ── Bland-Altman ──
    mean_hr = (hr_ecg + hr_polar_at_ecg) / 2
    diff_hr = hr_ecg - hr_polar_at_ecg
    loa_upper = bias + 1.96 * diffs.std()
    loa_lower = bias - 1.96 * diffs.std()
    print(f"  Bland-Altman 95% LoA: [{loa_lower:.1f}, {loa_upper:.1f}] BPM")

    # ── Plot ──
    # Only the two zoomed ECG panels share a time axis; the HR panel spans the
    # whole session and the Bland-Altman x-axis is BPM, not time.
    fig, axes = plt.subplots(4, 1, figsize=(14, 12),
                             gridspec_kw={"height_ratios": [2, 1, 2, 2]})

    # 1: Full raw ECG with R-peaks (zoomed)
    ax = axes[0]
    # Show a clean 10-second window for readability, at full resolution
    # (only ~1300 samples, so no subsampling — that would cut through the QRS peaks)
    zoom_end = 10.0
    zm = t_ecg < zoom_end
    ax.plot(t_ecg[zm], ecg_uv[zm], color="#555", lw=0.6)
    pk = peaks[t_ecg[peaks] < zoom_end]
    ax.scatter(t_ecg[pk], ecg_uv[pk], color="red", s=30, zorder=5)
    ax.set_ylabel("ECG (µV)")
    ax.set_title(f"ECG with detected R-peaks ({len(peaks)} total)")
    ax.set_xlim(0, zoom_end)
    ax.grid(True, alpha=0.3)

    # 2: Full filtered + integrated (10s zoom)
    ax = axes[1]
    ax.sharex(axes[0])
    ax.plot(t_ecg[zm], filtered[zm], color="steelblue", lw=0.6, label="Filtered (5-15 Hz)")
    ax.plot(t_ecg[zm], integrated[zm], color="orange", lw=0.8, label="Integrated (150ms MA)")
    ax.scatter(t_ecg[pk], filtered[pk], color="red", s=30, zorder=5)
    ax.set_ylabel("Amplitude")
    ax.legend(fontsize=8)
    ax.set_title("Bandpass-filtered ECG + moving-window integration")
    ax.grid(True, alpha=0.3)

    # 3: Full HR comparison
    ax = axes[2]
    ax.plot(t_hr, hr_firmware, "o-", color="C0", lw=1.2, ms=3,
            label=f"Polar H10 firmware")
    ax.plot(peak_times_valid, hr_ecg, ".", color="C1", ms=3, alpha=0.4)
    ax.plot(peak_times_valid, hr_ecg_smooth, "-", color="C1", lw=1.5,
            label="ECG R-peak HR")
    ax.set_ylabel("Heart Rate (BPM)")
    ax.legend(fontsize=9)
    ax.set_title("Heart Rate: Polar H10 firmware vs ECG R-peak detection")
    ax.set_xlabel("Time (s)")
    ax.grid(True, alpha=0.3)

    stats = (
        f"ECG:  {hr_ecg.mean():.1f} ± {hr_ecg.std():.1f} BPM\n"
        f"Polar: {hr_firmware.mean():.1f} ± {hr_firmware.std():.1f} BPM\n"
        f"Bias: {bias:+.1f} BPM    RMSE: {rmse:.1f} BPM\n"
        f"R-peaks: {len(peaks)}    RR outliers: {n_rejected}"
    )
    ax.text(0.98, 0.02, stats, transform=ax.transAxes,
            fontsize=8, va="bottom", ha="right",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.9))

    # 4: Bland-Altman plot
    ax = axes[3]
    ax.scatter(mean_hr, diff_hr, s=8, alpha=0.5, color="C1")
    ax.axhline(bias, color="darkred", ls="--", lw=1, label=f"Bias: {bias:+.1f} BPM")
    ax.axhline(loa_upper, color="darkred", ls=":", lw=1,
               label=f"LoA: [{loa_lower:.1f}, {loa_upper:.1f}]")
    ax.axhline(loa_lower, color="darkred", ls=":", lw=1)
    ax.set_xlabel("Mean HR of both methods (BPM)")
    ax.set_ylabel("ECG HR - Polar HR (BPM)")
    ax.legend(fontsize=8)
    ax.set_title("Bland-Altman: ECG R-peak vs Polar H10 firmware")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    out_path = base / "hr_comparison.png"
    fig.savefig(out_path, dpi=150)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
