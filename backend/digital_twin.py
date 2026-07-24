"""
Digital Twin — Innovation Feature 1.
Given actual (faulty) waveform data, generate the expected healthy waveform
for the same driving conditions, then compute point-by-point deviation.
"""
from __future__ import annotations

import json
import math
import os
import statistics
from typing import Any


# ──────────────────────────────────────────────────────────────────
# Load healthy reference scenarios once at module import
# ──────────────────────────────────────────────────────────────────

_HEALTHY_REFS: list[dict] = []

def _load_healthy_refs(scenario_dir: str | None = None) -> list[dict]:
    global _HEALTHY_REFS
    if _HEALTHY_REFS:
        return _HEALTHY_REFS
    if scenario_dir is None:
        scenario_dir = os.path.join(os.path.dirname(__file__), "data", "scenarios")
    if not os.path.isdir(scenario_dir):
        return []
    refs = []
    for fname in os.listdir(scenario_dir):
        if fname.startswith("HEALTHY_") and fname.endswith(".json"):
            with open(os.path.join(scenario_dir, fname)) as fh:
                data = json.load(fh)
            if data.get("scenario_type") == "healthy":
                refs.append(data)
    _HEALTHY_REFS = refs
    return refs


# ──────────────────────────────────────────────────────────────────
# Reference model: interpolate expected signal value from healthy refs
# ──────────────────────────────────────────────────────────────────

SIGNALS = ["rpm", "ect", "maf", "o2_voltage", "ltft", "tps", "batt_voltage", "can_health"]


def _build_lookup_tables(refs: list[dict]) -> dict[str, list[tuple[float, float]]]:
    """
    Build per-signal lookup tables keyed by normalised time position (0–1).
    Returns {signal: [(time_frac, mean_value), ...]} at 100 interpolation points.
    """
    tables: dict[str, list[tuple[float, float]]] = {}
    POINTS = 100
    for signal in SIGNALS:
        col: list[list[float]] = [[] for _ in range(POINTS)]
        for ref in refs:
            logs = ref.get("logs", [])
            n    = len(logs)
            if n == 0:
                continue
            for i, entry in enumerate(logs):
                bucket = min(POINTS - 1, int(i / n * POINTS))
                col[bucket].append(float(entry.get(signal, 0)))
        tables[signal] = [
            (p / POINTS, statistics.mean(vals) if vals else 0.0)
            for p, vals in enumerate(col)
        ]
    return tables


def _interpolate(table: list[tuple[float, float]], t_frac: float) -> float:
    """Linear interpolation of a lookup table at position t_frac (0–1)."""
    if not table:
        return 0.0
    if t_frac <= table[0][0]:
        return table[0][1]
    if t_frac >= table[-1][0]:
        return table[-1][1]
    for i in range(len(table) - 1):
        t0, v0 = table[i]
        t1, v1 = table[i + 1]
        if t0 <= t_frac <= t1:
            alpha = (t_frac - t0) / max(t1 - t0, 1e-9)
            return v0 + alpha * (v1 - v0)
    return table[-1][1]


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

def build_expected_waveform(actual_logs: list[dict],
                             scenario_dir: str | None = None) -> list[dict]:
    """
    Generate the expected healthy waveform for the same drive cycle length.
    Returns list of dicts with {t, timestamp, signal_name: expected_value, ...}.
    """
    refs = _load_healthy_refs(scenario_dir)
    if not refs:
        # Fallback: use simple parametric healthy model
        return _parametric_healthy(actual_logs)

    tables = _build_lookup_tables(refs)
    n      = len(actual_logs)
    expected = []
    for i, actual_entry in enumerate(actual_logs):
        t_frac = i / max(n - 1, 1)
        entry  = {
            "t":         actual_entry["t"],
            "timestamp": actual_entry["timestamp"],
        }
        for signal in SIGNALS:
            entry[signal] = round(_interpolate(tables[signal], t_frac), 4)
        expected.append(entry)
    return expected


def _parametric_healthy(actual_logs: list[dict]) -> list[dict]:
    """Fallback parametric model when no healthy reference files are loaded."""
    n       = len(actual_logs)
    result  = []
    for i, entry in enumerate(actual_logs):
        phase  = i / max(n - 1, 1)
        rpm    = 800 + 2000 * math.sin(phase * math.pi)
        tps    = max(3, (rpm - 800) / 5700 * 70)
        result.append({
            "t":          entry["t"],
            "timestamp":  entry["timestamp"],
            "rpm":         round(rpm, 1),
            "ect":         round(22 + 68 * min(1, phase / 0.3) ** 0.6, 1),
            "maf":         round(2.5 + rpm / 6500 * 80, 2),
            "o2_voltage":  round(0.45 + 0.40 * math.sin(2 * math.pi * 0.5 * i), 3),
            "ltft":        1.5,
            "tps":         round(tps, 1),
            "batt_voltage":round(13.8 + (rpm - 800) / 5700 * 0.4, 2),
            "can_health":  1,
        })
    return result


def compute_deviation(actual_logs: list[dict],
                      expected_waveform: list[dict]) -> dict[str, Any]:
    """
    Compute per-sample, per-signal deviation between actual and expected.
    Also identifies contiguous deviation regions (start/end + magnitude).
    Returns:
      {
        per_sample: [{t, signal: {actual, expected, deviation_pct}, ...}],
        deviation_regions: [{signal, start_t, end_t, start_ts, end_ts, mean_deviation_pct}],
        summary: {signal: {max_dev_pct, mean_dev_pct, rms_deviation}}
      }
    """
    n          = min(len(actual_logs), len(expected_waveform))
    per_sample = []
    # Accumulate per-signal deviation lists
    signal_devs: dict[str, list[float]] = {s: [] for s in SIGNALS}

    for i in range(n):
        actual   = actual_logs[i]
        expected = expected_waveform[i]
        sample: dict[str, Any] = {
            "t":         actual["t"],
            "timestamp": actual["timestamp"],
        }
        for signal in SIGNALS:
            a_val = float(actual.get(signal, 0))
            e_val = float(expected.get(signal, 0))
            denom = max(abs(e_val), 1e-6)
            dev_pct = (a_val - e_val) / denom * 100
            sample[signal] = {
                "actual":       round(a_val, 4),
                "expected":     round(e_val, 4),
                "deviation_pct": round(dev_pct, 2),
            }
            signal_devs[signal].append(dev_pct)
        per_sample.append(sample)

    # Summary stats per signal
    summary: dict[str, dict] = {}
    for signal, devs in signal_devs.items():
        if devs:
            rms = math.sqrt(sum(d * d for d in devs) / len(devs))
            summary[signal] = {
                "max_dev_pct":  round(max(abs(d) for d in devs), 2),
                "mean_dev_pct": round(sum(devs) / len(devs), 2),
                "rms_deviation":round(rms, 2),
            }
        else:
            summary[signal] = {"max_dev_pct": 0, "mean_dev_pct": 0, "rms_deviation": 0}

    # Deviation regions: contiguous spans where |dev_pct| > 15% for any signal
    DEVIATION_THRESHOLD = 15.0
    regions = []
    for signal in SIGNALS:
        devs    = signal_devs[signal]
        in_reg  = False
        reg_start = 0
        reg_devs: list[float] = []
        for i, d in enumerate(devs):
            if abs(d) > DEVIATION_THRESHOLD:
                if not in_reg:
                    in_reg    = True
                    reg_start = i
                    reg_devs  = []
                reg_devs.append(d)
            else:
                if in_reg and len(reg_devs) >= 5:
                    regions.append({
                        "signal":           signal,
                        "start_t":          actual_logs[reg_start]["t"],
                        "end_t":            actual_logs[i - 1]["t"],
                        "start_ts":         actual_logs[reg_start]["timestamp"],
                        "end_ts":           actual_logs[i - 1]["timestamp"],
                        "mean_deviation_pct": round(sum(abs(x) for x in reg_devs) / len(reg_devs), 2),
                        "max_deviation_pct":  round(max(abs(x) for x in reg_devs), 2),
                    })
                in_reg   = False
                reg_devs = []
        if in_reg and len(reg_devs) >= 5:
            regions.append({
                "signal":           signal,
                "start_t":          actual_logs[reg_start]["t"],
                "end_t":            actual_logs[n - 1]["t"],
                "start_ts":         actual_logs[reg_start]["timestamp"],
                "end_ts":           actual_logs[n - 1]["timestamp"],
                "mean_deviation_pct": round(sum(abs(x) for x in reg_devs) / len(reg_devs), 2),
                "max_deviation_pct":  round(max(abs(x) for x in reg_devs), 2),
            })

    # Sort by mean deviation descending
    regions.sort(key=lambda x: x["mean_deviation_pct"], reverse=True)

    return {
        "per_sample":         per_sample,
        "deviation_regions":  regions,
        "summary":            summary,
        "most_deviated_signal": max(summary, key=lambda s: summary[s]["max_dev_pct"], default=""),
    }


def run_digital_twin_analysis(actual_logs: list[dict],
                               scenario_dir: str | None = None) -> dict[str, Any]:
    """
    Convenience wrapper: build expected waveform + compute deviation in one call.
    """
    expected  = build_expected_waveform(actual_logs, scenario_dir)
    deviation = compute_deviation(actual_logs, expected)
    return {
        "expected_waveform": expected,
        "deviation":         deviation,
    }


# ──────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    scenario_dir = os.path.join(os.path.dirname(__file__), "data", "scenarios")
    faults       = [f for f in os.listdir(scenario_dir) if "FAULT" in f]
    if not faults:
        print("No fault scenarios found.")
        sys.exit(1)

    with open(os.path.join(scenario_dir, faults[0])) as fh:
        scenario = json.load(fh)

    print(f"Running digital twin for: {scenario['scenario_id']}")
    result = run_digital_twin_analysis(scenario["logs"], scenario_dir)

    dev = result["deviation"]
    print(f"\nMost deviated signal: {dev['most_deviated_signal']}")
    print(f"Deviation regions: {len(dev['deviation_regions'])}")
    for r in dev["deviation_regions"][:5]:
        print(f"  {r['signal']:12s}  t={r['start_t']:3d}–{r['end_t']:3d}  "
              f"mean_dev={r['mean_deviation_pct']:.1f}%  max={r['max_deviation_pct']:.1f}%")
    print("\nSignal summary:")
    for sig, s in dev["summary"].items():
        if s["max_dev_pct"] > 5:
            print(f"  {sig:14s} max_dev={s['max_dev_pct']:6.1f}%  "
                  f"rms={s['rms_deviation']:6.1f}%")
