"""
FastAPI backend for AI-Powered Root Cause Assistant.
"""
from __future__ import annotations

import json
import logging
import os
import random
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from orchestrator import run_pipeline, run_feedback_pipeline
from predictive_drift_monitor import scan_all_scenarios

# ──────────────────────────────────────────────────────────────────
# App setup
# ──────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

app = FastAPI(
    title       = "AI-Powered Root Cause Assistant",
    description = "Multi-agent ECM diagnostic pipeline",
    version     = "1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins  = ["*"],
    allow_methods  = ["*"],
    allow_headers  = ["*"],
)

SCENARIO_DIR = os.path.join(os.path.dirname(__file__), "data", "scenarios")
KB_PATH      = os.path.join(os.path.dirname(__file__), "knowledge_base.json")


# ──────────────────────────────────────────────────────────────────
# Request/Response models
# ──────────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    dtc:         list[str]
    logs:        list[dict]
    waveform:    list[dict] | None = None
    freeze_frame:dict       | None = None
    scenario_id: str               = "live"


class FeedbackRequest(BaseModel):
    confirmed_correct:            bool
    actual_root_cause_if_different: str | None = None
    engineer_notes:               str | None   = None
    scenario_id:                  str          = "unknown"
    original_diagnosis:           dict
    fault_signature_vector:       dict


# ──────────────────────────────────────────────────────────────────
# Scenario cache (loaded once)
# ──────────────────────────────────────────────────────────────────

_scenario_cache: dict[str, dict] = {}


def _load_scenarios() -> dict[str, dict]:
    global _scenario_cache
    if _scenario_cache:
        return _scenario_cache
    if not os.path.isdir(SCENARIO_DIR):
        return {}
    for fname in os.listdir(SCENARIO_DIR):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(SCENARIO_DIR, fname)) as fh:
                data = json.load(fh)
            _scenario_cache[data["scenario_id"]] = data
        except Exception as e:
            logger.warning(f"Could not load {fname}: {e}")
    logger.info(f"Loaded {len(_scenario_cache)} scenarios from {SCENARIO_DIR}")
    return _scenario_cache


# ──────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    scenarios = _load_scenarios()
    return {
        "status":         "ok",
        "scenario_count": len(scenarios),
        "scenario_dir":   SCENARIO_DIR,
    }


@app.get("/scenarios")
def list_scenarios() -> dict:
    """Return metadata about all available scenarios (no log data)."""
    scenarios = _load_scenarios()
    summary   = []
    for sid, s in scenarios.items():
        summary.append({
            "scenario_id":    sid,
            "scenario_type":  s.get("scenario_type", ""),
            "dtc":            s.get("dtc", []),
            "ground_truth":   s.get("ground_truth_cause", ""),
        })
    # Sort: healthy first, then faults alphabetically
    summary.sort(key=lambda x: (0 if x["scenario_type"] == "healthy" else 1, x["scenario_id"]))
    return {"scenarios": summary, "count": len(summary)}


@app.post("/generate-fault-scenario")
def generate_fault_scenario(scenario_id: str | None = None) -> dict:
    """
    Return a random (or specific) synthetic fault scenario for demo purposes.
    Includes full log and waveform data.
    """
    scenarios = _load_scenarios()
    if not scenarios:
        raise HTTPException(status_code=503, detail="No scenarios loaded. Run synthetic_data_generator.py first.")

    if scenario_id and scenario_id in scenarios:
        chosen = scenarios[scenario_id]
    else:
        # Random fault scenario (prefer fault over healthy)
        fault_scenarios = {k: v for k, v in scenarios.items()
                           if v.get("scenario_type") != "healthy"}
        pool    = fault_scenarios or scenarios
        key     = random.choice(list(pool.keys()))
        chosen  = pool[key]

    return {
        "scenario_id":    chosen["scenario_id"],
        "scenario_type":  chosen.get("scenario_type", ""),
        "dtc":            chosen.get("dtc", []),
        "ground_truth":   chosen.get("ground_truth_cause", ""),
        "freeze_frame":   chosen.get("freeze_frame"),
        "waveform":       chosen.get("waveform", []),
        "log_count":      len(chosen.get("logs", [])),
        "timestamp_metadata": chosen.get("timestamp_metadata", {}),
    }


@app.get("/scenario/{scenario_id}")
def get_scenario(scenario_id: str) -> dict:
    """Return full scenario including logs."""
    scenarios = _load_scenarios()
    if scenario_id not in scenarios:
        raise HTTPException(status_code=404, detail=f"Scenario {scenario_id!r} not found")
    return scenarios[scenario_id]


@app.post("/analyze")
def analyze(request: AnalyzeRequest) -> dict[str, Any]:
    """
    Run the full diagnostic pipeline on provided log data.
    Returns anomaly_report, digital_twin, fault_signature,
    agent1_root_causes, agent2_fix_guide, agent3_predictive_alerts.
    """
    if not request.dtc:
        raise HTTPException(status_code=400, detail="At least one DTC is required")
    if not request.logs:
        raise HTTPException(status_code=400, detail="Log data is required")

    logger.info(f"/analyze  scenario={request.scenario_id}  dtc={request.dtc}")
    try:
        result = run_pipeline(
            dtcs         = request.dtc,
            logs         = request.logs,
            waveform     = request.waveform,
            freeze_frame = request.freeze_frame,
            scenario_id  = request.scenario_id,
            scenario_dir = SCENARIO_DIR,
            kb_path      = KB_PATH,
        )
        return result
    except Exception as e:
        logger.exception("Pipeline error")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze-scenario/{scenario_id}")
def analyze_scenario(scenario_id: str) -> dict[str, Any]:
    """
    Convenience endpoint: look up a scenario by ID and run the full pipeline.
    """
    scenarios = _load_scenarios()
    if scenario_id not in scenarios:
        raise HTTPException(status_code=404, detail=f"Scenario {scenario_id!r} not found")

    s = scenarios[scenario_id]
    logger.info(f"/analyze-scenario/{scenario_id}  dtc={s.get('dtc')}")
    try:
        result = run_pipeline(
            dtcs         = s.get("dtc", []),
            logs         = s.get("logs", []),
            waveform     = s.get("waveform"),
            freeze_frame = s.get("freeze_frame"),
            scenario_id  = scenario_id,
            scenario_dir = SCENARIO_DIR,
            kb_path      = KB_PATH,
        )
        result["ground_truth"] = s.get("ground_truth_cause", "")
        return result
    except Exception as e:
        logger.exception("Pipeline error")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/feedback")
def submit_feedback(request: FeedbackRequest) -> dict:
    """
    Submit engineer feedback on a diagnosis → runs Agent 4 → updates feedback_log.json.
    """
    logger.info(f"/feedback  scenario={request.scenario_id}  correct={request.confirmed_correct}")
    try:
        feedback_dict = {
            "confirmed_correct":              request.confirmed_correct,
            "actual_root_cause_if_different": request.actual_root_cause_if_different,
            "engineer_notes":                 request.engineer_notes,
            "scenario_id":                    request.scenario_id,
        }
        result = run_feedback_pipeline(
            engineer_feedback      = feedback_dict,
            original_diagnosis     = request.original_diagnosis,
            fault_signature_vector = request.fault_signature_vector,
        )
        return result
    except Exception as e:
        logger.exception("Feedback pipeline error")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/predictive-scan")
def predictive_scan() -> dict:
    """
    Run predictive_drift_monitor across all loaded scenarios.
    Returns pre-failure drift warnings.
    """
    logger.info("/predictive-scan")
    try:
        warnings = scan_all_scenarios(SCENARIO_DIR)
        if warnings:
            from agent_predictive_alert import generate_predictive_alerts
            alerts = generate_predictive_alerts(warnings[:10])
        else:
            alerts = {
                "alerts": [],
                "fleet_action_recommended": False,
                "summary_for_manager": "No pre-failure drift detected across all scenarios.",
            }
        return {
            "drift_warnings": warnings,
            "alert_count":    len(warnings),
            "agent3_alerts":  alerts,
        }
    except Exception as e:
        logger.exception("Predictive scan error")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/knowledge-base/{dtc}")
def get_kb_entry(dtc: str) -> dict:
    """Return KB entry for a specific DTC."""
    try:
        with open(KB_PATH) as fh:
            kb = json.load(fh)
        entry = kb.get("dtc_entries", {}).get(dtc.upper())
        if not entry:
            raise HTTPException(status_code=404, detail=f"DTC {dtc!r} not in knowledge base")
        return entry
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────────
# Startup: generate scenarios if dir is empty
# ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    os.makedirs(SCENARIO_DIR, exist_ok=True)
    existing = [f for f in os.listdir(SCENARIO_DIR) if f.endswith(".json")]
    if not existing:
        logger.info("No scenarios found — generating synthetic data...")
        try:
            from synthetic_data_generator import run_generation
            run_generation(output_dir=SCENARIO_DIR)
        except Exception as e:
            logger.error(f"Failed to generate scenarios: {e}")
    _load_scenarios()
