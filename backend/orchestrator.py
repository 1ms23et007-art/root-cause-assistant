"""
Orchestrator — runs the full 4-agent diagnostic pipeline.
Pipeline: correlation_engine → Agent 1 → Agent 2 → Agent 3 (parallel if drift warnings)
Logs each stage clearly for demo explainability.
"""
from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from anomaly_detector          import analyze_logs, summarize_report
from digital_twin              import run_digital_twin_analysis
from correlation_engine        import build_fault_signature_vector
from predictive_drift_monitor  import scan_for_drift_warnings
from agent_root_cause_reasoning import analyze_root_cause
from agent_fix_guide           import generate_fix_guide
from agent_predictive_alert    import generate_predictive_alerts
from agent_feedback_calibration import process_feedback

# ──────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s  [%(levelname)s]  %(name)s — %(message)s",
    datefmt= "%H:%M:%S",
)
logger = logging.getLogger("orchestrator")


def _load_kb(kb_path: str | None = None) -> dict:
    if kb_path is None:
        kb_path = os.path.join(os.path.dirname(__file__), "knowledge_base.json")
    with open(kb_path) as fh:
        return json.load(fh)


def _kb_entry(kb: dict, dtc: str) -> dict | None:
    return kb.get("dtc_entries", {}).get(dtc)


# ──────────────────────────────────────────────────────────────────
# Stage runners
# ──────────────────────────────────────────────────────────────────

def _stage_anomaly_detection(logs: list[dict]) -> dict:
    logger.info("STAGE 1 ▶ Anomaly Detection (z-score / slew / FFT / cross-signal)")
    t0     = time.time()
    report = analyze_logs(logs)
    elapsed= round(time.time() - t0, 2)
    logger.info(f"         ✓ {report['anomaly_count']} anomalies found  "
                f"(overall severity {report['overall_severity']:.3f})  [{elapsed}s]")
    return report


def _stage_digital_twin(logs: list[dict], scenario_dir: str) -> dict:
    logger.info("STAGE 2 ▶ Digital Twin — computing expected waveform & deviation")
    t0     = time.time()
    result = run_digital_twin_analysis(logs, scenario_dir)
    elapsed= round(time.time() - t0, 2)
    dev    = result.get("deviation", {})
    top    = dev.get("most_deviated_signal", "—")
    regions= len(dev.get("deviation_regions", []))
    logger.info(f"         ✓ Most deviated signal: {top}  |  Deviation regions: {regions}  [{elapsed}s]")
    return result


def _stage_correlation(dtcs: list[str], logs: list[dict],
                        anomaly_report: dict, twin_result: dict,
                        freeze_frame: dict | None, kb_path: str) -> dict:
    logger.info("STAGE 3 ▶ Correlation Engine — building fault_signature_vector")
    t0  = time.time()
    fsv = build_fault_signature_vector(
        dtcs=dtcs, logs=logs, anomaly_report=anomaly_report,
        twin_result=twin_result, freeze_frame=freeze_frame, kb_path=kb_path,
    )
    elapsed = round(time.time() - t0, 2)
    logger.info(f"         ✓ timing_pattern={fsv['timing_pattern']}  "
                f"severity={fsv['overall_severity']}  "
                f"signals={fsv['affected_signals']}  [{elapsed}s]")
    return fsv


def _stage_agent1(fsv: dict) -> dict:
    logger.info("STAGE 4 ▶ Agent 1 — Root Cause Reasoning (LLM)")
    t0     = time.time()
    result = analyze_root_cause(fsv)
    elapsed= round(time.time() - t0, 2)
    causes = result.get("ranked_causes", [])
    top    = causes[0] if causes else {}
    logger.info(f"         ✓ Top cause: '{top.get('cause','?')}' "
                f"({top.get('confidence_score',0)}% confidence)  [{elapsed}s]")
    return result


def _stage_agent2(rc_result: dict, fsv: dict, kb_entry: dict | None) -> dict:
    logger.info("STAGE 5 ▶ Agent 2 — Fix Guide Generation (LLM)")
    t0     = time.time()
    result = generate_fix_guide(rc_result, fsv, kb_entry)
    elapsed= round(time.time() - t0, 2)
    steps  = len(result.get("steps", []))
    logger.info(f"         ✓ {steps} repair steps  "
                f"({result.get('estimated_total_time_hr','?')} hr est.)  [{elapsed}s]")
    return result


def _stage_predictive_scan(logs: list[dict], scenario_id: str) -> list[dict]:
    logger.info("STAGE 6a ▶ Predictive Drift Monitor — scanning for pre-failure drift")
    t0       = time.time()
    warnings = scan_for_drift_warnings(logs, scenario_id)
    elapsed  = round(time.time() - t0, 2)
    logger.info(f"          ✓ {len(warnings)} drift warning(s) detected  [{elapsed}s]")
    return warnings


def _stage_agent3(drift_warnings: list[dict]) -> dict:
    logger.info("STAGE 6b ▶ Agent 3 — Predictive Alert Generation (LLM)")
    t0     = time.time()
    result = generate_predictive_alerts(drift_warnings)
    elapsed= round(time.time() - t0, 2)
    alerts = result.get("alerts", [])
    urgencies = [a.get("urgency_level", "") for a in alerts]
    logger.info(f"          ✓ {len(alerts)} alert(s) generated  "
                f"urgencies={urgencies}  [{elapsed}s]")
    return result


# ──────────────────────────────────────────────────────────────────
# Main pipeline
# ──────────────────────────────────────────────────────────────────

def run_pipeline(
    dtcs:         list[str],
    logs:         list[dict],
    waveform:     list[dict] | None = None,
    freeze_frame: dict | None       = None,
    scenario_id:  str               = "live",
    scenario_dir: str | None        = None,
    kb_path:      str | None        = None,
) -> dict[str, Any]:
    """
    Full diagnostic pipeline.
    Returns combined structured result ready for the API response.
    """
    wall_start = time.time()
    if scenario_dir is None:
        scenario_dir = os.path.join(os.path.dirname(__file__), "data", "scenarios")
    if kb_path is None:
        kb_path = os.path.join(os.path.dirname(__file__), "knowledge_base.json")

    kb  = _load_kb(kb_path)
    dtc = dtcs[0] if dtcs else ""
    kb_ent = _kb_entry(kb, dtc)

    logger.info("=" * 60)
    logger.info(f"PIPELINE START  scenario={scenario_id}  dtc={dtc}")
    logger.info("=" * 60)

    pipeline_log = []

    # ── Stage 1: Anomaly Detection ────────────────────────────────
    anomaly_report = _stage_anomaly_detection(logs)
    pipeline_log.append({
        "stage": 1, "name": "Anomaly Detection",
        "anomaly_count": anomaly_report["anomaly_count"],
        "overall_severity": anomaly_report["overall_severity"],
    })

    # ── Stage 2: Digital Twin ─────────────────────────────────────
    twin_result = _stage_digital_twin(logs, scenario_dir)
    pipeline_log.append({
        "stage": 2, "name": "Digital Twin",
        "most_deviated_signal": twin_result["deviation"].get("most_deviated_signal", ""),
        "deviation_regions": len(twin_result["deviation"].get("deviation_regions", [])),
    })

    # ── Stage 3: Correlation Engine ───────────────────────────────
    fsv = _stage_correlation(dtcs, logs, anomaly_report, twin_result, freeze_frame, kb_path)
    pipeline_log.append({
        "stage": 3, "name": "Correlation Engine",
        "timing_pattern": fsv["timing_pattern"],
        "overall_severity": fsv["overall_severity"],
        "affected_signals": fsv["affected_signals"],
    })

    # ── Stages 4 + predictive scan run concurrently ───────────────
    # Agent 1 is the critical path. Predictive scan runs in parallel.
    agent3_result: dict = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_agent1 = pool.submit(_stage_agent1, fsv)
        fut_drift  = pool.submit(_stage_predictive_scan, logs, scenario_id)
        rc_result  = fut_agent1.result()
        drift_warnings = fut_drift.result()

    pipeline_log.append({
        "stage": 4, "name": "Agent 1 – Root Cause Reasoning",
        "top_cause": rc_result.get("ranked_causes", [{}])[0].get("cause", ""),
        "confidence": rc_result.get("ranked_causes", [{}])[0].get("confidence_score", 0),
        "cause_count": len(rc_result.get("ranked_causes", [])),
    })

    # ── Stage 5: Agent 2 — Fix Guide ─────────────────────────────
    fix_guide = _stage_agent2(rc_result, fsv, kb_ent)
    pipeline_log.append({
        "stage": 5, "name": "Agent 2 – Fix Guide",
        "step_count": len(fix_guide.get("steps", [])),
        "est_time_hr": fix_guide.get("estimated_total_time_hr", 0),
    })

    # ── Stage 6: Agent 3 — Predictive Alerts (only if warnings) ──
    if drift_warnings:
        agent3_result = _stage_agent3(drift_warnings)
        pipeline_log.append({
            "stage": "6b", "name": "Agent 3 – Predictive Alerts",
            "alert_count": len(agent3_result.get("alerts", [])),
            "fleet_action": agent3_result.get("fleet_action_recommended", False),
        })
    else:
        pipeline_log.append({
            "stage": "6a", "name": "Predictive Drift Monitor",
            "result": "No pre-failure drift detected",
        })

    wall_elapsed = round(time.time() - wall_start, 2)
    logger.info(f"PIPELINE COMPLETE  total={wall_elapsed}s")
    logger.info("=" * 60)

    return {
        "scenario_id":          scenario_id,
        "dtc":                  dtc,
        "all_dtcs":             dtcs,
        # ── deterministic outputs ─────────────────────────────────
        "anomaly_report":       anomaly_report,
        "anomaly_summary":      summarize_report(anomaly_report),
        "digital_twin":         twin_result,
        "fault_signature":      fsv,
        # ── agent outputs ─────────────────────────────────────────
        "agent1_root_causes":   rc_result,
        "agent2_fix_guide":     fix_guide,
        "agent3_predictive":    agent3_result if drift_warnings else {"alerts": [], "fleet_action_recommended": False},
        "drift_warnings":       drift_warnings,
        # ── meta ──────────────────────────────────────────────────
        "pipeline_log":         pipeline_log,
        "total_elapsed_sec":    wall_elapsed,
    }


def run_feedback_pipeline(
    engineer_feedback:     dict,
    original_diagnosis:    dict,
    fault_signature_vector:dict,
) -> dict:
    """Run Agent 4 (feedback/calibration) as a standalone pipeline step."""
    logger.info("FEEDBACK PIPELINE ▶ Agent 4 — Calibration")
    t0     = time.time()
    result = process_feedback(engineer_feedback, original_diagnosis, fault_signature_vector)
    elapsed= round(time.time() - t0, 2)
    logger.info(f"  ✓ calibration_note stored  [{elapsed}s]")
    return result


# ──────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    scenario_dir = os.path.join(os.path.dirname(__file__), "data", "scenarios")
    faults       = sorted(f for f in os.listdir(scenario_dir) if "FAULT" in f)
    if not faults:
        print("No fault scenarios. Run synthetic_data_generator.py first.")
        sys.exit(1)

    with open(os.path.join(scenario_dir, faults[0])) as fh:
        scenario = json.load(fh)

    print(f"Running full pipeline for: {scenario['scenario_id']}")
    result = run_pipeline(
        dtcs         = scenario["dtc"],
        logs         = scenario["logs"],
        waveform     = scenario.get("waveform"),
        freeze_frame = scenario.get("freeze_frame"),
        scenario_id  = scenario["scenario_id"],
        scenario_dir = scenario_dir,
    )

    print(f"\n{'='*60}")
    print(f"Pipeline complete in {result['total_elapsed_sec']}s")
    print(f"Top root cause: {result['agent1_root_causes'].get('ranked_causes', [{}])[0].get('cause', '—')}")
    print(f"Fix steps: {len(result['agent2_fix_guide'].get('steps', []))}")
    print(f"Predictive alerts: {len(result['agent3_predictive'].get('alerts', []))}")
