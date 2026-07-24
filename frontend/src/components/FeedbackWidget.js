import React, { useState } from 'react';

export default function FeedbackWidget({ onFeedback }) {
  const [notes, setNotes] = useState('');
  const [mode, setMode]   = useState(null); // 'correct' | 'incorrect' | null

  const submit = (confirmed) => {
    onFeedback(confirmed, notes);
    setMode(confirmed ? 'correct' : 'incorrect');
  };

  if (mode) return null;  // parent shows "feedback done" message

  return (
    <div style={{
      margin: '12px 16px',
      padding: '10px 12px',
      background: '#0d1117',
      border: '1px solid #21262d',
      borderRadius: 6,
    }}>
      <div style={{ fontSize: 11, color: '#656d76', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.8 }}>
        Engineer Feedback — Agent 1 Top Diagnosis
      </div>
      <div style={{ fontSize: 12, color: '#8b949e', marginBottom: 10 }}>
        Was the top root cause correct? Your feedback trains Agent 4's calibration loop.
      </div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
        <button
          onClick={() => submit(true)}
          style={{
            background: 'rgba(63,185,80,0.12)', border: '1px solid rgba(63,185,80,0.3)',
            color: '#3fb950', padding: '6px 16px', borderRadius: 5,
            cursor: 'pointer', fontSize: 13, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6
          }}
        >
          👍 Correct
        </button>
        <button
          onClick={() => {
            if (notes || window.confirm('Submit without notes?')) submit(false);
          }}
          style={{
            background: 'rgba(248,81,73,0.1)', border: '1px solid rgba(248,81,73,0.3)',
            color: '#f85149', padding: '6px 16px', borderRadius: 5,
            cursor: 'pointer', fontSize: 13, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6
          }}
        >
          👎 Incorrect
        </button>
      </div>
      <textarea
        value={notes}
        onChange={e => setNotes(e.target.value)}
        placeholder="Optional: what was the actual root cause?"
        style={{
          width: '100%', background: '#161b22', border: '1px solid #30363d',
          color: '#c9d1d9', borderRadius: 4, padding: '6px 8px', fontSize: 12,
          resize: 'vertical', minHeight: 48, fontFamily: 'inherit',
        }}
      />
    </div>
  );
}
