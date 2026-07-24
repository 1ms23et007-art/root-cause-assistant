"""
Predictive Drift Monitor — Innovation Feature 2.
Scans healthy-looking logs for slow drift trends that haven't yet crossed
the DTC threshold, and estimates time/mileage to failure.
"""
from __future__ import annotations

import json
import math
import os
import statistics
from datetime import datetime, timedelta
from typing import Any


# ──────────────────────────────────────────────────────────────────
# Signal drift monitoring configuration
# ──────────────────────────────────────────────────────────────────

DRIFT_MONITORS = [
    {
        "signal":           "ltft",
        "direction":        "abs_rising",       # |LTFT| trending upward
        "warning_threshold":  8.0,              # % – flag as drifting
        "fault_threshold":   10.0,              # % – where DTC P0171 fires
        "unit":             "%",
        "related_dtc":      "P0171",
        "description":      "Long-Term Fuel Trim positive bias (lean drift)",
    },
    {
        "signal":           "maf",
        "direction":        "ratio_falling",    # MAF/expected ratio drifting down
        "warning_threshold":  0.06,             # 6% under-read
        "fault_threshold":    0.12,             # 12% under-read
        "unit":             "g/s deviation",
        "related_dtc":      "P0171",
        "description":      "MAF sensor under-reporting drift (contamination)",
    },
    {
        "signal":           "batt_voltage",
        "direction":        "falling",
        "warning_threshold": 12.5,              # V – getting low
        "fault_threshold":   11.5,              # V – DTC P0562 threshold
        "unit":             "V",
        "related_dtc":      "P0562",
        "description":      "Battery/charging system voltage declining",
    },
    {
        "signal":           "o2_voltage",
        "direction":        "range_shrinking",  # switching amplitude shrinking
        "warning_threshold":  0.35,             # V swing – sensor aging
        "fault_threshold":    0.20,             # V swing – nearly stuck
        "unit":             "V swing",
        "related_dtc":      "P0171",
        "description":      "O2 sensor switching amplitude declining (sensor aging)",
    },
    {
        "signal":           "ect",
        "direction":        "rising",           # operating temp creeping up (thermostat)
        "warning_threshold": 100.0,             # °C – near overheat
        "fault_threshold":   110.0,             # °C
        "unit":             "°C",
        "related_dtc":      "P0300",
        "description":      "Engine operating temperature drifting high (thermostat sticking)",
    },
]

# Assume 1 sample per second, average speed ~50 km/h → 50/3600 km/sample
KM_PER_SAMPLE = 50 / 3600


# ──────────────────────────────────────────────────────────────────
# Per-signal metric extractors
# ──────────────────────────────────────────────────────────────────

def _extract_drift_metric(logs: list[dict], monitor: dict) -> list[float]:
    """Return the time series of the drifting metric (not the raw signal)."""
    sig = monitor["signal"]
    raw = [float(e.get(sig, 0)) for e in logs]

    if monitor["direction"] == "abs_rising":
        # |LTFT| running mean to smooth noise
        window = max(1, len(raw) // 10)
        return [abs(statistics.mean(raw[max(0, i - window + 1): i + 1]))
                for i in range(len(raw))]

    if monitor["direction"] == "ratio_falling":
        # Deviation ratio from a healthy baseline: assume idle MAF ~4.5 g/s
        # Use running deviation from first 10% median as baseline
        q = max(1, len(raw) // 10)
        baseline = statistics.median(raw[:q]) or 1.0
        return [abs(baseline - v) / baseline for v in raw]

    if monitor["direction"] == "range_shrinking":
        # Rolling peak-to-peak amplitude in a 20-sample window
        window = 20
        metrics = []
        for i in range(len(raw)):
            w = raw[max(0, i - window + 1): i + 1]
            metrics.append(max(w) - min(w))
        # For range_shrinking, lower = worse – invert logic
        return metrics  # compare against warning_threshold (min allowed)

    if monitor["direction"] in ("rising", "falling"):
        return raw

    return raw


def _compute_linear_drift_rate(metrics: list[float]) -> tuple[float, float]:
    """
    Fit a linear trend to the metric series.
    Returns (slope_per_sample, r_squared).
    """
    n = len(metrics)
    if n < 10:
        return 0.0, 0.0

    xs = list(range(n))
    xm = statistics.mean(xs)
    ym = statistics.mean(metrics)

    num = sum((xs[i] - xm) * (metrics[i] - ym) for i in range(n))
    den = sum((xs[i] - xm) ** 2 for i in range(n))
    slope = num / den if den != 0 else 0.0

    # R²
    ss_res = sum((metrics[i] - (ym + slope * (xs[i] - xm))) ** 2 for i in range(n))
    ss_tot = sum((m - ym) ** 2 for m in metrics) or 1e-9
    r2     = max(0.0, 1 - ss_res / ss_tot)

    return slope, r2


def _samples_to_threshold(current: float, slope: float,
                           threshold: float, direction: str,
                           is_range_shrinking: bool = False) -> int | None:
    """
    Given linear slope, estimate how many samples until threshold is breached.
    Returns None if no breach expected.
    """
    if abs(slope) < 1e-12:
        return None

    if is_range_shrinking:
        # Threshold = min allowed swing; breach when metric drops below threshold
        if slope >= 0:           # range is growing – not a threat
            return None
        if current <= threshold: # already below threshold
            return 0
        samples = (current - threshold) / abs(slope)
    elif direction in ("rising", "abs_rising", "ratio_falling"):
        if slope <= 0:
            return None
        if current >= threshold:
            return 0
        samples = (threshold - current) / slope
    else:  # falling
        if slope >= 0:
            return None
        if current <= threshold:
            return 0
        samples = (current - threshold) / abs(slope)

    return int(samples) if 0 < samples < 1e7 else None


def _is_healthy_looking(logs: list[dict]) -> bool:
    """
    Return True if there are no obvious DTC-level breaches in these logs
    (i.e., the log LOOKS healthy but may have slow drift).
    """
    ltft_vals = [abs(e.get("ltft", 0)) for e in logs]
    batt_vals = [e.get("batt_voltage", 13.8) for e in logs]
    maf_vals  = [e.get("maf", 4.5) for e in logs if e.get("rpm", 0) < 1000]

    if ltft_vals and max(ltft_vals) > 10:
        return False  # already at DTC threshold
    if batt_vals and min(batt_vals) < 11.5:
        return False
    return True


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

def scan_for_drift_warnings(logs: list[dict],
                             scenario_id: str = "unknown") -> list[dict]:
    """
    Scan a single log sequence for pre-failure drift warnings.
    Returns list of warning dicts.
    """
    if not _is_healthy_looking(logs):
        return []

    warnings = []
    n_samples = len(logs)
    if n_samples < 20:
        return []

    for monitor in DRIFT_MONITORS:
        metrics = _extract_drift_metric(logs, monitor)
        if not metrics:
            continue

        slope, r2 = _compute_linear_drift_rate(metrics)

        # Filter: only flag if R² > 0.25 (real trend, not random noise)
        if r2 < 0.20:
            continue

        is_shrink     = monitor["direction"] == "range_shrinking"
        current_val   = statistics.mean(metrics[-max(1, len(metrics) // 10):])
        warn_thresh   = monitor["warning_threshold"]
        fault_thresh  = monitor["fault_threshold"]

        # Determine if we're trending toward the warning zone
        direction     = monitor["direction"]
        approaching   = False
        if is_shrink:
            approaching = current_val > warn_thresh and slope < -1e-6
        elif direction in ("rising", "abs_rising", "ratio_falling"):
            approaching = current_val < fault_thresh and slope > 1e-6
        elif direction == "falling":
            approaching = current_val > fault_thresh and slope < -1e-6

        if not approaching:
            continue

        # Estimate samples to warning and fault threshold
        samples_to_warn  = _samples_to_threshold(current_val, slope, warn_thresh,
                                                  direction, is_shrink)
        samples_to_fault = _samples_to_threshold(current_val, slope, fault_thresh,
                                                  direction, is_shrink)

        # Convert samples → time (seconds) → km
        if samples_to_fault is not None:
            secs_to_fault = samples_to_fault
            km_to_fault   = round(secs_to_fault * KM_PER_SAMPLE, 1)
            hrs_to_fault  = round(secs_to_fault / 3600, 1)
        else:
            secs_to_fault = None
            km_to_fault   = None
            hrs_to_fault  = None

        # Severity: how far along from current toward fault threshold
        if is_shrink:
            progress = max(0.0, min(1.0, (warn_thresh - current_val) / max(warn_thresh - fault_thresh, 1e-6)))
        elif direction in ("rising", "abs_rising", "ratio_falling"):
            progress = max(0.0, min(1.0, current_val / max(fault_thresh, 1e-6)))
        else:
            progress = max(0.0, min(1.0, (warn_thresh - current_val) / max(warn_thresh - fault_thresh, 1e-6)))

        # Urgency classification
        if progress > 0.75 or (km_to_fault is not None and km_to_fault < 200):
            urgency = "high"
        elif progress > 0.45 or (km_to_fault is not None and km_to_fault < 800):
            urgency = "medium"
        else:
            urgency = "low"

        drift_rate_per_100km = round(slope / KM_PER_SAMPLE * 100, 4) if slope else 0.0

        warnings.append({
            "scenario_id":           scenario_id,
            "signal":                monitor["signal"],
            "description":           monitor["description"],
            "related_dtc":           monitor["related_dtc"],
            "current_value":         round(current_val, 4),
            "warning_threshold":     warn_thresh,
            "fault_threshold":       fault_thresh,
            "unit":                  monitor["unit"],
            "drift_slope_per_sample":round(slope, 6),
            "drift_rate_per_100km":  drift_rate_per_100km,
            "trend_r_squared":       round(r2, 3),
            "samples_to_fault":      samples_to_fault,
            "estimated_km_to_fault": km_to_fault,
            "estimated_hrs_to_fault":hrs_to_fault,
            "urgency":               urgency,
            "drift_progress_pct":    round(progress * 100, 1),
            "total_samples_analysed":n_samples,
        })

    # Sort by urgency then by proximity to fault threshold
    urgency_rank = {"high": 0, "medium": 1, "low": 2}
    warnings.sort(key=lambda w: (
        urgency_rank.get(w["urgency"], 9),
        w.get("samples_to_fault") or 1e9
    ))
    return warnings


def scan_all_scenarios(scenario_dir: str | None = None) -> list[dict]:
    """
    Scan all scenario JSON files in scenario_dir.
    Returns warnings from any scenario that looks healthy (pre-DTC drift).
    """
    if scenario_dir is None:
        scenario_dir = os.path.join(os.path.dirname(__file__), "data", "scenarios")
    if not os.path.isdir(scenario_dir):
        return []

    all_warnings = []
    for fname in sorted(os.listdir(scenario_dir)):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(scenario_dir, fname)) as fh:
            scenario = json.load(fh)
        warnings = scan_for_drift_warnings(
            scenario.get("logs", []),
            scenario_id=scenario.get("scenario_id", fname)
        )
        all_warnings.extend(warnings)

    all_warnings.sort(key=lambda w: (
        {"high": 0, "medium": 1, "low": 2}.get(w["urgency"], 9),
        w.get("samples_to_fault") or 1e9
    ))
    return all_warnings


# ──────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    scenario_dir = os.path.join(os.path.dirname(__file__), "data", "scenarios")
    print("Scanning all scenarios for pre-failure drift...\n")
    warnings = scan_all_scenarios(scenario_dir)
    if not warnings:
        print("No pre-failure drift detected across all scenarios.")
    else:
        print(f"Found {len(warnings)} drift warning(s):\n")
        for w in warnings[:10]:
            print(f"  [{w['urgency'].upper():6s}] {w['scenario_id']}")
            print(f"           Signal  : {w['signal']} ({w['unit']})")
            print(f"           Current : {w['current_value']}")
            print(f"           Threshold: {w['fault_threshold']}")
            print(f"           Est. km to fault: {w['estimated_km_to_fault']}")
            print(f"           Slope   : {w['drift_slope_per_sample']:.6f} per sample (R²={w['trend_r_squared']:.2f})")
            print()
