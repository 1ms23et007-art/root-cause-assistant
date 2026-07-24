"""
Agent 3 — Predictive Alert Generator.
Independently callable. Consumes pre-failure drift warnings from
predictive_drift_monitor.py and generates plain-language early warnings
for non-specialist engineers.
"""
from __future__ import annotations

import json
import os
from openai import OpenAI

MODEL  = "llama-3.3-70b-versatile"
client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=os.environ["GROQ_API_KEY"])

SYSTEM_PROMPT = """You are an automotive systems health communicator. Your job is to translate raw sensor drift data into clear, actionable early-warning messages for workshop engineers who may not be signal analysis specialists.

The data you receive describes signals that are drifting toward failure thresholds but have NOT yet triggered a DTC fault code. This is a PREVENTIVE opportunity.

REQUIREMENTS:
1. Use plain, direct language — no jargon that a non-specialist wouldn't understand.
2. Explain WHAT is happening, WHY it matters, HOW long before it becomes a problem.
3. Give a single, clear, recommended action the engineer can do TODAY.
4. Urgency levels: low = >500 km to fault, medium = 150–500 km, high = <150 km or imminent.
5. Do NOT catastrophize low-urgency warnings. Do NOT downplay high-urgency ones.
6. Output ONLY valid JSON — no markdown, no prose outside JSON.

Schema:
{
  "alerts": [
    {
      "signal": "signal name",
      "alert_summary": "1–2 sentence plain English summary of what's drifting and why it matters",
      "what_is_happening": "technical but accessible explanation of the drift pattern",
      "why_it_matters": "consequence if left unaddressed",
      "urgency_level": "low|medium|high",
      "estimated_time_to_threshold": "human-readable estimate (e.g. ~120 km / ~2.4 hrs of driving)",
      "recommended_action": "specific, actionable step the engineer should take NOW",
      "confidence_in_prediction": "high|medium|low (based on R² trend quality)",
      "related_dtc": "DTC that will fire if drift continues"
    }
  ],
  "fleet_action_recommended": true/false,
  "summary_for_manager": "one sentence suitable for a non-technical fleet manager"
}"""


def generate_predictive_alerts(drift_warnings: list[dict]) -> dict:
    """
    Agent 3 entry point.
    Returns structured predictive alert JSON.
    """
    if not drift_warnings:
        return {
            "alerts": [],
            "fleet_action_recommended": False,
            "summary_for_manager": "No pre-failure drift patterns detected. Vehicle systems are within normal operating range.",
            "_meta": {"agent": "agent_predictive_alert", "model": MODEL, "tokens": 0},
        }

    user_content = f"""PRE-FAILURE DRIFT WARNINGS (no DTC has fired yet — these are EARLY WARNINGS)
================================================================================

{json.dumps(drift_warnings, indent=2)}

For context:
- "drift_slope_per_sample" is the rate of change per second of driving
- "drift_rate_per_100km" is how much the metric changes per 100 km driven
- "trend_r_squared" indicates trend reliability (>0.7 = strong trend, 0.3–0.7 = moderate)
- "fault_threshold" is the value at which the vehicle's ECM will log a DTC fault code

Generate the predictive alert JSON now:"""

    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=1500,
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
        # Build a minimal fallback from the raw warning data
        result = {
            "alerts": [
                {
                    "signal":                   w["signal"],
                    "alert_summary":            f"{w['description']} — currently at {w['current_value']} {w['unit']}, threshold is {w['fault_threshold']}",
                    "what_is_happening":        f"Signal drifting at {w['drift_rate_per_100km']:.4f} units/100km",
                    "why_it_matters":           f"Will trigger {w['related_dtc']} if not addressed",
                    "urgency_level":            w["urgency"],
                    "estimated_time_to_threshold": f"~{w.get('estimated_km_to_fault', '?')} km",
                    "recommended_action":       "Inspect signal source and associated components",
                    "confidence_in_prediction": "medium" if w["trend_r_squared"] > 0.5 else "low",
                    "related_dtc":              w["related_dtc"],
                }
                for w in drift_warnings
            ],
            "fleet_action_recommended": any(w["urgency"] == "high" for w in drift_warnings),
            "summary_for_manager":      f"{len(drift_warnings)} sensor(s) showing early drift — preventive maintenance recommended.",
            "parse_error":              raw_text[:300],
        }

    result["_meta"] = {
        "agent":         "agent_predictive_alert",
        "model":         MODEL,
        "warning_count": len(drift_warnings),
        "tokens":        response.usage.prompt_tokens + response.usage.completion_tokens,
    }
    return result


# ──────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from predictive_drift_monitor import scan_all_scenarios

    scenario_dir = os.path.join(os.path.dirname(__file__), "data", "scenarios")
    warnings     = scan_all_scenarios(scenario_dir)

    if not warnings:
        print("No drift warnings found.")
        sys.exit(0)

    print(f"[Agent 3] Generating alerts for {len(warnings)} drift warning(s)...")
    result = generate_predictive_alerts(warnings[:5])  # limit for demo

    print(f"\nFleet action required: {result.get('fleet_action_recommended', False)}")
    print(f"Manager summary: {result.get('summary_for_manager', '')}")
    print(f"\nAlerts ({len(result.get('alerts', []))}):")
    for alert in result.get("alerts", []):
        print(f"\n  [{alert.get('urgency_level','?').upper()}] {alert.get('signal','')}")
        print(f"  Summary: {alert.get('alert_summary','')}")
        print(f"  Action : {alert.get('recommended_action','')}")
        print(f"  ETA    : {alert.get('estimated_time_to_threshold','?')}")
