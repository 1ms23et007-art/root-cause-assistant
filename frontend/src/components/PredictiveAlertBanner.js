import React, { useState } from 'react';

const URGENCY_CONFIG = {
  high:   { bg: 'rgba(248,81,73,0.12)',   border: 'rgba(248,81,73,0.35)',   color: '#f85149', icon: '🔴', label: 'HIGH' },
  medium: { bg: 'rgba(210,153,34,0.12)',  border: 'rgba(210,153,34,0.35)', color: '#d29922', icon: '🟡', label: 'MEDIUM' },
  low:    { bg: 'rgba(63,185,80,0.08)',   border: 'rgba(63,185,80,0.25)',  color: '#3fb950', icon: '🟢', label: 'LOW' },
};

export default function PredictiveAlertBanner({ alerts, driftWarnings, agentOutput }) {
  const [expanded, setExpanded] = useState(false);

  if (!alerts?.length && !driftWarnings?.length) return null;

  const topUrgency = alerts?.some(a => a.urgency_level === 'high') ? 'high'
    : alerts?.some(a => a.urgency_level === 'medium') ? 'medium' : 'low';
  const cfg = URGENCY_CONFIG[topUrgency];

  return (
    <div style={{
      background: cfg.bg, borderBottom: `2px solid ${cfg.border}`,
      padding: '10px 24px', position: 'relative',
    }}>
      <div
        onClick={() => setExpanded(e => !e)}
        style={{ display: 'flex', alignItems: 'center', gap: 12, cursor: 'pointer' }}
      >
        <div style={{
          background: `rgba(${topUrgency === 'high' ? '248,81,73' : topUrgency === 'medium' ? '210,153,34' : '63,185,80'}, 0.2)`,
          color: cfg.color, fontSize: 10, fontFamily: 'monospace', fontWeight: 800,
          padding: '3px 8px', borderRadius: 3, letterSpacing: 1,
        }}>
          {cfg.icon} A3 · PREDICTIVE · {cfg.label}
        </div>

        <div style={{ flex: 1, fontSize: 13, color: cfg.color, fontWeight: 600 }}>
          {agentOutput?.summary_for_manager || `${alerts?.length || driftWarnings?.length} pre-failure drift signal(s) detected — preventive action recommended`}
        </div>

        <div style={{ fontSize: 12, color: cfg.color }}>
          {expanded ? '▲ collapse' : '▼ details'}
        </div>
      </div>

      {expanded && (
        <div style={{ marginTop: 12, display: 'grid', gap: 8, gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
          {(alerts?.length ? alerts : []).map((alert, i) => {
            const ac = URGENCY_CONFIG[alert.urgency_level] || cfg;
            return (
              <div key={i} style={{
                background: '#0d1117', border: `1px solid ${ac.border}`,
                borderRadius: 6, padding: '10px 12px',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                  <span style={{ color: ac.color, fontFamily: 'monospace', fontSize: 11, fontWeight: 700 }}>
                    {alert.signal?.replace(/_/g, ' ').toUpperCase()}
                  </span>
                  <span style={{
                    background: ac.bg, color: ac.color, fontSize: 9,
                    padding: '1px 6px', borderRadius: 3, fontFamily: 'monospace', letterSpacing: 0.5
                  }}>
                    {alert.urgency_level?.toUpperCase()}
                  </span>
                </div>
                <p style={{ fontSize: 12, color: '#c9d1d9', marginBottom: 6 }}>{alert.alert_summary}</p>
                <p style={{ fontSize: 11, color: '#8b949e', marginBottom: 6 }}>{alert.why_it_matters}</p>
                <div style={{
                  background: 'rgba(88,166,255,0.08)', border: '1px solid rgba(88,166,255,0.2)',
                  borderRadius: 4, padding: '5px 8px', fontSize: 11, color: '#79c0ff'
                }}>
                  → {alert.recommended_action}
                </div>
                <div style={{ marginTop: 6, fontSize: 10, color: '#656d76', fontFamily: 'monospace' }}>
                  ETA: {alert.estimated_time_to_threshold} · DTC: {alert.related_dtc}
                </div>
              </div>
            );
          })}

          {/* Raw drift warnings if no agent3 output */}
          {!alerts?.length && driftWarnings.map((w, i) => {
            const ac = URGENCY_CONFIG[w.urgency] || cfg;
            return (
              <div key={i} style={{
                background: '#0d1117', border: `1px solid ${ac.border}`,
                borderRadius: 6, padding: '10px 12px',
              }}>
                <div style={{ color: ac.color, fontFamily: 'monospace', fontSize: 11, fontWeight: 700, marginBottom: 4 }}>
                  {w.signal?.replace(/_/g, ' ').toUpperCase()} — {w.urgency?.toUpperCase()}
                </div>
                <p style={{ fontSize: 12, color: '#c9d1d9', marginBottom: 4 }}>{w.description}</p>
                <div style={{ fontSize: 11, color: '#8b949e', fontFamily: 'monospace' }}>
                  Current: {w.current_value} → Fault at {w.fault_threshold} {w.unit}
                  &nbsp;· Est. {w.estimated_km_to_fault} km
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
