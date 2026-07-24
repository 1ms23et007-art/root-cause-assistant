# AI-Powered Root Cause Assistant
### ECM Diagnostic Multi-Agent Pipeline · Hackathon Project

> **Replaces slow, expert-dependent manual correlation of DTCs, validation reports, logs, and waveforms with an automated 4-agent AI pipeline — delivering ranked root causes with full evidence-cited reasoning chains in seconds.**

---

## Quick Start

```bash
# Set your Anthropic API key
export ANTHROPIC_API_KEY=sk-...

# From the project root
chmod +x start.sh && ./start.sh
```

- Backend:  http://localhost:8000
- Frontend: http://localhost:3000
- API docs: http://localhost:8000/docs

### Manual start (backend only)
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python synthetic_data_generator.py   # generate 35 labeled scenarios
uvicorn main:app --reload
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         React Frontend                              │
│  Scenario Selector · Waveform Chart · Root Cause Cards             │
│  Fix Guide (checkboxes) · Predictive Banner · Feedback Widget       │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ HTTP (axios)
┌──────────────────────────▼──────────────────────────────────────────┐
│                      FastAPI  main.py                               │
│  POST /analyze  ·  POST /feedback  ·  GET /predictive-scan         │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│                      orchestrator.py                                │
│                                                                     │
│   Stage 1 → anomaly_detector.py    (z-score / slew / FFT)          │
│   Stage 2 → digital_twin.py        (expected waveform + deviation)  │
│   Stage 3 → correlation_engine.py  (fault_signature_vector)         │
│   Stage 4 → Agent 1  ──────────────────────────────────────────┐   │
│   Stage 5 → Agent 2  (depends on Agent 1)                       │   │
│   Stage 6 → Predictive scan + Agent 3 (parallel with Stage 4)  │   │
└──────────────────────────────────────────────────────────────────┘  │
                                                                     │
                     ┌───────────────────────┘
                     ▼
           feedback → Agent 4 → feedback_log.json
                                    │
                                    └─► injected into Agent 1 on next call
```

---

## The 4 Agents — Distinct Roles

| Agent | File | Input | Output | Innovation |
|-------|------|-------|--------|------------|
| **Agent 1** — Root Cause Reasoning | `agent_root_cause_reasoning.py` | `fault_signature_vector` + KB | Ranked causes with evidence-cited reasoning chains | Evidence citation mandate; calibration note injection |
| **Agent 2** — Fix Guide | `agent_fix_guide.py` | Agent 1 top causes + KB repair procs | Step-by-step repair guide ordered cheapest→invasive | Phase-based with "confirm before replace" guards |
| **Agent 3** — Predictive Alerts | `agent_predictive_alert.py` | Pre-failure drift warnings | Plain-language early warnings with ETA | Fires BEFORE any DTC appears |
| **Agent 4** — Feedback Calibration | `agent_feedback_calibration.py` | Engineer thumbs up/down | Calibration note → `feedback_log.json` | Improves Agent 1's confidence over time |

Each agent is independently callable as a Python module — not split functions of one mega-prompt.

---

## Three Innovation Features

### 1. Digital Twin Overlay
`digital_twin.py` builds an interpolated "expected healthy waveform" from 5 healthy reference drive cycles, then computes point-by-point deviation between actual and expected. Deviation regions are shaded on the waveform chart in red, visually showing exactly where and how much the signal diverged from healthy behaviour.

### 2. Predictive Pre-DTC Drift Detection
`predictive_drift_monitor.py` scans logs that appear healthy (no DTC threshold breach yet) for slow linear drift trends in LTFT, MAF, battery voltage, O2 switching amplitude, and coolant temperature. It uses linear regression (R² filter to reject noise) to estimate km/hours until the DTC threshold is crossed — catching failures before they happen.

### 3. Feedback Calibration Loop
Agent 4 generates conditional calibration rules from engineer feedback (e.g., *"For P0171 + gradual MAF drift + no co-occurring DTCs, reduce confidence by 10% — pattern is sometimes a vacuum leak, not sensor contamination"*). These notes are stored in `feedback_log.json` and injected into Agent 1's system prompt on subsequent calls for the same DTC type. No model fine-tuning required — in-context learning via retrieved calibration notes.

---

## Differentiators vs. a Basic DTC Lookup Tool

| Basic DTC Lookup | RootCause AI |
|------------------|--------------|
| Shows possible causes for DTC code | Ranks causes by confidence from actual signal evidence |
| Generic repair steps | Ordered cheapest-first with "confirm before replace" gates |
| No waveform analysis | FFT noise detection, z-score, slew rate, cross-signal plausibility |
| No comparison baseline | Digital twin expected waveform overlay |
| Reactive (after DTC fires) | Predictive drift warnings before DTC threshold |
| Static confidence | Learning calibration loop from engineer feedback |
| Single lookup | Full explainability trace: evidence cited, alternatives eliminated |

---

## File Structure

```
rootcause/
├── start.sh                          # one-command startup
├── backend/
│   ├── main.py                       # FastAPI endpoints
│   ├── orchestrator.py               # pipeline runner
│   ├── synthetic_data_generator.py   # 35 labeled ECU scenarios
│   ├── knowledge_base.json           # DTC descriptions, thresholds, repairs
│   ├── anomaly_detector.py           # DSP: z-score, slew, FFT, cross-signal
│   ├── digital_twin.py               # expected waveform + deviation
│   ├── correlation_engine.py         # fault_signature_vector builder
│   ├── predictive_drift_monitor.py   # pre-failure linear drift detection
│   ├── agent_root_cause_reasoning.py # Agent 1
│   ├── agent_fix_guide.py            # Agent 2
│   ├── agent_predictive_alert.py     # Agent 3
│   ├── agent_feedback_calibration.py # Agent 4
│   ├── feedback_log.json             # calibration notes (auto-created)
│   └── data/scenarios/              # generated fault + healthy JSON files
└── frontend/
    ├── package.json
    └── src/
        ├── App.js                    # main dashboard
        ├── App.css                   # dark automotive theme
        └── components/
            ├── WaveformChart.js      # Recharts actual vs expected overlay
            ├── RootCauseCards.js     # expandable reasoning trace UI
            ├── FixGuidePanel.js      # step-by-step with checkboxes
            ├── PredictiveAlertBanner.js
            ├── PipelineLog.js        # execution log + anomaly table
            └── FeedbackWidget.js     # thumbs up/down → Agent 4
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Server status + scenario count |
| GET | `/scenarios` | List all available scenarios |
| GET | `/scenario/{id}` | Full scenario with logs |
| POST | `/generate-fault-scenario` | Random fault scenario for demo |
| POST | `/analyze` | Full pipeline on custom log data |
| POST | `/analyze-scenario/{id}` | Run pipeline on a stored scenario |
| POST | `/feedback` | Submit engineer feedback → Agent 4 |
| GET | `/predictive-scan` | Pre-failure scan across all scenarios |
| GET | `/knowledge-base/{dtc}` | KB entry for a DTC code |

---

## DTCs Covered

`P0171` · `P0174` · `P0300` · `P0301` · `P0302` · `P0303` · `P0304` · `P0562` · `P0563` · `U0100`

## Fault Patterns Generated (35 scenarios)

- Sensor drift (MAF, O2, ECT, LTFT) — gradual contamination/aging
- Flatline/open circuit (MAF, O2, TPS, battery sense) — broken wiring
- EMI/noise (O2, MAF, combined) — ignition system interference
- Stuck actuator (TPS, IAC, O2 high/low) — mechanical/electrical failure
- Intermittent dropout (CAN bus, O2, TPS) — corrosion with vibration
- Low/high voltage events — battery/alternator failure
- Multi-sensor correlated faults (power/ground faults affecting 2+ signals)
- Per-cylinder misfires (P0301–P0304) and random misfire (P0300)
