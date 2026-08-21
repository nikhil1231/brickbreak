import React, { useEffect, useState } from 'react';
import { Modal } from '../common/Modal';
import { fetchSymbol } from '../../services/api';
import { SymbolDetail } from '../../types';
import { Badge } from '../common/Badge';

interface SymbolModalProps {
  symbol: string | null;
  onClose: () => void;
}

export const SymbolModal: React.FC<SymbolModalProps> = ({ symbol, onClose }) => {
  const [data, setData] = useState<SymbolDetail | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!symbol) {
      setData(null);
      return;
    }
    let isMounted = true;
    setLoading(true);
    setError(null);

    fetchSymbol(symbol, 120)
      .then((res) => {
        if (isMounted) {
          setData(res);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          setError(err.message);
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [symbol]);

  if (!symbol) return null;

  const bars = data?.bars || [];
  const n = bars.length;

  const renderChart = () => {
    if (loading) {
      return (
        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
          Loading price series and indicators for {symbol}...
        </div>
      );
    }
    if (error) {
      return (
        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--red)' }}>
          Failed to load data: {error}
        </div>
      );
    }
    if (!n) {
      return (
        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
          No price history available.
        </div>
      );
    }

    const W = 1000;
    const H = 220;
    const PT = 12;
    const PB = 20;
    const PL = 50;
    const PR = 10;

    const lows = bars.map((b) => b.low);
    const highs = bars.map((b) => b.high);
    const lo = Math.min(...lows);
    const hi = Math.max(...highs);
    const range = hi - lo || 1;

    const x = (i: number) => PL + (i / (n - 1 || 1)) * (W - PL - PR);
    const y = (p: number) => PT + (1 - (p - lo) / range) * (H - PT - PB);

    const priceTicks = [lo, lo + range / 2, hi];
    const dateTicks = [0, Math.floor(n / 2), n - 1];

    const emaFastPts = bars
      .map((b, i) => (b.ema_fast != null ? `${x(i).toFixed(1)},${y(b.ema_fast).toFixed(1)}` : null))
      .filter(Boolean)
      .join(' ');

    const emaMidPts = bars
      .map((b, i) => (b.ema_mid != null ? `${x(i).toFixed(1)},${y(b.ema_mid).toFixed(1)}` : null))
      .filter(Boolean)
      .join(' ');

    return (
      <div>
        <div style={{ display: 'flex', gap: '16px', alignItems: 'center', marginBottom: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11.5px', color: 'var(--text-muted)' }}>
            <span style={{ width: '10px', height: '10px', background: 'var(--green)', borderRadius: '2px' }} />
            Bullish Candle
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11.5px', color: 'var(--text-muted)' }}>
            <span style={{ width: '10px', height: '10px', background: 'var(--red)', borderRadius: '2px' }} />
            Bearish Candle
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11.5px', color: 'var(--text-muted)' }}>
            <span style={{ width: '16px', height: '2px', background: '#5fbfa4' }} />
            EMA 20
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11.5px', color: 'var(--text-muted)' }}>
            <span style={{ width: '16px', height: '2px', background: '#d8b45e' }} />
            EMA 50
          </div>
        </div>

        <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: '220px', display: 'block', overflow: 'visible' }}>
          {priceTicks.map((p, idx) => (
            <g key={idx}>
              <line x1={PL} x2={W - PR} y1={y(p)} y2={y(p)} stroke="var(--grid-line)" strokeDasharray="2,2" />
              <text x={PL - 8} y={y(p) + 3.5} textAnchor="end" fontSize="10" fill="var(--text-muted)" className="tabular-nums font-mono">
                {p.toFixed(1)}
              </text>
            </g>
          ))}

          {dateTicks.map((i) => (
            <text key={i} x={x(i)} y={H - 4} textAnchor="middle" fontSize="10" fill="var(--text-muted)" className="tabular-nums font-mono">
              {bars[i]?.date}
            </text>
          ))}

          {/* Candlestick Wicks & Bodies */}
          {bars.map((b, i) => {
            const isUp = b.close >= b.open;
            const candleColor = isUp ? 'var(--green)' : 'var(--red)';
            const topY = y(Math.max(b.open, b.close));
            const botY = y(Math.min(b.open, b.close));
            const bodyHeight = Math.max(1.5, botY - topY);
            const cx = x(i);

            return (
              <g key={i}>
                <line x1={cx} x2={cx} y1={y(b.high)} y2={y(b.low)} stroke={candleColor} strokeWidth="1" />
                <rect
                  x={cx - 2}
                  y={topY}
                  width={4}
                  height={bodyHeight}
                  fill={isUp ? 'transparent' : candleColor}
                  stroke={candleColor}
                  strokeWidth="1"
                />
              </g>
            );
          })}

          {/* Overlaid EMA Curves */}
          {emaFastPts && <polyline points={emaFastPts} fill="none" stroke="#5fbfa4" strokeWidth="1.6" strokeLinecap="round" />}
          {emaMidPts && <polyline points={emaMidPts} fill="none" stroke="#d8b45e" strokeWidth="1.6" strokeLinecap="round" />}
        </svg>

        {/* Latest Metrics Summary */}
        {bars.length > 0 && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
              gap: '10px',
              marginTop: '20px',
              borderTop: '1px solid var(--border)',
              paddingTop: '14px',
            }}
          >
            <div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>CLOSE</div>
              <div style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-bright)' }}>
                ₹{bars[bars.length - 1].close?.toFixed(2)}
              </div>
            </div>
            <div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>ATR RATIO</div>
              <div style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-bright)' }}>
                {bars[bars.length - 1].atr_ratio?.toFixed(2) ?? '—'}
              </div>
            </div>
            <div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>BASE DEPTH</div>
              <div style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-bright)' }}>
                {bars[bars.length - 1].base_depth?.toFixed(1) ? `${bars[bars.length - 1].base_depth?.toFixed(1)}%` : '—'}
              </div>
            </div>
            <div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>BB WIDTH PCTILE</div>
              <div style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-bright)' }}>
                {bars[bars.length - 1].bb_width_pctile?.toFixed(0) ?? '—'}
              </div>
            </div>
          </div>
        )}
      </div>
    );
  };

  return (
    <Modal
      isOpen={!!symbol}
      onClose={onClose}
      title={
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span>{symbol}</span>
          {data?.sector && <Badge status={data.sector} />}
          <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: 'normal' }}>
            Daily history (last 120 sessions)
          </span>
        </div>
      }
      maxWidth="850px"
    >
      {renderChart()}
    </Modal>
  );
};
