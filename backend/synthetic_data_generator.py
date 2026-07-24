"""
Synthetic ECU data generator for AI-Powered Root Cause Assistant.
Generates realistic time-series sensor logs for both healthy and faulty drive cycles.
"""

import json
import math
import random
import os
from datetime import datetime, timedelta

SEED = 42
random.seed(SEED)

# ──────────────────────────────────────────────────────────────────
# OBD-II realistic signal ranges
# ──────────────────────────────────────────────────────────────────
SIGNAL_PARAMS = {
    "rpm":          {"min": 650,  "max": 6500, "idle": 800,    "unit": "RPM"},
    "ect":          {"min": 20,   "max": 120,  "idle": 88,     "unit": "°C"},
    "maf":          {"min": 2.0,  "max": 220,  "idle": 4.5,    "unit": "g/s"},
    "o2_voltage":   {"min": 0.0,  "max": 1.0,  "idle": 0.45,   "unit": "V"},
    "ltft":         {"min": -25,  "max": 25,   "idle": 1.5,    "unit": "%"},
    "tps":          {"min": 0,    "max": 100,  "idle": 5.0,    "unit": "%"},
    "can_health":   {"min": 0,    "max": 1,    "idle": 1.0,    "unit": "status"},
    "batt_voltage": {"min": 10.0, "max": 15.0, "idle": 13.8,   "unit": "V"},
}

DTC_REGISTRY = {
    "P0171": "System Too Lean (Bank 1)",
    "P0174": "System Too Lean (Bank 2)",
    "P0300": "Random/Multiple Cylinder Misfire Detected",
    "P0301": "Cylinder 1 Misfire Detected",
    "P0302": "Cylinder 2 Misfire Detected",
    "P0303": "Cylinder 3 Misfire Detected",
    "P0304": "Cylinder 4 Misfire Detected",
    "P0562": "System Voltage Low",
    "P0563": "System Voltage High",
    "U0100": "Lost Communication with ECM/PCM",
}

SAMPLES_PER_SCENARIO = 300   # 5-minute drive cycle at 1 Hz
WEEKS_DRIFT_WINDOW   = 8     # drift scenarios span ~8 simulated weeks


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def _drive_cycle_rpm(t: int, total: int) -> float:
    """Simulate a realistic RPM drive cycle: warmup → cruise → decel."""
    phase = t / total
    if phase < 0.10:                        # cold start idle
        return 800 + random.gauss(0, 20)
    elif phase < 0.25:                      # warmup ramp
        return 800 + (phase - 0.10) / 0.15 * 2200 + random.gauss(0, 50)
    elif phase < 0.60:                      # cruise ~2800 RPM
        return 2800 + 400 * math.sin(phase * 12) + random.gauss(0, 60)
    elif phase < 0.80:                      # acceleration burst
        return 3500 + 1200 * math.sin((phase - 0.60) * 8) + random.gauss(0, 80)
    else:                                   # decel / idle return
        return 2800 * (1 - (phase - 0.80) / 0.20) + 800 + random.gauss(0, 40)


def _ect_curve(t: int, total: int) -> float:
    """Engine coolant temp rises from ambient to ~90°C, stabilises."""
    phase = t / total
    if phase < 0.30:
        return 22 + 68 * (phase / 0.30) ** 0.6 + random.gauss(0, 0.5)
    return 88 + random.gauss(0, 0.8)


def _maf_from_rpm(rpm: float, tps: float) -> float:
    base = 2.5 + rpm / 6500 * 80 + tps / 100 * 40
    return max(2.0, base + random.gauss(0, 1.5))


def _o2_healthy(t: int) -> float:
    """Narrowband O2 switching ~0.5 Hz between 0.1–0.9 V."""
    return 0.45 + 0.40 * math.sin(2 * math.pi * 0.5 * t) + random.gauss(0, 0.02)


def _tps_from_rpm(rpm: float) -> float:
    return max(3, min(95, (rpm - 800) / 5700 * 70 + random.gauss(0, 2)))


def _ltft_healthy() -> float:
    return random.gauss(1.5, 1.0)


def _batt_voltage(rpm: float) -> float:
    """Alternator charges above idle; slightly lower at cranking."""
    return 13.8 + (rpm - 800) / 5700 * 0.4 + random.gauss(0, 0.05)


def _build_healthy_log(total: int, start_ts: datetime):
    logs = []
    for t in range(total):
        rpm = _drive_cycle_rpm(t, total)
        tps = _tps_from_rpm(rpm)
        entry = {
            "timestamp": (start_ts + timedelta(seconds=t)).isoformat(),
            "t": t,
            "rpm":         round(max(650, rpm), 1),
            "ect":         round(_ect_curve(t, total), 1),
            "maf":         round(_maf_from_rpm(rpm, tps), 2),
            "o2_voltage":  round(min(1.0, max(0.0, _o2_healthy(t))), 3),
            "ltft":        round(_ltft_healthy(), 2),
            "tps":         round(tps, 1),
            "can_health":  1,
            "batt_voltage":round(_batt_voltage(rpm), 2),
            "vibration_event": False,
        }
        logs.append(entry)
    return logs


# ──────────────────────────────────────────────────────────────────
# Fault injection functions (one per fault type)
# ──────────────────────────────────────────────────────────────────

def _inject_sensor_drift(logs: list, signal: str = "maf", drift_pct: float = 0.15):
    """Gradually drift signal by drift_pct over the entire log window."""
    n = len(logs)
    for i, entry in enumerate(logs):
        factor = 1.0 + drift_pct * (i / n)
        entry[signal] = round(entry[signal] * factor, 2)
    return logs


def _inject_flatline(logs: list, signal: str = "maf", pin_value: float = 0.0,
                     start_frac: float = 0.4):
    """Pin signal to a fixed value from start_frac onward (open circuit)."""
    start = int(len(logs) * start_frac)
    for entry in logs[start:]:
        entry[signal] = pin_value
    return logs


def _inject_emi_noise(logs: list, signal: str = "o2_voltage"):
    """Add RPM-correlated high-frequency noise to signal."""
    for entry in logs:
        noise_amp = 0.05 + (entry["rpm"] / 6500) * 0.15
        entry[signal] = round(
            min(1.0, max(0.0, entry[signal] + random.gauss(0, noise_amp))), 3
        )
    return logs


def _inject_stuck_actuator(logs: list, signal: str = "tps",
                            stuck_value: float = 15.0, start_frac: float = 0.35):
    """Freeze actuator output (PWM stuck at fixed duty cycle)."""
    start = int(len(logs) * start_frac)
    for entry in logs[start:]:
        entry[signal] = stuck_value
    return logs


def _inject_intermittent_dropout(logs: list, signal: str = "can_health"):
    """Signal dropout correlated with simulated vibration events."""
    vibe_windows = [(80, 120), (200, 240)]
    for entry in logs:
        t = entry["t"]
        in_vibe = any(s <= t <= e for s, e in vibe_windows)
        entry["vibration_event"] = in_vibe
        if in_vibe and random.random() < 0.70:
            entry[signal] = 0
    return logs


def _inject_low_voltage(logs: list):
    """Simulate battery/alternator failure – voltage collapses."""
    start = int(len(logs) * 0.45)
    for i, entry in enumerate(logs):
        if i >= start:
            drop = (i - start) / max(1, len(logs) - start) * 2.8
            entry["batt_voltage"] = round(max(9.5, 13.8 - drop + random.gauss(0, 0.1)), 2)
    return logs


def _inject_multi_sensor_power_fault(logs: list):
    """
    Power/ground fault: MAF AND O2 both degrade simultaneously.
    NOT independent sensor failure.
    """
    start = int(len(logs) * 0.50)
    for i, entry in enumerate(logs):
        if i >= start:
            frac = (i - start) / max(1, len(logs) - start)
            entry["maf"]        = round(entry["maf"] * (1 - frac * 0.35), 2)
            entry["o2_voltage"] = round(max(0, entry["o2_voltage"] - frac * 0.25), 3)
            entry["batt_voltage"] = round(max(10.5, entry["batt_voltage"] - frac * 1.2), 2)
    return logs


# ──────────────────────────────────────────────────────────────────
# Freeze frame snapshot
# ──────────────────────────────────────────────────────────────────

def _freeze_frame(log_entry: dict) -> dict:
    return {
        "rpm":         log_entry["rpm"],
        "ect":         log_entry["ect"],
        "maf":         log_entry["maf"],
        "ltft":        log_entry["ltft"],
        "tps":         log_entry["tps"],
        "batt_voltage":log_entry["batt_voltage"],
    }


# ──────────────────────────────────────────────────────────────────
# Waveform extraction (subsample for chart)
# ──────────────────────────────────────────────────────────────────

def _build_waveform(logs: list) -> list:
    """Return a lightweight waveform array for frontend charting (every sample)."""
    return [
        {
            "t":           e["t"],
            "timestamp":   e["timestamp"],
            "rpm":         e["rpm"],
            "ect":         e["ect"],
            "maf":         e["maf"],
            "o2_voltage":  e["o2_voltage"],
            "ltft":        e["ltft"],
            "tps":         e["tps"],
            "batt_voltage":e["batt_voltage"],
            "can_health":  e["can_health"],
            "vibration_event": e["vibration_event"],
        }
        for e in logs
    ]


# ──────────────────────────────────────────────────────────────────
# Scenario definitions  (scenario_type → injector + DTC + cause)
# ──────────────────────────────────────────────────────────────────

SCENARIO_TEMPLATES = [
    # (name, injector_fn_key, dtcs, ground_truth_cause)
    ("sensor_drift_maf",       "drift_maf",         ["P0171"],              "MAF sensor contamination/aging causing gradual 15% drift"),
    ("sensor_drift_o2",        "drift_o2",          ["P0171"],              "O2 sensor aging causing gradual drift – lean trim bias"),
    ("flatline_maf",           "flatline_maf",      ["P0171", "P0174"],     "MAF wiring open circuit – broken connector pin"),
    ("flatline_o2",            "flatline_o2",       ["P0171"],              "O2 sensor open circuit – disconnected connector"),
    ("emi_noise_o2",           "emi_o2",            ["P0300"],              "O2 sensor EMI noise from poorly shielded ignition wiring"),
    ("emi_noise_maf",          "emi_maf",           ["P0171"],              "MAF signal EMI interference near ignition coil"),
    ("stuck_tps",              "stuck_tps",         ["P0300"],              "Throttle body actuator mechanically stuck – driver transistor failure"),
    ("stuck_iac",              "stuck_maf_high",    ["P0171"],              "IAC solenoid stuck at high-flow position – mechanical failure"),
    ("intermittent_can",       "dropout_can",       ["U0100"],              "Corroded CAN bus connector – intermittent dropout with vibration"),
    ("intermittent_o2",        "dropout_o2",        ["P0300"],              "Loose O2 sensor connector – intermittent signal loss"),
    ("low_voltage_weak_batt",  "low_volt",          ["P0562"],              "Weak battery / failing alternator causing system voltage collapse"),
    ("high_voltage_reg",       "high_volt",         ["P0563"],              "Faulty voltage regulator – overcharging alternator"),
    ("multi_sensor_power",     "multi_power",       ["P0171", "P0300"],     "Common power/ground fault causing simultaneous MAF and O2 degradation"),
    ("multi_sensor_ground",    "multi_ground",      ["P0171", "U0100"],     "Corroded ground strap causing MAF + CAN bus degradation"),
    # Additional variants to reach 30+
    ("drift_maf_mild",         "drift_maf_mild",    ["P0171"],              "Early-stage MAF sensor contamination – 8% drift"),
    ("drift_ltft",             "drift_ltft",        ["P0171"],              "Fuel trim gradual positive drift – vacuum leak developing"),
    ("flatline_batt_sense",    "flatline_batt",     ["P0562"],              "Battery voltage sense wire open – incorrect voltage reading"),
    ("emi_maf_heavy",          "emi_maf_heavy",     ["P0300", "P0171"],     "Severe MAF EMI from failing ignition module"),
    ("stuck_o2_high",          "stuck_o2_high",     ["P0171"],              "O2 sensor stuck rich (0.9V) – shorted heater element"),
    ("stuck_o2_low",           "stuck_o2_low",      ["P0174"],              "O2 sensor stuck lean (0.1V) – contaminated sensor tip"),
    ("dropout_tps",            "dropout_tps",       ["P0300"],              "TPS intermittent dropout – loose harness connector"),
    ("misfire_p0301",          "misfire_cyl1",      ["P0301"],              "Cylinder 1 misfire – fouled spark plug or ignition coil failure"),
    ("misfire_p0302",          "misfire_cyl2",      ["P0302"],              "Cylinder 2 misfire – injector partial clog"),
    ("misfire_p0303",          "misfire_cyl3",      ["P0303"],              "Cylinder 3 misfire – coil-on-plug failure"),
    ("misfire_p0304",          "misfire_cyl4",      ["P0304"],              "Cylinder 4 misfire – compression low or head gasket"),
    ("misfire_random",         "misfire_random",    ["P0300"],              "Random misfire – degraded fuel pressure or ignition timing"),
    ("low_volt_alt_fail",      "low_volt_late",     ["P0562"],              "Alternator diode failure – charging dropout above 3000 RPM"),
    ("multi_sensor_ground2",   "multi_ground2",     ["P0174", "U0100"],     "Engine block ground bolt corrosion – Bank 2 and CAN degradation"),
    ("drift_ect_slow",         "drift_ect",         ["P0300"],              "ECT sensor slow drift – thermostat starting to stick closed"),
    ("flatline_tps",           "flatline_tps",      ["P0300"],              "TPS open circuit – broken potentiometer wiper"),
    ("multi_sensor_power2",    "multi_power2",      ["P0562", "U0100"],     "Battery terminal corrosion – voltage drop causing ECM comms loss"),
]


def _apply_injector(logs: list, key: str) -> list:
    """Map injector key to the right fault injection function."""
    import copy
    logs = copy.deepcopy(logs)

    if key == "drift_maf":         return _inject_sensor_drift(logs, "maf",        0.15)
    if key == "drift_maf_mild":    return _inject_sensor_drift(logs, "maf",        0.08)
    if key == "drift_o2":          return _inject_sensor_drift(logs, "o2_voltage", 0.20)
    if key == "drift_ltft":        return _inject_sensor_drift(logs, "ltft",       0.30)
    if key == "drift_ect":         return _inject_sensor_drift(logs, "ect",        0.12)
    if key == "flatline_maf":      return _inject_flatline(logs, "maf",        0.0)
    if key == "flatline_o2":       return _inject_flatline(logs, "o2_voltage", 0.0)
    if key == "flatline_batt":     return _inject_flatline(logs, "batt_voltage", 5.0)
    if key == "flatline_tps":      return _inject_flatline(logs, "tps",        0.0)
    if key == "emi_o2":            return _inject_emi_noise(logs, "o2_voltage")
    if key == "emi_maf":           return _inject_emi_noise(logs, "maf")
    if key == "emi_maf_heavy":
        logs = _inject_emi_noise(logs, "maf")
        return _inject_emi_noise(logs, "o2_voltage")
    if key == "stuck_tps":         return _inject_stuck_actuator(logs, "tps",  15.0)
    if key == "stuck_maf_high":    return _inject_stuck_actuator(logs, "maf",  18.5)
    if key == "stuck_o2_high":     return _inject_stuck_actuator(logs, "o2_voltage", 0.90)
    if key == "stuck_o2_low":      return _inject_stuck_actuator(logs, "o2_voltage", 0.10)
    if key == "dropout_can":       return _inject_intermittent_dropout(logs, "can_health")
    if key == "dropout_o2":        return _inject_intermittent_dropout(logs, "o2_voltage")
    if key == "dropout_tps":       return _inject_intermittent_dropout(logs, "tps")
    if key == "low_volt":          return _inject_low_voltage(logs)
    if key == "low_volt_late":
        import copy as _c
        logs2 = _c.deepcopy(logs)
        # voltage drops only when RPM > 3000
        for e in logs2:
            if e["rpm"] > 3000:
                e["batt_voltage"] = round(e["batt_voltage"] - 1.5 + random.gauss(0, 0.15), 2)
        return logs2
    if key == "high_volt":
        for e in logs:
            e["batt_voltage"] = round(min(15.5, e["batt_voltage"] + 1.2 + random.gauss(0, 0.1)), 2)
        return logs
    if key == "multi_power":       return _inject_multi_sensor_power_fault(logs)
    if key == "multi_power2":
        logs = _inject_low_voltage(logs)
        return _inject_intermittent_dropout(logs, "can_health")
    if key == "multi_ground":
        logs = _inject_sensor_drift(logs, "maf", 0.12)
        return _inject_intermittent_dropout(logs, "can_health")
    if key == "multi_ground2":
        logs = _inject_sensor_drift(logs, "o2_voltage", 0.15)
        return _inject_intermittent_dropout(logs, "can_health")
    if key.startswith("misfire_"):
        # Misfires show as RPM dips + O2 noise + LTFT going lean
        for e in logs[int(len(logs)*0.30):]:
            e["rpm"] = round(max(600, e["rpm"] - random.gauss(0, 120)), 1)
            e["o2_voltage"] = round(min(1.0, max(0, e["o2_voltage"] + random.gauss(0, 0.12))), 3)
            e["ltft"] = round(e["ltft"] + random.gauss(3, 1.5), 2)
        return logs

    return logs   # unknown key → no fault


def _compute_peak_fault_index(logs: list, dtcs: list) -> int:
    """Return index of the log entry that best represents fault peak."""
    return max(len(logs) // 2, len(logs) - 60)


# ──────────────────────────────────────────────────────────────────
# Main generator
# ──────────────────────────────────────────────────────────────────

def generate_healthy_scenario(scenario_id: str, start_ts: datetime) -> dict:
    logs = _build_healthy_log(SAMPLES_PER_SCENARIO, start_ts)
    return {
        "scenario_id":        scenario_id,
        "scenario_type":      "healthy",
        "dtc":                [],
        "ground_truth_cause": "No fault – healthy drive cycle",
        "logs":               logs,
        "waveform":           _build_waveform(logs),
        "freeze_frame":       None,
        "timestamp_metadata": {
            "start": start_ts.isoformat(),
            "end":   (start_ts + timedelta(seconds=SAMPLES_PER_SCENARIO - 1)).isoformat(),
            "duration_sec": SAMPLES_PER_SCENARIO,
            "vehicle_id":   "TEST_VEH_001",
            "odometer_km":  round(15000 + random.uniform(0, 80000), 0),
        },
    }


def generate_fault_scenario(scenario_id: str,
                             template: tuple,
                             start_ts: datetime) -> dict:
    name, injector_key, dtcs, gt_cause = template
    base_logs = _build_healthy_log(SAMPLES_PER_SCENARIO, start_ts)
    faulty_logs = _apply_injector(base_logs, injector_key)

    peak_idx = _compute_peak_fault_index(faulty_logs, dtcs)
    freeze = _freeze_frame(faulty_logs[peak_idx])

    return {
        "scenario_id":        scenario_id,
        "scenario_type":      name,
        "dtc":                dtcs,
        "ground_truth_cause": gt_cause,
        "logs":               faulty_logs,
        "waveform":           _build_waveform(faulty_logs),
        "freeze_frame":       freeze,
        "timestamp_metadata": {
            "start":        start_ts.isoformat(),
            "end":          (start_ts + timedelta(seconds=SAMPLES_PER_SCENARIO - 1)).isoformat(),
            "duration_sec": SAMPLES_PER_SCENARIO,
            "vehicle_id":   "TEST_VEH_001",
            "odometer_km":  round(15000 + random.uniform(0, 80000), 0),
        },
    }


def run_generation(output_dir: str = "data/scenarios"):
    os.makedirs(output_dir, exist_ok=True)
    base_time = datetime(2024, 9, 1, 8, 0, 0)
    generated = []

    # 5 healthy scenarios
    for i in range(5):
        sid = f"HEALTHY_{i+1:03d}"
        ts  = base_time + timedelta(hours=i * 6)
        scenario = generate_healthy_scenario(sid, ts)
        path = os.path.join(output_dir, f"{sid}.json")
        with open(path, "w") as f:
            json.dump(scenario, f, indent=2)
        generated.append(sid)
        print(f"[GEN] {sid} → {path}")

    # Fault scenarios
    for idx, template in enumerate(SCENARIO_TEMPLATES):
        sid = f"FAULT_{idx+1:03d}_{template[0].upper()}"
        ts  = base_time + timedelta(days=idx * 2, hours=idx % 8)
        scenario = generate_fault_scenario(sid, template, ts)
        path = os.path.join(output_dir, f"{sid}.json")
        with open(path, "w") as f:
            json.dump(scenario, f, indent=2)
        generated.append(sid)
        print(f"[GEN] {sid} → {path}  DTC={template[2]}")

    print(f"\n✓ Generated {len(generated)} scenarios ({len(SCENARIO_TEMPLATES)} fault + 5 healthy)")
    return generated


if __name__ == "__main__":
    run_generation(output_dir="data/scenarios")
