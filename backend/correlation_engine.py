"""
Correlation Engine — fuses DTC, anomaly_report, digital_twin deviation,
co-occurring DTC patterns, and KB validation thresholds into a single
fault_signature_vector that all agents downstream consume.
"""
from __future__ import annotations

import json
import os
import statistics
from typing import Any


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def _load_kb(kb_path: str | None = None) -> dict:
    if kb_path is None:
        kb_path = os.path.join(os.path.dirname(__file__), "knowledge_base.json")
    with open(kb_path) as fh:
        return json.load(fh)


def _kb_entry(kb: dict, dtc: str) -> dict | None:
    return kb.get("dtc_entries", {}).get(dtc)


def _derive_timing_pattern(anomaly_report: dict) -> str:
    """
    Classify timing pattern from anomaly types:
    gradual → at least one 'gradual_drift'
    abrupt  → 'flatline' or 'abrupt_jump' without drift
    intermittent → 'flatline_open_circuit' with short duration OR dropout events
    multi-system → anomalies across ≥3 different signals
    """
    all_anomalies = [
        a for sig, events in anomaly_report.items()
        if isinstance(events, list)
        for a in events
    ]

    types   = {a["anomaly_type"] for a in all_anomalies}
    signals = {a.get("signal_name", "cross") for a in all_anomalies
               if a.get("signal_name") not in (None, "cross_signal")}

    if len(signals) >= 3:
        return "multi-system"
    if "gradual_drift" in types:
        return "gradual"
    if "flatline_open_circuit" in types or "abrupt_jump" in types:
        # Check if there are also intermittent patterns
        if any("dropout" in t or "intermittent" in t for t in types):
            return "intermittent"
        return "abrupt"
    if any("dropout" in t or "intermittent" in t or "vibration" in t for t in types):
        return "intermittent"
    return "gradual"   # default for mild drift


def _compute_validation_deviation(logs: list[dict], kb_entry: dict | None) -> dict:
    """
    Compare actual signal stats against KB validation thresholds.
    Returns {signal: {threshold_breached, actual_value, threshold, deviation_pct}}.
    """
    if not kb_entry:
        return {}
    thresholds = kb_entry.get("validation_thresholds", {})
    result     = {}

    # LTFT check
    if "ltft_normal_range_pct" in thresholds and logs:
        ltft_vals = [e.get("ltft", 0) for e in logs if e.get("ltft") is not None]
        if ltft_vals:
            mean_ltft = statistics.mean(ltft_vals)
            lo, hi    = thresholds["ltft_normal_range_pct"]
            breached  = mean_ltft < lo or mean_ltft > hi
            result["ltft"] = {
                "threshold_breached": breached,
                "actual_value":       round(mean_ltft, 2),
                "threshold":          f"[{lo}%, {hi}%]",
                "deviation_pct":      round(max(0, mean_ltft - hi) or min(0, mean_ltft - lo), 2),
            }

    # MAF at idle check
    if "maf_at_idle_gs" in thresholds and logs:
        idle_logs = [e for e in logs if e.get("rpm", 0) < 1000]
        if idle_logs:
            maf_idle  = statistics.mean(e.get("maf", 0) for e in idle_logs)
            lo, hi    = thresholds["maf_at_idle_gs"]
            breached  = maf_idle < lo or maf_idle > hi
            result["maf_idle"] = {
                "threshold_breached": breached,
                "actual_value":       round(maf_idle, 2),
                "threshold":          f"[{lo}, {hi}] g/s",
                "deviation_pct":      round((maf_idle - (hi + lo) / 2) / ((hi + lo) / 2) * 100, 1),
            }

    # Battery voltage
    if "battery_voltage_operating_V" in thresholds and logs:
        batt_vals = [e.get("batt_voltage", 13.8) for e in logs]
        min_batt  = min(batt_vals)
        lo, hi    = thresholds["battery_voltage_operating_V"]
        breached  = min_batt < lo
        result["batt_voltage"] = {
            "threshold_breached": breached,
            "actual_value":       round(min_batt, 2),
            "threshold":          f"≥{lo} V",
            "deviation_pct":      round((lo - min_batt) / lo * 100, 1) if breached else 0.0,
        }

    # CAN health dropout
    if logs:
        can_vals  = [e.get("can_health", 1) for e in logs]
        drop_pct  = can_vals.count(0) / len(can_vals) * 100
        if drop_pct > 0:
            result["can_health"] = {
                "threshold_breached": drop_pct > 5,
                "actual_value":       round(drop_pct, 1),
                "threshold":          "dropout_rate < 5%",
                "deviation_pct":      round(drop_pct, 1),
            }

    return result


def _co_occurring_dtcs(primary_dtcs: list[str],
                        kb: dict) -> list[dict]:
    """
    Look up fault_pattern_correlations in the KB to find related DTCs
    and interpret multi-DTC patterns.
    """
    correlations = kb.get("fault_pattern_correlations", {})
    co_occurring = []
    dtc_set      = set(primary_dtcs)

    for pattern_key, pattern_data in correlations.items():
        pattern_dtcs = set(pattern_key.split("+"))
        if pattern_dtcs.issubset(dtc_set) or (len(pattern_dtcs) > 1 and pattern_dtcs & dtc_set):
            co_occurring.append({
                "pattern":           pattern_key,
                "interpretation":    pattern_data.get("interpretation", ""),
                "priority_cause":    pattern_data.get("priority_cause", ""),
                "matched_dtcs":      list(pattern_dtcs & dtc_set),
            })
    return co_occurring


def _summarise_anomalies(anomaly_report: dict) -> list[dict]:
    """Return top anomalies sorted by severity for the fault_signature_vector."""
    flat = []
    for sig, events in anomaly_report.items():
        if not isinstance(events, list):
            continue
        for event in events:
            flat.append({
                "signal_name":    event.get("signal_name", sig),
                "anomaly_type":   event.get("anomaly_type", "unknown"),
                "severity_score": event.get("severity_score", 0),
                "duration_sec":   event.get("duration_sec", 0),
                "detail":         event.get("detail", ""),
                "first_detected": event.get("first_detected_timestamp", ""),
            })
    flat.sort(key=lambda x: x["severity_score"], reverse=True)
    return flat[:12]    # top 12 anomalies to avoid overwhelming agents


def _summarise_twin_deviation(twin_result: dict | None) -> dict:
    if not twin_result:
        return {}
    dev = twin_result.get("deviation", {})
    return {
        "most_deviated_signal": dev.get("most_deviated_signal", ""),
        "top_regions":          dev.get("deviation_regions", [])[:5],
        "signal_summary":       {
            sig: stats for sig, stats in dev.get("summary", {}).items()
            if stats.get("max_dev_pct", 0) > 10
        },
    }


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

def build_fault_signature_vector(
    dtcs:           list[str],
    logs:           list[dict],
    anomaly_report: dict,
    twin_result:    dict | None = None,
    freeze_frame:   dict | None = None,
    kb_path:        str  | None = None,
) -> dict[str, Any]:
    """
    Fuse all available evidence into a single fault_signature_vector.
    This is the structured input every LLM agent will reason over.
    """
    kb                  = _load_kb(kb_path)
    primary_dtc         = dtcs[0] if dtcs else ""
    kb_ent              = _kb_entry(kb, primary_dtc)
    timing_pattern      = _derive_timing_pattern(anomaly_report)
    validation_dev      = _compute_validation_deviation(logs, kb_ent)
    co_occurring        = _co_occurring_dtcs(dtcs, kb)
    anomaly_summary     = _summarise_anomalies(anomaly_report)
    twin_summary        = _summarise_twin_deviation(twin_result)

    # Compute overall anomaly severity
    all_severities = [a["severity_score"] for a in anomaly_summary]
    overall_sev    = round(max(all_severities, default=0.0), 3)

    # Which signals are anomalous
    affected_signals = list({
        a["signal_name"] for a in anomaly_summary
        if a["severity_score"] > 0.3 and a["signal_name"] not in ("", "cross_signal")
    })

    # Collect all anomaly types for pattern matching
    anomaly_types = list({a["anomaly_type"] for a in anomaly_summary})

    fsv: dict[str, Any] = {
        # ── Identity ──────────────────────────────────────────────
        "dtc":                   primary_dtc,
        "all_dtcs":              dtcs,
        "dtc_description":       kb_ent["description"] if kb_ent else "Unknown DTC",

        # ── Signal evidence ───────────────────────────────────────
        "anomalies":             anomaly_summary,
        "anomaly_types":         anomaly_types,
        "affected_signals":      affected_signals,
        "overall_severity":      overall_sev,

        # ── Pattern classification ────────────────────────────────
        "timing_pattern":        timing_pattern,   # gradual|abrupt|intermittent|multi-system

        # ── Co-occurring DTC interpretation ───────────────────────
        "co_occurring_dtcs":     co_occurring,

        # ── KB threshold checks ───────────────────────────────────
        "validation_deviation":  validation_dev,
        "validation_deviation_pct": round(
            max((v.get("deviation_pct", 0) for v in validation_dev.values()), default=0.0),
            2
        ),

        # ── Digital twin ──────────────────────────────────────────
        "digital_twin_deviation_summary": twin_summary,

        # ── Freeze frame ──────────────────────────────────────────
        "freeze_frame":          freeze_frame or {},

        # ── KB reference ──────────────────────────────────────────
        "kb_typical_causes":     (kb_ent or {}).get("typical_causes", []),
        "kb_priority_order":     (kb_ent or {}).get("diagnostic_priority_order", []),
        "kb_validation_thresholds": (kb_ent or {}).get("validation_thresholds", {}),
    }
    return fsv


# ──────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from anomaly_detector import analyze_logs
    from digital_twin    import run_digital_twin_analysis

    scenario_dir = os.path.join(os.path.dirname(__file__), "data", "scenarios")
    faults       = sorted(f for f in os.listdir(scenario_dir) if "FAULT" in f)
    if not faults:
        print("No fault scenarios found. Run synthetic_data_generator.py first.")
        sys.exit(1)

    with open(os.path.join(scenario_dir, faults[0])) as fh:
        scenario = json.load(fh)

    print(f"Scenario: {scenario['scenario_id']}")
    print(f"DTC     : {scenario['dtc']}")
    print(f"Truth   : {scenario['ground_truth_cause']}")

    anomaly_report = analyze_logs(scenario["logs"])
    twin_result    = run_digital_twin_analysis(scenario["logs"], scenario_dir)
    fsv = build_fault_signature_vector(
        dtcs           = scenario["dtc"],
        logs           = scenario["logs"],
        anomaly_report = anomaly_report,
        twin_result    = twin_result,
        freeze_frame   = scenario.get("freeze_frame"),
    )

    print(f"\nFault Signature Vector:")
    print(f"  timing_pattern      : {fsv['timing_pattern']}")
    print(f"  overall_severity    : {fsv['overall_severity']}")
    print(f"  affected_signals    : {fsv['affected_signals']}")
    print(f"  anomaly_types       : {fsv['anomaly_types']}")
    print(f"  co_occurring_dtcs   : {len(fsv['co_occurring_dtcs'])} pattern(s)")
    print(f"  validation_deviation: {fsv['validation_deviation_pct']}%")
    print(f"  digital_twin most deviated: {fsv['digital_twin_deviation_summary'].get('most_deviated_signal','—')}")
    print(f"\nTop anomalies:")
    for a in fsv["anomalies"][:5]:
        print(f"  [{a['severity_score']:.2f}] {a['signal_name']:14s} {a['anomaly_type']:30s} {a['detail'][:60]}")
