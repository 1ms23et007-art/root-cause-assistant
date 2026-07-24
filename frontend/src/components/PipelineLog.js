import React, { useState } from 'react';

const STAGE_ICONS = {
  1: '📡', 2: '🔮', 3: '🔗', 4: '🤖', 5: '🔧', '6a': '📈', '6b': '⚠',
};

export default function PipelineLog({ log, totalElapsed, anomalySummary, faultSignature }) {
  const [showRaw, setShowRaw] = useState(false);

  if (!log?.length) return null;

  return (
    <div>
      <div className="section-header">
        <h2 className="section-title">
          <span className="section-icon">⚡</span> Pipeline Execution Log
        </h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 11, fontFamily: 'monospace', color: '#8b949e' }}>
            Total: {totalElapsed}s
          </span>
          <button
            onClick={() => setShowRaw(r => !r)}
            style={{
              background: 'transparent', border: '1px solid #30363d',
              color: '#8b949e', fontSize: 10, padding: '2px 8px',
              borderRadius: 4, cursor: 'pointer', fontFamily: 'monospace'
            }}
          >
            {showRaw ? 'hide raw' : 'raw JSON'}
          </button>
        </div>
      </div>

      <div style={{ padding: '12px 16px' }}>
        {/* Pipeline stages */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {log.map((stage, i) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', gap: 12,
              padding: '8px 12px', background: '#0d1117', borderRadius: 5,
              border: '1px solid #21262d',
            }}>
              <div style={{ fontSize: 16, flexShrink: 0 }}>
                {STAGE_ICONS[stage.stage] || '▸'}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: '#e6edf3' }}>
                  Stage {stage.stage} — {stage.name}
                </div>
                <div style={{ fontSize: 11, color: '#656d76', fontFamily: 'monospace', marginTop: 2 }}>
                  {Object.entries(stage)
                    .filter(([k]) => !['stage', 'name'].includes(k))
                    .map(([k, v]) => `${k}: ${JSON.stringify(v)}`)
                    .join('  ·  ')}
                </div>
              </div>
              <div style={{ color: '#3fb950', fontSize: 14, flexShrink: 0 }}>✓</div>
            </div>
          ))}
        </div>

        {/* Top anomalies table */}
        {anomalySummary?.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: 10, color: '#656d76', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>
              Top Anomalies Detected
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontFamily: 'monospace' }}>
                <thead>
                  <tr style={{ background: '#1c2128' }}>
                    {['Signal', 'Anomaly Type', 'Severity', 'Duration (s)', 'Detail'].map(h => (
                      <th key={h} style={{ padding: '5px 10px', textAlign: 'left', color: '#656d76', fontWeight: 600, borderBottom: '1px solid #21262d' }}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {anomalySummary.slice(0, 10).map((a, i) => {
                    const sev = a.severity_score;
                    const sevColor = sev > 0.7 ? '#f85149' : sev > 0.4 ? '#d29922' : '#3fb950';
                    return (
                      <tr key={i} style={{ borderBottom: '1px solid #161b22' }}>
                        <td style={{ padding: '4px 10px', color: '#58a6ff' }}>{a.signal_name}</td>
                        <td style={{ padding: '4px 10px', color: '#c9d1d9' }}>{a.anomaly_type.replace(/_/g, ' ')}</td>
                        <td style={{ padding: '4px 10px', color: sevColor, fontWeight: 700 }}>{(sev * 100).toFixed(0)}%</td>
                        <td style={{ padding: '4px 10px', color: '#8b949e' }}>{a.duration_sec}</td>
                        <td style={{ padding: '4px 10px', color: '#8b949e', maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {a.detail}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Raw FSV */}
        {showRaw && faultSignature && (
          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 10, color: '#656d76', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>
              Fault Signature Vector (raw)
            </div>
            <pre style={{
              background: '#0d1117', border: '1px solid #21262d', borderRadius: 5,
              padding: 12, fontSize: 10, color: '#8b949e', overflow: 'auto',
              maxHeight: 300, fontFamily: 'monospace', lineHeight: 1.6
            }}>
              {JSON.stringify(faultSignature, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
