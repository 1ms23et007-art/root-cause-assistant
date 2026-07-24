"""
Agent 2 — Fix Guide Generator.
Independently callable. Consumes top root causes from Agent 1 + KB repair procedures,
produces a step-by-step engineer repair guide ordered cheapest-to-most-invasive.
"""
from __future__ import annotations

import json
import os
from openai import OpenAI

MODEL  = "llama-3.3-70b-versatile"
client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=os.environ["GROQ_API_KEY"])

SYSTEM_PROMPT = """You are a senior automotive repair technician writing a concise, actionable repair guide for a workshop engineer.

Given the top root causes identified by the diagnostic AI and the known repair procedures from the knowledge base, generate a practical step-by-step fix guide.

REQUIREMENTS:
1. Order steps from cheapest/fastest/least-invasive check FIRST to most invasive LAST.
   Example order: visual inspection → electrical test → cleaning → component replacement → major teardown.
2. Include a "CONFIRM BEFORE YOU REPLACE" verification check for any step that involves component replacement.
3. Be specific: mention the exact tool, measurement value or expected outcome for each step.
4. Group steps by phase: PHASE 1 – Quick checks (0–30 min), PHASE 2 – Electrical/Sensor tests (30–90 min), PHASE 3 – Component replacement (if phases 1–2 don't resolve).
5. Include concrete safety notes (fire, electrical, hot coolant, etc.) relevant to this specific repair.
6. Output ONLY valid JSON — no markdown, no prose outside JSON.

Schema:
{
  "repair_target": "brief description of what we're fixing",
  "steps": [
    {
      "phase": 1,
      "step_number": 1,
      "action": "Clear description of what to do",
      "tool_required": "specific tool(s)",
      "expected_outcome": "what you should find/measure if system is healthy",
      "if_outcome_abnormal": "what it means and what to do next",
      "est_time_min": 15,
      "confirm_before_replace": "verification test before condemning the part (if applicable, else null)"
    }
  ],
  "estimated_total_time_hr": 2.5,
  "tools_required": ["list of all unique tools needed"],
  "parts_that_may_be_needed": ["list of possibly faulty parts, ranked by likelihood"],
  "safety_notes": ["specific safety warnings for this repair"],
  "success_criteria": "how to confirm the repair is complete and effective"
}"""


def generate_fix_guide(
    root_cause_result: dict,
    fault_signature_vector: dict,
    kb_entry: dict | None = None,
) -> dict:
    """
    Agent 2 entry point.
    Returns structured repair guide JSON.
    """
    # Extract top 2 causes from Agent 1 output
    ranked_causes  = root_cause_result.get("ranked_causes", [])
    top_causes     = ranked_causes[:2]
    dtc            = fault_signature_vector.get("dtc", "UNKNOWN")

    # Get KB repair procedures for this DTC
    kb_procedures  = (kb_entry or {}).get("repair_procedures", [])
    kb_tools       = (kb_entry or {}).get("required_tools", [])
    kb_fix_time    = (kb_entry or {}).get("estimated_fix_time_hr", "unknown")

    user_content = f"""DIAGNOSIS SUMMARY
==================
DTC: {dtc} — {fault_signature_vector.get('dtc_description', '')}
Timing pattern: {fault_signature_vector.get('timing_pattern', 'unknown')}

TOP ROOT CAUSES (from diagnostic reasoning):
{json.dumps(top_causes, indent=2)}

RELEVANT ANOMALY EVIDENCE:
{json.dumps(fault_signature_vector.get('anomalies', [])[:6], indent=2)}

VALIDATION THRESHOLD BREACHES:
{json.dumps(fault_signature_vector.get('validation_deviation', {}), indent=2)}

KNOWLEDGE BASE REPAIR PROCEDURES FOR {dtc}:
{json.dumps(kb_procedures, indent=2)}

KNOWLEDGE BASE TOOLS:
{kb_tools}

KNOWLEDGE BASE ESTIMATED FIX TIME: {kb_fix_time} hr

RECOMMENDED FIRST ACTION (from Agent 1):
{root_cause_result.get('recommended_first_action', '')}

Generate the step-by-step repair guide JSON now:"""

    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=2048,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_content},
        ],
    )

    raw_text = response.choices[0].message.content.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError:
        result = {
            "repair_target": f"DTC {dtc} repair",
            "steps": [],
            "estimated_total_time_hr": 0,
            "tools_required": [],
            "parts_that_may_be_needed": [],
            "safety_notes": ["Unable to parse fix guide — manual review required"],
            "success_criteria": "",
            "parse_error": raw_text[:500],
        }

    result["_meta"] = {
        "agent":  "agent_fix_guide",
        "model":  MODEL,
        "dtc":    dtc,
        "tokens": response.usage.prompt_tokens + response.usage.completion_tokens,
    }
    return result


# ──────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from anomaly_detector    import analyze_logs
    from digital_twin        import run_digital_twin_analysis
    from correlation_engine  import build_fault_signature_vector
    from agent_root_cause_reasoning import analyze_root_cause
    import json as _json

    scenario_dir = os.path.join(os.path.dirname(__file__), "data", "scenarios")
    faults       = sorted(f for f in os.listdir(scenario_dir) if "FAULT" in f)
    if not faults:
        print("No fault scenarios found.")
        sys.exit(1)

    with open(os.path.join(scenario_dir, faults[0])) as fh:
        scenario = json.load(fh)

    print(f"[Agent 2] Fix guide for: {scenario['scenario_id']}")

    anomaly_report = analyze_logs(scenario["logs"])
    twin_result    = run_digital_twin_analysis(scenario["logs"], scenario_dir)
    fsv = build_fault_signature_vector(
        dtcs=scenario["dtc"], logs=scenario["logs"],
        anomaly_report=anomaly_report, twin_result=twin_result,
        freeze_frame=scenario.get("freeze_frame"),
    )

    rc_result = analyze_root_cause(fsv)
    guide     = generate_fix_guide(rc_result, fsv)

    print(f"\nRepair target: {guide.get('repair_target', '')}")
    print(f"Estimated time: {guide.get('estimated_total_time_hr', '?')} hr")
    print(f"Steps: {len(guide.get('steps', []))}")
    for step in guide.get("steps", [])[:4]:
        print(f"  [{step.get('phase','')}] Step {step.get('step_number','')}: {step.get('action','')[:70]}")
