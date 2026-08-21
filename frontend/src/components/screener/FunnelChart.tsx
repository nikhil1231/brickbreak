import React from 'react';

interface FunnelChartProps {
  meanPerStage: Record<string, number>;
}

export const FunnelChart: React.FC<FunnelChartProps> = ({ meanPerStage }) => {
  const stages = Object.keys(meanPerStage);
  if (!stages.length) return <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>No stage data</div>;

  const top = meanPerStage[stages[0]] || 1;

  const formatNumber = (v: number) => {
    if (v == null || isNaN(v)) return '—';
    return v >= 1000 ? v.toLocaleString(undefined, { maximumFractionDigits: 0 }) : v.toFixed(1);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
      {stages.map((stage) => {
        const val = meanPerStage[stage] || 0;
        const pct = ((val / top) * 100).toFixed(1);
        const widthPct = Math.max(0.5, (val / top) * 100);

        return (
          <div
            key={stage}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              fontSize: '12px',
            }}
          >
            <div
              style={{
                width: '130px',
                color: 'var(--text-muted)',
                flexShrink: 0,
                textTransform: 'capitalize',
              }}
            >
              {stage.replace(/_/g, ' ')}
            </div>
            <div
              style={{
                flex: 1,
                background: 'var(--bg-main)',
                border: '1px solid var(--border)',
                borderRadius: '4px',
                height: '20px',
                position: 'relative',
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  height: '100%',
                  width: `${widthPct}%`,
                  background: 'linear-gradient(90deg, var(--accent), #5fbfa4)',
                  borderRadius: '3px',
                  transition: 'width 0.2s ease',
                }}
              />
            </div>
            <div
              className="tabular-nums"
              style={{
                width: '65px',
                textAlign: 'right',
                fontWeight: 600,
                color: 'var(--text-bright)',
              }}
            >
              {formatNumber(val)}
            </div>
            <div
              className="tabular-nums"
              style={{
                width: '50px',
                textAlign: 'right',
                color: 'var(--text-muted)',
                fontSize: '11px',
              }}
            >
              {pct}%
            </div>
          </div>
        );
      })}
    </div>
  );
};
