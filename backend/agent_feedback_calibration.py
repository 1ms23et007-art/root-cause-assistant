"""
Agent 4 — Feedback Calibration Loop (Innovation Feature 3).
Independently callable. Consumes engineer feedback on a previous diagnosis,
generates a calibration note, and stores it in feedback_log.json.
On subsequent Agent 1 calls the relevant notes are injected as context.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from openai import OpenAI

MODEL             = "llama-3.3-70b-versatile"
client            = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=os.environ["GROQ_API_KEY"])
FEEDBACK_LOG_PATH = os.path.join(os.path.dirname(__file__), "feedback_log.json")


SYSTEM_PROMPT = """You are a diagnostic AI calibration specialist. Your job is to analyse engineer feedback on a previous AI diagnosis and generate a precise, actionable calibration note that will improve future diagnostic accuracy.

REQUIREMENTS:
1. Identify the specific PATTERN in the fault evidence that led the AI astray (or was correct).
2. Express the calibration note as a conditional rule: "For [fault pattern] cases with [evidence features], confidence in [cause] should be [adjusted] because [reason]."
3. Be specific about WHICH signals/anomaly types and WHICH fault patterns trigger this adjustment.
4. If the diagnosis was CORRECT, the note should REINFORCE the pattern that worked.
5. If INCORRECT, the note should REDUCE confidence in the misidentified cause AND potentially INCREASE confidence in the actual cause.
6. Output ONLY valid JSON — no markdown, no prose outside JSON.

Schema:
{
  "calibration_note": "conditional rule as described",
  "confidence_adjustment_pct": -25 to +25 (negative = reduce confidence, positive = reinforce),
  "affected_fault_pattern": "DTC + key signal pattern that triggers this note",
  "related_dtcs": ["list of DTCs this calibration applies to"],
  "cause_being_adjusted": "name of the root cause whose confidence is being adjusted",
  "direction": "reinforce|reduce",
  "evidence_pattern_that_triggered": "specific anomaly pattern that caused the original diagnosis",
  "correct_cause_if_different": "actual cause (if diagnosis was wrong, else null)",
  "lesson_type": "false_positive|false_negative|confirmed_correct|ambiguity_clarification"
}"""


def _load_feedback_log() -> dict:
    if not os.path.exists(FEEDBACK_LOG_PATH):
        return {"calibration_notes": [], "total_feedback_count": 0}
    try:
        with open(FEEDBACK_LOG_PATH) as fh:
            return json.load(fh)
    except Exception:
        return {"calibration_notes": [], "total_feedback_count": 0}


def _save_feedback_log(log: dict) -> None:
    with open(FEEDBACK_LOG_PATH, "w") as fh:
        json.dump(log, fh, indent=2)


def process_feedback(
    engineer_feedback: dict,
    original_diagnosis: dict,
    fault_signature_vector: dict,
) -> dict:
    """
    Agent 4 entry point.

    engineer_feedback schema:
    {
      "confirmed_correct": true/false,
      "actual_root_cause_if_different": "...",   # optional, only if wrong
      "engineer_notes": "...",                   # optional
      "scenario_id": "..."                       # for tracking
    }

    original_diagnosis: Agent 1 output (ranked_causes, etc.)
    fault_signature_vector: the FSV used for the diagnosis
    """
    confirmed      = engineer_feedback.get("confirmed_correct", True)
    actual_cause   = engineer_feedback.get("actual_root_cause_if_different")
    engineer_notes = engineer_feedback.get("engineer_notes", "")
    scenario_id    = engineer_feedback.get("scenario_id", "unknown")
    dtc            = fault_signature_vector.get("dtc", "UNKNOWN")

    top_cause = {}
    if original_diagnosis.get("ranked_causes"):
        top_cause = original_diagnosis["ranked_causes"][0]

    user_content = f"""ENGINEER FEEDBACK ON PREVIOUS AI DIAGNOSIS
==========================================

Scenario ID: {scenario_id}
DTC: {dtc}
Diagnosis confirmed correct: {confirmed}
Actual root cause (if different): {actual_cause or 'N/A — diagnosis was correct'}
Engineer notes: {engineer_notes or 'None'}

ORIGINAL AI TOP DIAGNOSIS:
  Cause: {top_cause.get('cause', 'unknown')}
  Confidence: {top_cause.get('confidence_score', 0)}%
  Supporting evidence: {top_cause.get('supporting_evidence', [])}
  Reasoning chain: {top_cause.get('reasoning_chain', [])}

FAULT EVIDENCE THAT WAS USED:
  Timing pattern: {fault_signature_vector.get('timing_pattern', '')}
  Affected signals: {fault_signature_vector.get('affected_signals', [])}
  Anomaly types: {fault_signature_vector.get('anomaly_types', [])}
  Validation deviation: {fault_signature_vector.get('validation_deviation_pct', 0)}%
  Co-occurring DTCs: {[c.get('pattern') for c in fault_signature_vector.get('co_occurring_dtcs', [])]}

ALL RANKED CAUSES FROM AI:
{json.dumps(original_diagnosis.get('ranked_causes', [])[:3], indent=2)}

Generate the calibration note JSON now:"""

    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_content},
        ],
    )

    raw_text = response.choices[0].message.content.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        calibration = json.loads(raw_text)
    except json.JSONDecodeError:
        calibration = {
            "calibration_note":              f"Feedback recorded for {dtc} — manual review required",
            "confidence_adjustment_pct":      0,
            "affected_fault_pattern":         dtc,
            "related_dtcs":                  [dtc],
            "cause_being_adjusted":           top_cause.get("cause", ""),
            "direction":                      "confirmed_correct" if confirmed else "reduce",
            "evidence_pattern_that_triggered":"",
            "correct_cause_if_different":     actual_cause,
            "lesson_type":                    "confirmed_correct" if confirmed else "false_positive",
            "parse_error":                    raw_text[:300],
        }

    # Persist to feedback_log.json
    log = _load_feedback_log()
    log_entry = {
        "timestamp":               datetime.utcnow().isoformat(),
        "scenario_id":             scenario_id,
        "dtc":                     dtc,
        "confirmed_correct":       confirmed,
        "actual_root_cause":       actual_cause,
        "engineer_notes":          engineer_notes,
        **calibration,
    }
    log["calibration_notes"].append(log_entry)
    log["total_feedback_count"] = log.get("total_feedback_count", 0) + 1
    _save_feedback_log(log)

    calibration["_meta"] = {
        "agent":          "agent_feedback_calibration",
        "model":          MODEL,
        "scenario_id":    scenario_id,
        "feedback_count": log["total_feedback_count"],
        "tokens":         response.usage.prompt_tokens + response.usage.completion_tokens,
    }
    return calibration


def get_all_calibration_notes(dtc: str | None = None) -> list[dict]:
    """Return stored calibration notes, optionally filtered by DTC."""
    log   = _load_feedback_log()
    notes = log.get("calibration_notes", [])
    if dtc:
        notes = [n for n in notes if dtc in n.get("affected_fault_pattern", "")
                 or dtc in n.get("related_dtcs", [])]
    return notes


# ──────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Demo: simulate engineer feedback saying Agent 1 was WRONG about P0171
    demo_feedback = {
        "confirmed_correct": False,
        "actual_root_cause_if_different": "Vacuum leak at intake manifold gasket, not MAF sensor drift",
        "engineer_notes": "Found intake manifold gasket blown at cylinder 2–3 interface. MAF was reading correctly after all.",
        "scenario_id": "DEMO_FEEDBACK_001",
    }

    demo_diagnosis = {
        "ranked_causes": [
            {
                "rank": 1,
                "cause": "MAF sensor contamination causing drift",
                "confidence_score": 72,
                "supporting_evidence": ["MAF showing 12% gradual drift over log", "LTFT +8.5%"],
                "reasoning_chain": ["Step 1: Gradual drift pattern suggests contamination", "Step 2: No co-occurring U0100 rules out wiring"],
            }
        ],
        "overall_diagnostic_confidence": 72,
    }

    demo_fsv = {
        "dtc": "P0171",
        "dtc_description": "System Too Lean Bank 1",
        "timing_pattern": "gradual",
        "affected_signals": ["maf", "ltft"],
        "anomaly_types": ["gradual_drift"],
        "validation_deviation_pct": 8.5,
        "co_occurring_dtcs": [],
    }

    print("[Agent 4] Processing demo feedback...")
    result = process_feedback(demo_feedback, demo_diagnosis, demo_fsv)
    print(f"\nCalibration note: {result.get('calibration_note', '')}")
    print(f"Adjustment      : {result.get('confidence_adjustment_pct', 0):+d}%")
    print(f"Lesson type     : {result.get('lesson_type', '')}")
    print(f"Saved to        : {FEEDBACK_LOG_PATH}")
