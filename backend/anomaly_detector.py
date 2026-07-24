"""
Deterministic signal processing layer — no LLM.
Performs z-score, slew rate, FFT, and cross-signal plausibility analysis.
"""
from __future__ import annotations

import json
import math
import statistics
from typing import Any


# ──────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────

ZSCORE_WINDOW       = 30     # rolling window size for mean/std
ZSCORE_THRESHOLD    = 3.0    # z-score above this → anomaly
SLEW_WINDOW         = 5      # points for rolling slew rate
FLATLINE_WINDOW     = 15     # consecutive identical values → flatline
FLATLINE_TOLERANCE  = 0.001  # absolute delta for "same value"
FFT_NOISE_THRESHOLD = 0.25   # normalised high-frequency energy fraction

SIGNAL_NORMAL_RANGES = {
    "rpm":         (650,  6500),
    "ect":         (20,   120),
    "maf":         (2.0,  220),
    "o2_voltage":  (0.0,  1.0),
    "ltft":        (-25,  25),
    "tps":         (0,    100),
    "can_health":  (0,    1),
    "batt_voltage":(10.0, 15.5),
}

SIGNALS_TO_ANALYSE = list(SIGNAL_NORMAL_RANGES.keys())


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def _extract_series(logs: list[dict], signal: str) -> list[float]:
    return [float(e.get(signal, 0)) for e in logs]


def _rolling_mean_std(series: list[float], window: int) -> list[tuple[float, float]]:
    """Return list of (mean, std) tuples using a causal rolling window."""
    result = []
    for i, _ in enumerate(series):
        w = series[max(0, i - window + 1): i + 1]
        m = statistics.mean(w)
        s = statistics.pstdev(w) if len(w) > 1 else 0.0
        result.append((m, s))
    return result


def _zscore_anomalies(series: list[float], timestamps: list[str],
                      signal: str) -> list[dict]:
    stats   = _rolling_mean_std(series, ZSCORE_WINDOW)
    events  = []
    in_anom = False
    start_i = 0
    for i, (val, (mean, std)) in enumerate(zip(series, stats)):
        z = abs(val - mean) / std if std > 0 else 0.0
        if z > ZSCORE_THRESHOLD and not in_anom:
            in_anom = True
            start_i = i
        elif z <= ZSCORE_THRESHOLD and in_anom:
            duration = i - start_i
            if duration >= 2:
                events.append({
                    "anomaly_type": "z_score_deviation",
                    "first_detected_timestamp": timestamps[start_i],
                    "end_timestamp": timestamps[i],
                    "duration_sec": duration,
                    "severity_score": min(1.0, round(z / 10.0, 3)),
                    "detail": f"z={z:.2f} at sample {i}",
                })
            in_anom = False
    if in_anom:
        duration = len(series) - start_i
        events.append({
            "anomaly_type": "z_score_deviation",
            "first_detected_timestamp": timestamps[start_i],
            "end_timestamp": timestamps[-1],
            "duration_sec": duration,
            "severity_score": 0.8,
            "detail": "Ongoing at end of log",
        })
    return events


def _slew_rate_anomalies(series: list[float], timestamps: list[str],
                         signal: str) -> list[dict]:
    """
    Detect abrupt jumps (high slew rate) vs. gradual drift.
    Returns both 'abrupt_jump' and 'gradual_drift' anomaly types.
    """
    if len(series) < SLEW_WINDOW + 1:
        return []

    rng = SIGNAL_NORMAL_RANGES.get(signal, (0, 1))
    signal_range = max(rng[1] - rng[0], 1e-6)
    events = []

    # Compute per-sample slew rate (normalised)
    slew_rates = []
    for i in range(1, len(series)):
        raw = abs(series[i] - series[i - 1]) / signal_range
        slew_rates.append(raw)

    # Abrupt jump: single-sample normalised slew > 0.10 (10% of range)
    ABRUPT_THRESHOLD = 0.10
    for i, sr in enumerate(slew_rates):
        if sr > ABRUPT_THRESHOLD:
            events.append({
                "anomaly_type": "abrupt_jump",
                "first_detected_timestamp": timestamps[i],
                "end_timestamp": timestamps[i + 1],
                "duration_sec": 1,
                "severity_score": min(1.0, round(sr / 0.30, 3)),
                "detail": f"Normalised slew rate {sr:.4f} at sample {i+1}",
            })

    # Gradual drift: compare first 10% vs last 10% of series
    n = len(series)
    q = max(5, n // 10)
    early_mean = statistics.mean(series[:q])
    late_mean  = statistics.mean(series[-q:])
    drift_pct  = abs(late_mean - early_mean) / max(abs(early_mean), 1e-6) * 100
    if drift_pct > 8.0:
        severity = min(1.0, drift_pct / 30.0)
        events.append({
            "anomaly_type": "gradual_drift",
            "first_detected_timestamp": timestamps[0],
            "end_timestamp": timestamps[-1],
            "duration_sec": n,
            "severity_score": round(severity, 3),
            "detail": f"Drift of {drift_pct:.1f}% from early mean {early_mean:.3f} to late mean {late_mean:.3f}",
        })
    return events


def _flatline_detection(series: list[float], timestamps: list[str],
                         signal: str) -> list[dict]:
    events  = []
    count   = 1
    start_i = 0
    for i in range(1, len(series)):
        if abs(series[i] - series[i - 1]) < FLATLINE_TOLERANCE:
            if count == 1:
                start_i = i - 1
            count += 1
        else:
            if count >= FLATLINE_WINDOW:
                events.append({
                    "anomaly_type": "flatline_open_circuit",
                    "first_detected_timestamp": timestamps[start_i],
                    "end_timestamp": timestamps[i - 1],
                    "duration_sec": count,
                    "severity_score": min(1.0, count / len(series)),
                    "detail": f"Signal pinned at {series[start_i]:.4f} for {count} samples",
                })
            count = 1
    if count >= FLATLINE_WINDOW:
        events.append({
            "anomaly_type": "flatline_open_circuit",
            "first_detected_timestamp": timestamps[start_i],
            "end_timestamp": timestamps[-1],
            "duration_sec": count,
            "severity_score": min(1.0, count / len(series)),
            "detail": f"Signal pinned at {series[start_i]:.4f} for {count} samples (until end)",
        })
    return events


def _fft_noise_analysis(series: list[float], timestamps: list[str],
                         signal: str) -> list[dict]:
    """
    Simple DFT-based noise detection.
    High-frequency energy fraction > threshold → EMI / noise anomaly.
    """
    n = len(series)
    if n < 16:
        return []

    mean = statistics.mean(series)
    demeaned = [x - mean for x in series]

    # Compute DFT magnitudes manually (avoid numpy dependency for portability)
    half = n // 2
    magnitudes = []
    for k in range(half):
        re = sum(demeaned[j] * math.cos(2 * math.pi * k * j / n) for j in range(n))
        im = sum(demeaned[j] * math.sin(2 * math.pi * k * j / n) for j in range(n))
        magnitudes.append(math.sqrt(re * re + im * im))

    total_energy = sum(m * m for m in magnitudes) or 1e-9
    # High-frequency = top 40% of frequency bins
    hf_start      = int(half * 0.60)
    hf_energy     = sum(m * m for m in magnitudes[hf_start:])
    hf_fraction   = hf_energy / total_energy

    events = []
    if hf_fraction > FFT_NOISE_THRESHOLD:
        events.append({
            "anomaly_type": "emi_noise",
            "first_detected_timestamp": timestamps[0],
            "end_timestamp": timestamps[-1],
            "duration_sec": n,
            "severity_score": round(min(1.0, hf_fraction * 2), 3),
            "detail": f"High-frequency energy fraction {hf_fraction:.3f} (threshold {FFT_NOISE_THRESHOLD})",
        })
    return events


def _range_violations(series: list[float], timestamps: list[str],
                       signal: str) -> list[dict]:
    lo, hi = SIGNAL_NORMAL_RANGES.get(signal, (-1e9, 1e9))
    viol   = [(i, v) for i, v in enumerate(series) if v < lo or v > hi]
    if not viol:
        return []
    first_idx = viol[0][0]
    severity  = min(1.0, len(viol) / len(series) * 2)
    direction = "below_min" if viol[0][1] < lo else "above_max"
    return [{
        "anomaly_type": f"range_violation_{direction}",
        "first_detected_timestamp": timestamps[first_idx],
        "end_timestamp": timestamps[viol[-1][0]],
        "duration_sec": len(viol),
        "severity_score": round(severity, 3),
        "detail": f"{len(viol)} samples outside [{lo}, {hi}]; first value={viol[0][1]}",
    }]


def _cross_signal_plausibility(logs: list[dict]) -> list[dict]:
    """
    Check cross-signal invariants:
    - TPS increase should precede RPM increase within 3 seconds
    - If ECT < 60°C (cold), O2 sensor should be in open loop (LTFT frozen)
    - If batt_voltage < 11.0 V, expect can_health dropouts
    """
    events = []
    n = len(logs)
    timestamps = [e["timestamp"] for e in logs]

    # TPS → RPM latency check
    tps   = [e.get("tps", 0)   for e in logs]
    rpm   = [e.get("rpm", 0)   for e in logs]
    LATENCY_WINDOW = 3  # seconds (1 sample/sec assumed)
    violations = 0
    for i in range(LATENCY_WINDOW, n):
        tps_delta = tps[i] - tps[i - LATENCY_WINDOW]
        rpm_delta = rpm[i] - rpm[i - LATENCY_WINDOW]
        # Large RPM increase without preceding TPS increase
        if rpm_delta > 500 and tps_delta < 5:
            violations += 1

    if violations > n * 0.05:
        events.append({
            "anomaly_type": "cross_signal_tps_rpm_mismatch",
            "first_detected_timestamp": timestamps[LATENCY_WINDOW],
            "end_timestamp": timestamps[-1],
            "duration_sec": n,
            "severity_score": round(min(1.0, violations / n * 5), 3),
            "detail": f"TPS–RPM plausibility violations in {violations}/{n} samples",
        })

    # Battery voltage → CAN health correlation
    batt  = [e.get("batt_voltage", 13.8) for e in logs]
    can   = [e.get("can_health",   1)    for e in logs]
    low_v_windows = [i for i, v in enumerate(batt) if v < 11.0]
    can_drops     = [i for i, v in enumerate(can)  if v == 0]
    correlated    = len(set(low_v_windows) & set(can_drops))
    if low_v_windows and can_drops and correlated > len(low_v_windows) * 0.3:
        events.append({
            "anomaly_type": "cross_signal_voltage_can_correlation",
            "first_detected_timestamp": timestamps[low_v_windows[0]],
            "end_timestamp": timestamps[-1],
            "duration_sec": len(low_v_windows),
            "severity_score": 0.85,
            "detail": f"CAN bus dropouts correlated with low battery voltage events ({correlated} overlapping samples)",
        })

    # O2 sensor stuck check (no switching) in warm engine
    ect         = [e.get("ect", 90)        for e in logs]
    o2          = [e.get("o2_voltage", 0.5) for e in logs]
    warm_o2     = [o2[i] for i in range(n) if ect[i] > 70]
    if len(warm_o2) > 20:
        o2_range = max(warm_o2) - min(warm_o2)
        if o2_range < 0.15:    # switching should produce at least 0.6V swing
            events.append({
                "anomaly_type": "cross_signal_o2_not_switching",
                "first_detected_timestamp": timestamps[0],
                "end_timestamp": timestamps[-1],
                "duration_sec": len(warm_o2),
                "severity_score": 0.9,
                "detail": f"O2 sensor voltage range only {o2_range:.3f} V during warm operation (expect ≥0.6 V swing)",
            })
    return events


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

def analyze_logs(logs: list[dict]) -> dict:
    """
    Run the full anomaly detection suite over a list of log entries.
    Returns anomaly_report: {signal_name: [...anomalies...], cross_signal: [...]}
    """
    timestamps = [e["timestamp"] for e in logs]
    report: dict[str, Any] = {}

    for signal in SIGNALS_TO_ANALYSE:
        series   = _extract_series(logs, signal)
        anomalies: list[dict] = []

        anomalies.extend(_zscore_anomalies(series, timestamps, signal))
        anomalies.extend(_slew_rate_anomalies(series, timestamps, signal))
        anomalies.extend(_flatline_detection(series, timestamps, signal))
        anomalies.extend(_range_violations(series, timestamps, signal))

        if signal in ("o2_voltage", "maf", "batt_voltage"):
            anomalies.extend(_fft_noise_analysis(series, timestamps, signal))

        # Add signal_name to each entry
        for a in anomalies:
            a["signal_name"] = signal

        # Deduplicate / merge overlapping events by anomaly_type
        report[signal] = _merge_close_events(anomalies)

    report["cross_signal"] = _cross_signal_plausibility(logs)

    # Overall severity: max across all signals
    all_scores = [
        a["severity_score"]
        for sig_events in report.values()
        for a in (sig_events if isinstance(sig_events, list) else [])
    ]
    report["overall_severity"] = round(max(all_scores, default=0.0), 3)
    report["anomaly_count"]    = sum(
        len(v) for v in report.values()
        if isinstance(v, list)
    )
    return report


def _merge_close_events(events: list[dict]) -> list[dict]:
    """Keep the highest-severity instance when same anomaly_type appears >3 times."""
    by_type: dict[str, list[dict]] = {}
    for e in events:
        by_type.setdefault(e["anomaly_type"], []).append(e)

    merged = []
    for atype, group in by_type.items():
        if len(group) > 3:
            best = max(group, key=lambda x: x["severity_score"])
            best["detail"] += f" [merged {len(group)} events]"
            merged.append(best)
        else:
            merged.extend(group)
    return merged


def summarize_report(report: dict) -> list[dict]:
    """
    Return a flat list of the most significant anomalies across all signals,
    sorted by severity descending. Used by the correlation engine.
    """
    flat = []
    for sig, events in report.items():
        if not isinstance(events, list):
            continue
        flat.extend(events)
    flat.sort(key=lambda x: x.get("severity_score", 0), reverse=True)
    return flat


# ──────────────────────────────────────────────────────────────────
# CLI entry point for quick testing
# ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))

    scenario_dir = os.path.join(os.path.dirname(__file__), "data", "scenarios")
    files = [f for f in os.listdir(scenario_dir) if f.endswith(".json")]
    if not files:
        print("No scenario files found. Run synthetic_data_generator.py first.")
        sys.exit(1)

    # Pick first fault scenario
    fault_files = [f for f in files if "FAULT" in f]
    test_file   = os.path.join(scenario_dir, fault_files[0] if fault_files else files[0])

    with open(test_file) as fh:
        scenario = json.load(fh)

    print(f"Analysing scenario: {scenario['scenario_id']}")
    print(f"Ground truth: {scenario['ground_truth_cause']}")
    report = analyze_logs(scenario["logs"])
    print(f"\nAnomaly count: {report['anomaly_count']}  Overall severity: {report['overall_severity']}")
    flat = summarize_report(report)
    for a in flat[:8]:
        print(f"  [{a['severity_score']:.2f}] {a.get('signal_name','cross')} – {a['anomaly_type']}: {a['detail'][:80]}")
