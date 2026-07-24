import React, { useMemo } from 'react';
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
  ReferenceArea,
} from 'recharts';

const SIGNAL_CONFIG = {
  maf:         { label: 'MAF',          unit: 'g/s',  color: '#58a6ff', expectedColor: '#1f6feb', domain: [0, 30]   },
  o2_voltage:  { label: 'O2 Voltage',   unit: 'V',    color: '#3fb950', expectedColor: '#238636', domain: [0, 1.05] },
  ltft:        { label: 'LTFT',         unit: '%',    color: '#d29922', expectedColor: '#9e6a03', domain: [-30, 30] },
  rpm:         { label: 'RPM',          unit: 'RPM',  color: '#bc8cff', expectedColor: '#8957e5', domain: [0, 7000] },
  batt_voltage:{ label: 'Battery V',    unit: 'V',    color: '#79c0ff', expectedColor: '#388bfd', domain: [9, 16]   },
  ect:         { label: 'Coolant Temp', unit: '°C',   color: '#f85149', expectedColor: '#b91c1c', domain: [0, 130]  },
  tps:         { label: 'TPS',          unit: '%',    color: '#e3823e', expectedColor: '#b45309', domain: [0, 105]  },
  can_health:  { label: 'CAN Health',   unit: '',     color: '#39d353', expectedColor: '#1a7f37', domain: [-0.1, 1.2]},
};

const CustomTooltip = ({ active, payload, label, signal }) => {
  if (!active || !payload?.length) return null;
  const cfg = SIGNAL_CONFIG[signal] || { unit: '' };
  return (
    <div style={{
      background: '#1c2128', border: '1px solid #30363d', borderRadius: 6,
      padding: '8px 12px', fontSize: 11, fontFamily: 'monospace'
    }}>
      <div style={{ color: '#8b949e', marginBottom: 4 }}>t = {label}s</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color, lineHeight: 1.8 }}>
          {p.name}: <strong>{typeof p.value === 'number' ? p.value.toFixed(3) : p.value}</strong> {cfg.unit}
        </div>
      ))}
    </div>
  );
};

export default function WaveformChart({ waveform, expectedWaveform, deviationRegions, signal, anomalies }) {
  const cfg = SIGNAL_CONFIG[signal] || { label: signal, unit: '', color: '#58a6ff', domain: ['auto', 'auto'] };

  // Merge actual + expected into one dataset for Recharts
  const chartData = useMemo(() => {
    const expMap = {};
    (expectedWaveform || []).forEach(e => { expMap[e.t] = e[signal]; });
    return (waveform || []).map(w => ({
      t:        w.t,
      actual:   w[signal],
      expected: expMap[w.t] !== undefined ? expMap[w.t] : null,
      vibration:w.vibration_event ? (cfg.domain?.[1] || 1) * 0.05 : null,
    }));
  }, [waveform, expectedWaveform, signal]);

  // Signal-specific anomaly regions
  const signalRegions = useMemo(() =>
    (deviationRegions || []).filter(r => r.signal === signal),
    [deviationRegions, signal]
  );

  // Top anomalies for this signal
  const signalAnomalies = useMemo(() =>
    (anomalies || [])
      .filter(a => a.signal_name === signal)
      .sort((a, b) => b.severity_score - a.severity_score)
      .slice(0, 3),
    [anomalies, signal]
  );

  const [yMin, yMax] = cfg.domain || ['auto', 'auto'];

  return (
    <div style={{ padding: '12px 8px' }}>
      {signalAnomalies.length > 0 && (
        <div style={{ display: 'flex', gap: 8, padding: '4px 8px 10px', flexWrap: 'wrap' }}>
          {signalAnomalies.map((a, i) => (
            <div key={i} style={{
              background: `rgba(${a.severity_score > 0.7 ? '248,81,73' : a.severity_score > 0.4 ? '210,153,34' : '63,185,80'}, 0.12)`,
              border: `1px solid rgba(${a.severity_score > 0.7 ? '248,81,73' : a.severity_score > 0.4 ? '210,153,34' : '63,185,80'}, 0.35)`,
              borderRadius: 4, padding: '2px 8px', fontSize: 10, fontFamily: 'monospace',
              color: a.severity_score > 0.7 ? '#f85149' : a.severity_score > 0.4 ? '#d29922' : '#3fb950'
            }}>
              {a.anomaly_type.replace(/_/g, ' ')} [{(a.severity_score * 100).toFixed(0)}%]
            </div>
          ))}
        </div>
      )}

      <ResponsiveContainer width="100%" height={240}>
        <ComposedChart data={chartData} margin={{ top: 8, right: 20, left: 0, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#21262d" />
          <XAxis
            dataKey="t"
            tick={{ fill: '#656d76', fontSize: 10, fontFamily: 'monospace' }}
            tickLine={false}
            axisLine={{ stroke: '#30363d' }}
            label={{ value: 'Time (s)', position: 'insideBottomRight', fill: '#656d76', fontSize: 10 }}
          />
          <YAxis
            domain={[yMin, yMax]}
            tick={{ fill: '#656d76', fontSize: 10, fontFamily: 'monospace' }}
            tickLine={false}
            axisLine={{ stroke: '#30363d' }}
            label={{ value: `${cfg.label} (${cfg.unit})`, angle: -90, position: 'insideLeft', fill: '#656d76', fontSize: 10 }}
            width={55}
          />
          <Tooltip content={<CustomTooltip signal={signal} />} />
          <Legend
            formatter={(v) => <span style={{ color: '#8b949e', fontSize: 11, fontFamily: 'monospace' }}>{v}</span>}
          />

          {/* Shade deviation regions (digital twin) */}
          {signalRegions.map((r, i) => (
            <ReferenceArea
              key={i}
              x1={r.start_t}
              x2={r.end_t}
              fill="rgba(248,81,73,0.08)"
              stroke="rgba(248,81,73,0.3)"
              strokeWidth={1}
            />
          ))}

          {/* LTFT ±10% threshold lines */}
          {signal === 'ltft' && (
            <>
              <ReferenceLine y={10}  stroke="rgba(248,81,73,0.5)" strokeDasharray="5 3" label={{ value: '+10%', fill: '#f85149', fontSize: 9 }} />
              <ReferenceLine y={-10} stroke="rgba(248,81,73,0.5)" strokeDasharray="5 3" label={{ value: '-10%', fill: '#f85149', fontSize: 9 }} />
            </>
          )}
          {signal === 'batt_voltage' && (
            <ReferenceLine y={11.5} stroke="rgba(248,81,73,0.5)" strokeDasharray="5 3" label={{ value: 'P0562', fill: '#f85149', fontSize: 9 }} />
          )}

          {/* Expected waveform (digital twin) */}
          {expectedWaveform.length > 0 && (
            <Line
              type="monotone"
              dataKey="expected"
              stroke={cfg.expectedColor}
              strokeDasharray="5 3"
              strokeWidth={1.5}
              dot={false}
              name="Expected (Twin)"
              connectNulls={false}
            />
          )}

          {/* Actual signal */}
          <Line
            type="monotone"
            dataKey="actual"
            stroke={cfg.color}
            strokeWidth={2}
            dot={false}
            name={`Actual — ${cfg.label}`}
            activeDot={{ r: 4, fill: cfg.color }}
          />
        </ComposedChart>
      </ResponsiveContainer>

      {signalRegions.length > 0 && (
        <div style={{ fontSize: 10, color: '#8b949e', padding: '4px 8px', fontFamily: 'monospace' }}>
          ⚠ {signalRegions.length} deviation region(s) highlighted in red — actual diverges from digital twin expected
        </div>
      )}
    </div>
  );
}
