import React, { useState } from 'react';

const PHASE_COLORS = {
  1: { color: '#3fb950', bg: 'rgba(63,185,80,0.12)', label: 'Quick Checks' },
  2: { color: '#d29922', bg: 'rgba(210,153,34,0.12)', label: 'Electrical / Sensor Tests' },
  3: { color: '#f85149', bg: 'rgba(248,81,73,0.12)', label: 'Component Replacement' },
};

export default function FixGuidePanel({ guide }) {
  const [checked, setChecked] = useState({});

  if (!guide || !guide.steps?.length) {
    return <div style={{ padding: 16, color: '#8b949e', fontSize: 13 }}>No repair guide available.</div>;
  }

  const toggle = (idx) => setChecked(prev => ({ ...prev, [idx]: !prev[idx] }));

  const completedCount = Object.values(checked).filter(Boolean).length;
  const totalSteps     = guide.steps.length;

  return (
    <div style={{ padding: '12px 16px' }}>
      {/* Progress bar */}
      <div style={{ marginBottom: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5, fontSize: 11, color: '#8b949e' }}>
          <span>Repair Progress</span>
          <span style={{ fontFamily: 'monospace' }}>{completedCount}/{totalSteps} steps</span>
        </div>
        <div style={{ background: '#21262d', borderRadius: 4, height: 5 }}>
          <div style={{
            width: `${(completedCount / totalSteps) * 100}%`, height: '100%',
            background: completedCount === totalSteps ? '#3fb950' : '#58a6ff',
            borderRadius: 4, transition: 'width 0.3s'
          }} />
        </div>
      </div>

      {/* Repair target */}
      {guide.repair_target && (
        <div style={{ marginBottom: 14, fontSize: 13, color: '#c9d1d9', padding: '6px 10px', background: '#0d1117', borderRadius: 4 }}>
          <strong style={{ color: '#8b949e', fontSize: 10, textTransform: 'uppercase', letterSpacing: 1 }}>Target: </strong>
          {guide.repair_target}
        </div>
      )}

      {/* Steps */}
      {guide.steps.map((step, idx) => {
        const phaseInfo = PHASE_COLORS[step.phase] || PHASE_COLORS[3];
        const done      = checked[idx];
        return (
          <div
            key={idx}
            onClick={() => toggle(idx)}
            style={{
              display: 'flex', gap: 12, padding: '10px 12px',
              background: done ? 'rgba(63,185,80,0.05)' : 'var(--bg-raised,#1c2128)',
              border: `1px solid ${done ? 'rgba(63,185,80,0.2)' : '#21262d'}`,
              borderRadius: 6, marginBottom: 6, cursor: 'pointer',
              opacity: done ? 0.65 : 1, transition: 'all 0.15s',
            }}
          >
            {/* Checkbox */}
            <div style={{
              width: 20, height: 20, border: `2px solid ${done ? '#3fb950' : '#484f58'}`,
              borderRadius: 4, flexShrink: 0, display: 'flex', alignItems: 'center',
              justifyContent: 'center', background: done ? '#3fb950' : 'transparent',
              marginTop: 1, transition: 'all 0.15s',
            }}>
              {done && <span style={{ color: '#0d1117', fontSize: 12, fontWeight: 900 }}>✓</span>}
            </div>

            {/* Content */}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
                <span style={{
                  background: phaseInfo.bg, color: phaseInfo.color,
                  fontSize: 9, fontFamily: 'monospace', fontWeight: 700,
                  padding: '1px 6px', borderRadius: 3, letterSpacing: 0.5,
                  textTransform: 'uppercase', flexShrink: 0,
                }}>
                  P{step.phase}
                </span>
                <span style={{ fontSize: 11, color: '#656d76', fontFamily: 'monospace' }}>
                  Step {step.step_number}
                </span>
                {step.est_time_min && (
                  <span style={{ fontSize: 10, color: '#484f58', marginLeft: 'auto' }}>
                    ~{step.est_time_min} min
                  </span>
                )}
              </div>

              <div style={{
                fontSize: 13, color: done ? '#656d76' : '#c9d1d9',
                textDecoration: done ? 'line-through' : 'none', marginBottom: 6
              }}>
                {step.action}
              </div>

              {!done && (
                <>
                  {step.tool_required && (
                    <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 3 }}>
                      <span style={{ color: '#58a6ff' }}>🔧 </span>{step.tool_required}
                    </div>
                  )}
                  {step.expected_outcome && (
                    <div style={{ fontSize: 11, color: '#3fb950' }}>
                      <span>✓ </span>{step.expected_outcome}
                    </div>
                  )}
                  {step.confirm_before_replace && (
                    <div style={{
                      marginTop: 6, padding: '5px 8px',
                      background: 'rgba(210,153,34,0.1)', border: '1px solid rgba(210,153,34,0.25)',
                      borderRadius: 4, fontSize: 11, color: '#d29922'
                    }}>
                      ⚠ Confirm before replace: {step.confirm_before_replace}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        );
      })}

      {/* Safety notes */}
      {guide.safety_notes?.length > 0 && (
        <div style={{
          marginTop: 12, padding: '10px 12px',
          background: 'rgba(248,81,73,0.06)', border: '1px solid rgba(248,81,73,0.2)',
          borderRadius: 5,
        }}>
          <div style={{ fontSize: 10, color: '#656d76', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>
            Safety Notes
          </div>
          {guide.safety_notes.map((note, i) => (
            <div key={i} style={{ fontSize: 12, color: '#f85149', marginBottom: 3 }}>
              ⚠ {note}
            </div>
          ))}
        </div>
      )}

      {/* Tools */}
      {guide.tools_required?.length > 0 && (
        <div style={{ marginTop: 10, fontSize: 11, color: '#656d76' }}>
          <strong style={{ color: '#484f58', fontSize: 10, textTransform: 'uppercase', letterSpacing: 1 }}>Tools needed: </strong>
          {guide.tools_required.join(' · ')}
        </div>
      )}

      {/* Success criteria */}
      {guide.success_criteria && (
        <div style={{
          marginTop: 10, padding: '8px 12px',
          background: 'rgba(63,185,80,0.06)', border: '1px solid rgba(63,185,80,0.2)',
          borderRadius: 5, fontSize: 12, color: '#3fb950'
        }}>
          <strong>✓ Success: </strong>{guide.success_criteria}
        </div>
      )}
    </div>
  );
}
