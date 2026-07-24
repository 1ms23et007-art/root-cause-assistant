import React, { useState } from 'react';

const CONF_COLOR = (score) => {
  if (score >= 70) return '#3fb950';
  if (score >= 45) return '#d29922';
  return '#f85149';
};

const CONF_BG = (score) => {
  if (score >= 70) return 'rgba(63,185,80,0.12)';
  if (score >= 45) return 'rgba(210,153,34,0.12)';
  return 'rgba(248,81,73,0.12)';
};

export default function RootCauseCards({ result, faultSignature }) {
  const [expanded, setExpanded] = useState(0);

  const causes = result?.ranked_causes || [];
  const ambiguity = result?.ambiguity_note;
  const firstAction = result?.recommended_first_action;

  if (!causes.length) {
    return <div style={{ padding: 16, color: '#8b949e', fontSize: 13 }}>No root causes generated.</div>;
  }

  return (
    <div style={{ padding: '12px 16px' }}>
      {/* Ambiguity note */}
      {ambiguity && (
        <div style={{
          background: 'rgba(210,153,34,0.1)', border: '1px solid rgba(210,153,34,0.3)',
          borderRadius: 5, padding: '8px 12px', marginBottom: 12, fontSize: 12, color: '#d29922'
        }}>
          ⚠ Ambiguity: {ambiguity}
        </div>
      )}

      {/* Cause cards */}
      {causes.map((cause, idx) => {
        const isOpen = expanded === idx;
        const color  = CONF_COLOR(cause.confidence_score);
        const bg     = CONF_BG(cause.confidence_score);
        return (
          <div
            key={idx}
            style={{
              background: isOpen ? 'rgba(22,27,34,0.8)' : 'var(--bg-raised,#1c2128)',
              border: `1px solid ${isOpen ? color : '#30363d'}`,
              borderRadius: 6,
              marginBottom: 8,
              overflow: 'hidden',
              transition: 'border-color 0.15s',
            }}
          >
            {/* Card header */}
            <div
              onClick={() => setExpanded(isOpen ? -1 : idx)}
              style={{
                display: 'flex', alignItems: 'center', gap: 12,
                padding: '10px 14px', cursor: 'pointer',
                userSelect: 'none',
              }}
            >
              <div style={{
                background: bg, color, width: 26, height: 26,
                borderRadius: 4, display: 'flex', alignItems: 'center',
                justifyContent: 'center', fontFamily: 'monospace', fontWeight: 800, fontSize: 12,
                flexShrink: 0,
              }}>
                #{cause.rank}
              </div>

              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#e6edf3', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {cause.cause}
                </div>
              </div>

              {/* Confidence bar */}
              <div style={{ flexShrink: 0, textAlign: 'right' }}>
                <div style={{ fontSize: 16, fontWeight: 700, color, fontFamily: 'monospace' }}>
                  {cause.confidence_score}%
                </div>
                <div style={{
                  width: 80, height: 4, background: '#21262d', borderRadius: 2, marginTop: 3
                }}>
                  <div style={{
                    width: `${cause.confidence_score}%`, height: '100%',
                    background: color, borderRadius: 2
                  }} />
                </div>
              </div>

              <div style={{ color: '#656d76', fontSize: 12, flexShrink: 0 }}>
                {isOpen ? '▲' : '▼'}
              </div>
            </div>

            {/* Expanded reasoning trace */}
            {isOpen && (
              <div style={{ borderTop: '1px solid #21262d', padding: '12px 14px', fontSize: 12 }}>
                {/* Supporting evidence */}
                {cause.supporting_evidence?.length > 0 && (
                  <div style={{ marginBottom: 14 }}>
                    <div style={{ fontSize: 10, color: '#656d76', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>
                      Supporting Evidence
                    </div>
                    {cause.supporting_evidence.map((ev, i) => (
                      <div key={i} style={{
                        display: 'flex', gap: 8, alignItems: 'flex-start',
                        marginBottom: 4, color: '#8b949e'
                      }}>
                        <span style={{ color: '#3fb950', flexShrink: 0 }}>●</span>
                        <span>{ev}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Reasoning chain */}
                {cause.reasoning_chain?.length > 0 && (
                  <div style={{ marginBottom: 14 }}>
                    <div style={{ fontSize: 10, color: '#656d76', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>
                      Reasoning Chain
                    </div>
                    {cause.reasoning_chain.map((step, i) => (
                      <div key={i} style={{
                        display: 'flex', gap: 10, alignItems: 'flex-start',
                        marginBottom: 6, color: '#c9d1d9'
                      }}>
                        <div style={{
                          background: 'rgba(88,166,255,0.15)', color: '#58a6ff',
                          width: 20, height: 20, borderRadius: 3,
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          fontFamily: 'monospace', fontSize: 10, fontWeight: 700, flexShrink: 0
                        }}>
                          {i + 1}
                        </div>
                        <span style={{ paddingTop: 1 }}>{step}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Ruled out alternatives */}
                {cause.ruled_out_alternatives?.length > 0 && (
                  <div style={{ marginBottom: 14 }}>
                    <div style={{ fontSize: 10, color: '#656d76', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>
                      Ruled-Out Alternatives
                    </div>
                    {cause.ruled_out_alternatives.map((alt, i) => (
                      <div key={i} style={{
                        display: 'flex', gap: 8, alignItems: 'flex-start',
                        marginBottom: 4, color: '#656d76',
                        textDecoration: 'line-through',
                      }}>
                        <span style={{ color: '#f85149', flexShrink: 0, textDecoration: 'none' }}>✕</span>
                        <span style={{ textDecoration: 'none', color: '#656d76' }}>{alt}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Further testing */}
                {cause.requires_further_testing?.length > 0 && (
                  <div>
                    <div style={{ fontSize: 10, color: '#656d76', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>
                      Requires Further Testing
                    </div>
                    {cause.requires_further_testing.map((test, i) => (
                      <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 4, color: '#d29922' }}>
                        <span>→</span><span>{test}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}

      {/* First action recommendation */}
      {firstAction && (
        <div style={{
          background: 'rgba(88,166,255,0.08)', border: '1px solid rgba(88,166,255,0.25)',
          borderRadius: 5, padding: '8px 12px', marginTop: 4, fontSize: 12, color: '#79c0ff'
        }}>
          <strong>Recommended first action:</strong> {firstAction}
        </div>
      )}

      {/* Fault signature summary */}
      {faultSignature && (
        <div style={{ marginTop: 12, padding: '8px 12px', background: '#0d1117', borderRadius: 5, fontSize: 11, fontFamily: 'monospace' }}>
          <span style={{ color: '#656d76' }}>Pattern: </span>
          <span style={{ color: '#bc8cff' }}>{faultSignature.timing_pattern}</span>
          <span style={{ color: '#30363d', margin: '0 8px' }}>|</span>
          <span style={{ color: '#656d76' }}>Severity: </span>
          <span style={{ color: '#d29922' }}>{(faultSignature.overall_severity * 100).toFixed(0)}%</span>
          <span style={{ color: '#30363d', margin: '0 8px' }}>|</span>
          <span style={{ color: '#656d76' }}>Signals: </span>
          <span style={{ color: '#8b949e' }}>{faultSignature.affected_signals?.join(', ')}</span>
        </div>
      )}
    </div>
  );
}
