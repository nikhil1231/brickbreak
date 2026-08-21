import React, { useRef, useState } from 'react';

interface TimeSeriesChartProps {
  dates: string[];
  values: number[];
  selectedDate?: string;
  onSelectDate: (date: string) => void;
}

export const TimeSeriesChart: React.FC<TimeSeriesChartProps> = ({
  dates,
  values,
  selectedDate,
  onSelectDate,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const n = dates?.length || 0;
  if (!n || !values?.length) {
    return <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>No timeline data available</div>;
  }

  const W = 1000;
  const H = 180;
  const PL = 44;
  const PB = 26;
  const PT = 10;
  const PR = 12;

  const mx = Math.max(1, ...values);
  const x = (i: number) => PL + (i / (n - 1 || 1)) * (W - PL - PR);
  const y = (k: number) => PT + (1 - k / mx) * (H - PT - PB);

  const points = values.map((k, i) => `${x(i).toFixed(1)},${y(k).toFixed(1)}`).join(' ');

  const ticks = [0, Math.round(mx / 2), mx];
  const labelIndices = [0, Math.floor(n / 4), Math.floor(n / 2), Math.floor((3 * n) / 4), n - 1];

  const handleMouseMove = (e: React.MouseEvent<SVGRectElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const pos = (e.clientX - rect.left) / rect.width;
    const idx = Math.max(0, Math.min(n - 1, Math.round(pos * (n - 1))));
    setHoverIndex(idx);
  };

  const handleMouseLeave = () => {
    setHoverIndex(null);
  };

  const handleClick = (e: React.MouseEvent<SVGRectElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const pos = (e.clientX - rect.left) / rect.width;
    const idx = Math.max(0, Math.min(n - 1, Math.round(pos * (n - 1))));
    if (dates[idx]) {
      onSelectDate(dates[idx]);
    }
  };

  const selectedIndex = selectedDate ? dates.indexOf(selectedDate) : -1;
  const activeIndex = hoverIndex ?? (selectedIndex >= 0 ? selectedIndex : null);

  return (
    <div ref={containerRef} style={{ width: '100%', position: 'relative' }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: '100%', height: '180px', display: 'block', overflow: 'visible' }}
      >
        {/* Horizontal grid lines & Y-axis labels */}
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={PL}
              x2={W - PR}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--grid-line)"
              strokeDasharray="2,2"
            />
            <text
              x={PL - 8}
              y={y(t) + 3.5}
              textAnchor="end"
              fontSize="10"
              fill="var(--text-muted)"
              className="tabular-nums font-mono"
            >
              {t}
            </text>
          </g>
        ))}

        {/* X-axis date labels */}
        {labelIndices.map((i) => (
          <text
            key={i}
            x={x(i)}
            y={H - 6}
            textAnchor="middle"
            fontSize="10"
            fill="var(--text-muted)"
            className="tabular-nums font-mono"
          >
            {dates[i]}
          </text>
        ))}

        {/* Area fill */}
        <polygon
          points={`${x(0)},${H - PB} ${points} ${x(n - 1)},${H - PB}`}
          fill="rgba(88, 166, 255, 0.08)"
        />

        {/* Polyline series */}
        <polyline
          points={points}
          fill="none"
          stroke="var(--accent)"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Active / Hover crosshair */}
        {activeIndex != null && (
          <g>
            <line
              x1={x(activeIndex)}
              x2={x(activeIndex)}
              y1={PT}
              y2={H - PB}
              stroke="var(--accent-hover)"
              strokeWidth="1"
              strokeDasharray="3,3"
            />
            <circle
              cx={x(activeIndex)}
              cy={y(values[activeIndex])}
              r={4}
              fill="var(--accent)"
              stroke="var(--bg-main)"
              strokeWidth="2"
            />
          </g>
        )}

        {/* Interactive hit overlay */}
        <rect
          x={PL}
          y={0}
          width={W - PL - PR}
          height={H - PB}
          fill="transparent"
          style={{ cursor: 'crosshair' }}
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
          onClick={handleClick}
        />
      </svg>

      {/* Floating active point tooltip */}
      {activeIndex != null && (
        <div
          style={{
            position: 'absolute',
            top: '8px',
            right: '12px',
            background: 'var(--bg-main)',
            border: '1px solid var(--border)',
            padding: '4px 10px',
            borderRadius: '4px',
            fontSize: '11.5px',
            display: 'flex',
            gap: '10px',
            alignItems: 'center',
          }}
        >
          <span style={{ color: 'var(--text-muted)' }}>Date: <strong style={{ color: 'var(--text-bright)' }}>{dates[activeIndex]}</strong></span>
          <span style={{ color: 'var(--text-muted)' }}>Candidates: <strong style={{ color: 'var(--accent)' }}>{values[activeIndex]}</strong></span>
        </div>
      )}
    </div>
  );
};
