import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import WaveformChart from './components/WaveformChart';
import RootCauseCards from './components/RootCauseCards';
import FixGuidePanel from './components/FixGuidePanel';
import PredictiveAlertBanner from './components/PredictiveAlertBanner';
import PipelineLog from './components/PipelineLog';
import FeedbackWidget from './components/FeedbackWidget';
import './App.css';

const API = process.env.REACT_APP_API_URL || 'http://localhost:8000';

export default function App() {
  const [scenarios, setScenarios]           = useState([]);
  const [selectedId, setSelectedId]         = useState('');
  const [scenario, setScenario]             = useState(null);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [loading, setLoading]               = useState(false);
  const [loadingScenario, setLoadingScenario] = useState(false);
  const [error, setError]                   = useState(null);
  const [activeSignal, setActiveSignal]     = useState('maf');
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);

  // Load scenario list on mount
  useEffect(() => {
    axios.get(`${API}/scenarios`)
      .then(r => {
        setScenarios(r.data.scenarios || []);
        const firstFault = r.data.scenarios?.find(s => s.scenario_type !== 'healthy');
        if (firstFault) setSelectedId(firstFault.scenario_id);
      })
      .catch(() => setError('Cannot reach backend. Is the FastAPI server running on port 8000?'));
  }, []);

  const loadScenario = useCallback(async (id) => {
    if (!id) return;
    setLoadingScenario(true);
    setError(null);
    setAnalysisResult(null);
    setFeedbackSubmitted(false);
    try {
      const r = await axios.get(`${API}/scenario/${id}`);
      setScenario(r.data);
    } catch (e) {
      setError(`Failed to load scenario ${id}`);
    } finally {
      setLoadingScenario(false);
    }
  }, []);

  useEffect(() => { if (selectedId) loadScenario(selectedId); }, [selectedId, loadScenario]);

  const runAnalysis = async () => {
    if (!scenario) return;
    setLoading(true);
    setError(null);
    setAnalysisResult(null);
    setFeedbackSubmitted(false);
    try {
      const r = await axios.post(`${API}/analyze-scenario/${scenario.scenario_id}`);
      setAnalysisResult(r.data);
    } catch (e) {
      setError(e.response?.data?.detail || 'Analysis failed');
    } finally {
      setLoading(false);
    }
  };

  const handleFeedback = async (confirmed, notes) => {
    if (!analysisResult) return;
    try {
      await axios.post(`${API}/feedback`, {
        confirmed_correct:              confirmed,
        actual_root_cause_if_different: confirmed ? null : notes,
        engineer_notes:                 notes,
        scenario_id:                    scenario?.scenario_id,
        original_diagnosis:             analysisResult.agent1_root_causes,
        fault_signature_vector:         analysisResult.fault_signature,
      });
      setFeedbackSubmitted(true);
    } catch (e) {
      setError('Feedback submission failed');
    }
  };

  const dtcBadges = scenario?.dtc?.map(d => (
    <span key={d} className="dtc-badge">{d}</span>
  ));

  const alerts = analysisResult?.agent3_predictive?.alerts || [];
  const driftWarnings = analysisResult?.drift_warnings || [];

  return (
    <div className="app">
      {/* ── Header ──────────────────────────────────────────── */}
      <header className="app-header">
        <div className="header-left">
          <div className="logo-icon">⚙</div>
          <div>
            <h1>RootCause AI</h1>
            <span className="header-sub">ECM Diagnostic Assistant · Multi-Agent Pipeline</span>
          </div>
        </div>
        <div className="header-badges">
          <span className="tech-badge">Claude claude-sonnet-4-6</span>
          <span className="tech-badge">4-Agent Pipeline</span>
          <span className="tech-badge">Digital Twin</span>
        </div>
      </header>

      {/* ── Predictive Alert Banner ──────────────────────────── */}
      {(alerts.length > 0 || driftWarnings.length > 0) && (
        <PredictiveAlertBanner
          alerts={alerts}
          driftWarnings={driftWarnings}
          agentOutput={analysisResult?.agent3_predictive}
        />
      )}

      {/* ── Control Bar ─────────────────────────────────────── */}
      <div className="control-bar">
        <div className="control-group">
          <label className="control-label">SCENARIO / DTC</label>
          <select
            className="scenario-select"
            value={selectedId}
            onChange={e => setSelectedId(e.target.value)}
            disabled={loading}
          >
            <option value="">— Select scenario —</option>
            {scenarios.filter(s => s.scenario_type !== 'healthy').map(s => (
              <option key={s.scenario_id} value={s.scenario_id}>
                [{s.dtc?.join(', ') || '—'}]  {s.scenario_id.replace('FAULT_', '').replace(/_/g, ' ')}
              </option>
            ))}
          </select>
        </div>

        {scenario && (
          <div className="scenario-meta">
            <div className="meta-dtc">{dtcBadges}</div>
            <div className="meta-truth">
              <span className="meta-label">Ground truth:</span>
              <span className="meta-value">{scenario.ground_truth_cause}</span>
            </div>
          </div>
        )}

        <button
          className={`analyze-btn ${loading ? 'analyzing' : ''}`}
          onClick={runAnalysis}
          disabled={!scenario || loading}
        >
          {loading ? (
            <><span className="spinner" />  Running Pipeline...</>
          ) : (
            <><span className="btn-icon">▶</span> Run AI Diagnosis</>
          )}
        </button>
      </div>

      {error && <div className="error-banner">⚠ {error}</div>}

      {/* ── Waveform Chart ──────────────────────────────────── */}
      {scenario && (
        <section className="section">
          <div className="section-header">
            <h2 className="section-title">
              <span className="section-icon">〜</span> Sensor Waveform
            </h2>
            <div className="signal-tabs">
              {['maf', 'o2_voltage', 'ltft', 'rpm', 'batt_voltage', 'ect', 'tps'].map(sig => (
                <button
                  key={sig}
                  className={`signal-tab ${activeSignal === sig ? 'active' : ''}`}
                  onClick={() => setActiveSignal(sig)}
                >
                  {sig.replace('_', ' ').toUpperCase()}
                </button>
              ))}
            </div>
          </div>
          <WaveformChart
            waveform={scenario.waveform || []}
            expectedWaveform={analysisResult?.digital_twin?.expected_waveform || []}
            deviationRegions={analysisResult?.digital_twin?.deviation?.deviation_regions || []}
            signal={activeSignal}
            anomalies={analysisResult?.anomaly_summary || []}
          />
          {loadingScenario && <div className="chart-overlay">Loading scenario data...</div>}
        </section>
      )}

      {/* ── Analysis Results ─────────────────────────────────── */}
      {analysisResult && (
        <div className="analysis-grid">
          {/* Agent 1 — Root Causes */}
          <section className="section agent-section">
            <div className="section-header">
              <h2 className="section-title">
                <span className="agent-badge a1">A1</span>
                Root Cause Analysis
              </h2>
              <div className="confidence-pill">
                {analysisResult.agent1_root_causes?.overall_diagnostic_confidence}% confidence
              </div>
            </div>
            <RootCauseCards
              result={analysisResult.agent1_root_causes}
              faultSignature={analysisResult.fault_signature}
            />
            {!feedbackSubmitted ? (
              <FeedbackWidget onFeedback={handleFeedback} />
            ) : (
              <div className="feedback-done">✓ Feedback recorded — Agent 4 calibration note saved</div>
            )}
          </section>

          {/* Agent 2 — Fix Guide */}
          <section className="section agent-section">
            <div className="section-header">
              <h2 className="section-title">
                <span className="agent-badge a2">A2</span>
                Repair Guide
              </h2>
              <div className="time-pill">
                {analysisResult.agent2_fix_guide?.estimated_total_time_hr} hr est.
              </div>
            </div>
            <FixGuidePanel guide={analysisResult.agent2_fix_guide} />
          </section>
        </div>
      )}

      {/* ── Pipeline Log ─────────────────────────────────────── */}
      {analysisResult && (
        <section className="section">
          <PipelineLog
            log={analysisResult.pipeline_log}
            totalElapsed={analysisResult.total_elapsed_sec}
            anomalySummary={analysisResult.anomaly_summary}
            faultSignature={analysisResult.fault_signature}
          />
        </section>
      )}

      {/* ── Empty state ──────────────────────────────────────── */}
      {!scenario && !error && (
        <div className="empty-state">
          <div className="empty-icon">⚙</div>
          <p>Select a fault scenario above and click <strong>Run AI Diagnosis</strong></p>
          <p className="empty-sub">The pipeline will analyse sensor logs, compute the digital twin deviation, and run all 4 agents.</p>
        </div>
      )}

      {scenario && !analysisResult && !loading && (
        <div className="empty-state">
          <p>Scenario loaded — <strong>{scenario.waveform?.length || 0}</strong> waveform samples ready.</p>
          <p className="empty-sub">Click <strong>Run AI Diagnosis</strong> to start the multi-agent pipeline.</p>
        </div>
      )}
    </div>
  );
}
