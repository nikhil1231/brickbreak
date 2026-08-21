import React, { useState } from 'react';
import { CandidateRow } from '../../types';
import { ChevronUp, ChevronDown, Search } from 'lucide-react';

interface CandidateTableProps {
  candidates: CandidateRow[];
  columns: string[];
  onSelectSymbol: (symbol: string) => void;
}

export const CandidateTable: React.FC<CandidateTableProps> = ({
  candidates,
  columns,
  onSelectSymbol,
}) => {
  const [sortKey, setSortKey] = useState<string>('median_tv_20_cr');
  const [sortDir, setSortDir] = useState<-1 | 1>(-1);
  const [searchQuery, setSearchQuery] = useState<string>('');

  if (!candidates || candidates.length === 0) {
    return (
      <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
        No candidates match the filter criteria for this date.
      </div>
    );
  }

  const handleSort = (col: string) => {
    if (sortKey === col) {
      setSortDir((d) => (d === -1 ? 1 : -1));
    } else {
      setSortKey(col);
      setSortDir(-1);
    }
  };

  const filtered = candidates.filter((c) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      c.symbol?.toLowerCase().includes(q) ||
      c.sector?.toLowerCase().includes(q)
    );
  });

  const sorted = [...filtered].sort((a, b) => {
    const va = a[sortKey];
    const vb = b[sortKey];
    if (va == null) return 1;
    if (vb == null) return -1;
    if (typeof va === 'string') {
      return sortDir * va.localeCompare(vb);
    }
    return sortDir * (va - vb);
  });

  const formatCell = (val: any) => {
    if (val == null) return '—';
    if (typeof val === 'boolean') return val ? '✅' : '—';
    if (typeof val === 'number') {
      if (isNaN(val)) return '—';
      return Math.abs(val) >= 100
        ? val.toLocaleString(undefined, { maximumFractionDigits: 0 })
        : val.toFixed(2);
    }
    return String(val);
  };

  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '12px',
          gap: '12px',
        }}
      >
        <div style={{ position: 'relative', width: '240px' }}>
          <Search
            size={14}
            style={{
              position: 'absolute',
              left: '10px',
              top: '50%',
              transform: 'translateY(-50%)',
              color: 'var(--text-muted)',
            }}
          />
          <input
            type="text"
            placeholder="Search symbol / sector..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              paddingLeft: '32px',
              width: '100%',
              fontSize: '12px',
            }}
          />
        </div>
        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
          Showing {sorted.length} of {candidates.length} candidates
        </div>
      </div>

      <div style={{ overflowX: 'auto', border: '1px solid var(--border)', borderRadius: '6px' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12.5px' }}>
          <thead>
            <tr style={{ background: '#0e131a', borderBottom: '1px solid var(--border)' }}>
              {columns.map((col, idx) => {
                const isSorted = sortKey === col;
                const isLeft = idx < 2;
                return (
                  <th
                    key={col}
                    onClick={() => handleSort(col)}
                    style={{
                      textAlign: isLeft ? 'left' : 'right',
                      padding: '8px 10px',
                      color: isSorted ? 'var(--accent)' : 'var(--text-muted)',
                      fontSize: '11px',
                      fontWeight: 600,
                      textTransform: 'uppercase',
                      letterSpacing: '0.04em',
                      cursor: 'pointer',
                      userSelect: 'none',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    <div
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px',
                        justifyContent: isLeft ? 'flex-start' : 'flex-end',
                      }}
                    >
                      <span>{col.replace(/_/g, ' ')}</span>
                      {isSorted && (
                        sortDir === -1 ? <ChevronDown size={12} /> : <ChevronUp size={12} />
                      )}
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr
                key={row.symbol}
                onClick={() => onSelectSymbol(row.symbol)}
                style={{
                  borderBottom: '1px solid var(--border)',
                  cursor: 'pointer',
                  transition: 'background 0.1s ease',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-panel-hover)')}
                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
              >
                {columns.map((col, idx) => {
                  const isLeft = idx < 2;
                  const isSymbol = col === 'symbol';
                  const val = row[col];
                  return (
                    <td
                      key={col}
                      className={typeof val === 'number' ? 'tabular-nums font-mono' : ''}
                      style={{
                        textAlign: isLeft ? 'left' : 'right',
                        padding: '7px 10px',
                        whiteSpace: 'nowrap',
                        color: isSymbol ? 'var(--accent)' : 'inherit',
                        fontWeight: isSymbol ? 600 : 'normal',
                      }}
                    >
                      {formatCell(val)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
