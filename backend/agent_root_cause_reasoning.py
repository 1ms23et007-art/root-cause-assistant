"""
Agent 1 — Root Cause Reasoning.
Independently callable. Consumes fault_signature_vector + KB entries,
produces a ranked list of probable root causes with evidence-cited reasoning chains.
"""
from __future__ import annotations

import json
import os
from openai import OpenAI

MODEL  = "llama-3.3-70b-versatile"
client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=os.environ["GROQ_API_KEY"])

SYSTEM_PROMPT = """You are an expert automotive ECM (Engine Control Module) diagnostic engineer with 20+ years of experience diagnosing OBD-II fault codes using data-driven signal analysis.

Your task: given structured fault evidence (anomaly signals, digital twin deviations, DTC codes, and validation data), generate a RANKED list of the most probable root causes.

STRICT REQUIREMENTS:
1. Only cite evidence present in the input data. Quote specific signal names, anomaly types, severity scores, and threshold values.
2. If evidence is ambiguous between two causes, state that explicitly rather than guessing with high confidence.
3. Eliminate alternative causes step-by-step using the actual evidence — explain WHY each cause was ruled in or out.
4. Consider timing_pattern (gradual vs abrupt vs intermittent vs multi-system) as a key differentiator.
5. Weight multi-signal correlated faults more heavily than single-signal anomalies.
6. Output ONLY valid JSON matching the schema exactly — no markdown, no prose outside the JSON.

Schema:
{
  "ranked_causes": [
    {
      "rank": 1,
      "cause": "short descriptive name",
      "confidence_score": 0-100,
      "supporting_evidence": ["list of specific evidence items citing signal names and values"],
      "reasoning_chain": ["step 1: ...", "step 2: ...", "step 3: ..."],
      "ruled_out_alternatives": ["alternative cause X ruled out because: ..."],
      "requires_further_testing": ["additional test needed to confirm"]
    }
  ],
  "overall_diagnostic_confidence": 0-100,
  "ambiguity_note": "only present if evidence is genuinely ambiguous between top causes",
  "recommended_first_action": "single most important next step"
}

Return 3–5 ranked causes. Confidence scores must sum to no more than 200 (to reflect that causes can be complementary, not exhaustive 100% probability distribution)."""


def _load_feedback_context(dtc: str,
                            feedback_log_path: str | None = None) -> str:
    """Load relevant past calibration notes for this DTC type from feedback_log.json."""
    if feedback_log_path is None:
        feedback_log_path = os.path.join(os.path.dirname(__file__), "feedback_log.json")
    if not os.path.exists(feedback_log_path):
        return ""
    try:
        with open(feedback_log_path) as fh:
            log = json.load(fh)
        relevant = [
            entry for entry in log.get("calibration_notes", [])
            if dtc in entry.get("affected_fault_pattern", "")
               or dtc in entry.get("related_dtcs", [])
        ]
        if not relevant:
            return ""
        lines = ["CALIBRATION NOTES FROM PAST ENGINEER FEEDBACK (factor these into confidence scores):"]
        for note in relevant[-5:]:  # last 5 relevant notes
            lines.append(f"- {note.get('calibration_note', '')}"
                         f" [confidence_adj: {note.get('confidence_adjustment_pct', 0):+.0f}%]")
        return "\n".join(lines)
    except Exception:
        return ""


def analyze_root_cause(
    fault_signature_vector: dict,
    kb_entry: dict | None = None,
    feedback_log_path: str | None = None,
) -> dict:
    """
    Agent 1 entry point.
    Returns structured root cause analysis JSON.
    """
    dtc            = fault_signature_vector.get("dtc", "UNKNOWN")
    feedback_ctx   = _load_feedback_context(dtc, feedback_log_path)

    user_content = f"""FAULT EVIDENCE FOR DIAGNOSIS
=============================

DTC: {dtc} — {fault_signature_vector.get('dtc_description', '')}
All active DTCs: {fault_signature_vector.get('all_dtcs', [dtc])}
Timing pattern: {fault_signature_vector.get('timing_pattern', 'unknown')}
Overall severity: {fault_signature_vector.get('overall_severity', 0):.3f}
Affected signals: {fault_signature_vector.get('affected_signals', [])}

TOP ANOMALIES (sorted by severity):
{json.dumps(fault_signature_vector.get('anomalies', []), indent=2)}

CO-OCCURRING DTC PATTERNS:
{json.dumps(fault_signature_vector.get('co_occurring_dtcs', []), indent=2)}

VALIDATION THRESHOLD BREACHES:
{json.dumps(fault_signature_vector.get('validation_deviation', {}), indent=2)}

DIGITAL TWIN DEVIATION SUMMARY:
{json.dumps(fault_signature_vector.get('digital_twin_deviation_summary', {}), indent=2)}

FREEZE FRAME DATA:
{json.dumps(fault_signature_vector.get('freeze_frame', {}), indent=2)}

KNOWLEDGE BASE — KNOWN CAUSES FOR {dtc}:
{json.dumps(fault_signature_vector.get('kb_typical_causes', []), indent=2)}

KNOWLEDGE BASE — VALIDATION THRESHOLDS FOR {dtc}:
{json.dumps(fault_signature_vector.get('kb_validation_thresholds', {}), indent=2)}

KNOWLEDGE BASE — DIAGNOSTIC PRIORITY ORDER:
{json.dumps(fault_signature_vector.get('kb_priority_order', []), indent=2)}
"""

    if feedback_ctx:
        user_content += f"\n{feedback_ctx}\n"

    user_content += "\nGenerate the ranked root cause analysis JSON now:"

    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=2048,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_content},
        ],
    )

    raw_text = response.choices[0].message.content.strip()

    # Strip any markdown code fence if model added one
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError:
        # Fallback: wrap in error structure
        result = {
            "ranked_causes": [],
            "overall_diagnostic_confidence": 0,
            "parse_error": raw_text[:500],
            "recommended_first_action": "Manual inspection required — agent output could not be parsed",
        }

    result["_meta"] = {
        "agent":  "agent_root_cause_reasoning",
        "model":  MODEL,
        "dtc":    dtc,
        "tokens": response.usage.prompt_tokens + response.usage.completion_tokens,
    }
    return result


# ──────────────────────────────────────────────────────────────────
# CLI entry point for standalone testing
# ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from anomaly_detector    import analyze_logs
    from digital_twin        import run_digital_twin_analysis
    from correlation_engine  import build_fault_signature_vector

    scenario_dir = os.path.join(os.path.dirname(__file__), "data", "scenarios")
    faults       = sorted(f for f in os.listdir(scenario_dir) if "FAULT" in f)
    if not faults:
        print("No fault scenarios. Run synthetic_data_generator.py first.")
        sys.exit(1)

    with open(os.path.join(scenario_dir, faults[0])) as fh:
        scenario = json.load(fh)

    print(f"[Agent 1] Analysing: {scenario['scenario_id']}")
    print(f"          Ground truth: {scenario['ground_truth_cause']}")

    anomaly_report = analyze_logs(scenario["logs"])
    twin_result    = run_digital_twin_analysis(scenario["logs"], scenario_dir)
    fsv = build_fault_signature_vector(
        dtcs=scenario["dtc"], logs=scenario["logs"],
        anomaly_report=anomaly_report, twin_result=twin_result,
        freeze_frame=scenario.get("freeze_frame"),
    )

    result = analyze_root_cause(fsv)
    print(f"\nTop root causes ({result.get('overall_diagnostic_confidence', 0)}% confidence):")
    for cause in result.get("ranked_causes", [])[:3]:
        print(f"  #{cause['rank']} [{cause['confidence_score']}%] {cause['cause']}")
        print(f"     Evidence: {cause['supporting_evidence'][0] if cause.get('supporting_evidence') else '—'}")
