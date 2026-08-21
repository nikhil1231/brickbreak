import React, { useState, useEffect, useRef, useCallback } from 'react';
import { ScreenConfig, ScreenResponse, ScreenerMeta } from '../../types';
import { fetchMeta, runScreen } from '../../services/api';
import { FilterSidebar } from './FilterSidebar';
import { FunnelChart } from './FunnelChart';
import { TimeSeriesChart } from './TimeSeriesChart';
import { CandidateTable } from './CandidateTable';
import { SectorChart } from './SectorChart';
import { SymbolModal } from './SymbolModal';
import { MetricBox } from '../common/MetricBox';
import {
  Box,
  Flex,
  Paper,
  Text,
  Alert,
  SimpleGrid,
  Group,
  Loader,
  Badge as MantineBadge,
} from '@mantine/core';
import { IconInfoCircle, IconAlertTriangle } from '@tabler/icons-react';

interface ScreenerViewProps {
  onStatusChange?: (status: string) => void;
  onMetaLoaded?: (metaText: string) => void;
}

export const ScreenerView: React.FC<ScreenerViewProps> = ({
  onStatusChange,
  onMetaLoaded,
}) => {
  const [meta, setMeta] = useState<ScreenerMeta | null>(null);
  const [config, setConfig] = useState<ScreenConfig>({});
  const [data, setData] = useState<ScreenResponse | null>(null);
  const [selectedDate, setSelectedDate] = useState<string | undefined>(undefined);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const debounceTimerRef = useRef<NodeJS.Timeout | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Initial load: metadata
  useEffect(() => {
    fetchMeta()
      .then((m) => {
        setMeta(m);
        setConfig(m.defaults || {});
        if (onMetaLoaded) {
          onMetaLoaded(
            `${m.n_symbols.toLocaleString()} symbols · ${m.dates.length.toLocaleString()} sessions · ${m.dates[0]} → ${m.dates[m.dates.length - 1]}`
          );
        }
        setLoading(false);
      })
      .catch((err) => {
        setError(`Failed to load screener meta: ${err.message}`);
        setLoading(false);
      });
  }, []);

  // Trigger screen with debounce
  const triggerScreen = useCallback(
    (cfg: ScreenConfig, date?: string) => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
      debounceTimerRef.current = setTimeout(() => {
        if (abortControllerRef.current) {
          abortControllerRef.current.abort();
        }
        const ac = new AbortController();
        abortControllerRef.current = ac;

        if (onStatusChange) onStatusChange('Screening...');

        runScreen(cfg, date, ac.signal)
          .then((res) => {
            setData(res);
            setSelectedDate(res.selected_date);
            if (onStatusChange) onStatusChange('');
          })
          .catch((err) => {
            if (err.name !== 'AbortError') {
              setError(err.message);
              if (onStatusChange) onStatusChange('Error');
            }
          });
      }, 200);
    },
    [onStatusChange]
  );

  // Trigger on config / date change
  useEffect(() => {
    if (!loading && meta) {
      triggerScreen(config, selectedDate);
    }
  }, [config, selectedDate, loading]);

  const handleConfigChange = (newValues: Partial<ScreenConfig>) => {
    setConfig((prev) => ({ ...prev, ...newValues }));
  };

  const handlePresetSelect = (minRank: number, maxRank: number) => {
    setConfig((prev) => ({
      ...prev,
      min_size_rank: minRank,
      max_size_rank: maxRank,
    }));
    setSelectedDate(undefined);
  };

  if (loading) {
    return (
      <Flex justify="center" align="center" style={{ minHeight: '60vh' }}>
        <Group gap="md">
          <Loader color="blue" size="md" />
          <Text size="sm" c="dimmed">
            Warming metrics panel and loading screener metadata...
          </Text>
        </Group>
      </Flex>
    );
  }

  const s = data?.summary?.candidates_per_day;

  return (
    <Flex style={{ minHeight: 'calc(100vh - 65px)' }}>
      {/* Left Sidebar Filters */}
      <FilterSidebar
        config={config}
        onChange={handleConfigChange}
        onPresetSelect={handlePresetSelect}
      />

      {/* Main Content Area */}
      <Box style={{ flex: 1, padding: '20px 24px', minWidth: 0, overflowY: 'auto' }}>
        {error && (
          <Alert
            icon={<IconAlertTriangle size={16} />}
            title="Screener Error"
            color="red"
            mb="md"
            withCloseButton
            onClose={() => setError(null)}
          >
            {error}
          </Alert>
        )}

        <Alert icon={<IconInfoCircle size={16} />} color="yellow" variant="light" mb="md" radius="md">
          <Text size="xs" fw={500}>
            <strong>Phase 1 — screening only.</strong> No second-level data is fetched here. Find thresholds where
            candidates/day is workable (~5–30) to make tick fetching economical.
          </Text>
        </Alert>

        {/* KPI Cards */}
        <SimpleGrid cols={{ base: 2, sm: 3, md: 6 }} spacing="sm" mb="md">
          <MetricBox
            label="Candidates / Day"
            value={s?.mean != null ? s.mean.toFixed(1) : '—'}
            highlight={s?.mean != null && s.mean > 0 && s.mean <= 30 ? 'green' : s?.mean != null && s.mean > 30 ? 'accent' : 'none'}
            subtext={s?.mean != null && s.mean > 0 && s.mean <= 30 ? 'Workable range' : s?.mean != null && s.mean > 30 ? 'Too loose' : 'Too tight'}
            isBig
          />
          <MetricBox
            label="Median / Day"
            value={s?.median != null ? Math.round(s.median) : '—'}
          />
          <MetricBox
            label="P90 / Day"
            value={s?.p90 != null ? Math.round(s.p90) : '—'}
          />
          <MetricBox
            label="Max / Day"
            value={s?.max != null ? Math.round(s.max) : '—'}
          />
          <MetricBox
            label="Zero-Cand Days"
            value={s?.zero_days_pct != null ? `${Math.round(s.zero_days_pct)}%` : '—'}
          />
          <MetricBox
            label="1s Calls / 3y"
            value={s?.mean != null ? (s.mean * 750).toLocaleString(undefined, { maximumFractionDigits: 0 }) : '—'}
            subtext="1 call per name·day"
          />
        </SimpleGrid>

        {/* Filter Stage Funnel */}
        <Paper p="md" radius="md" mb="md">
          <Group justify="space-between" mb="sm">
            <Text size="xs" fw={700} tt="uppercase" c="dimmed" style={{ letterSpacing: '0.06em' }}>
              Funnel — Mean Names Surviving Per Day
            </Text>
          </Group>
          <FunnelChart meanPerStage={data?.summary?.mean_per_stage || {}} />
        </Paper>

        {/* Candidates Time Series Chart */}
        <Paper p="md" radius="md" mb="md">
          <Group justify="space-between" mb="xs">
            <Group gap="xs">
              <Text size="xs" fw={700} tt="uppercase" c="dimmed" style={{ letterSpacing: '0.06em' }}>
                Candidates Per Day
              </Text>
              <Text size="xs" c="dimmed">
                — click timeline to inspect specific session
              </Text>
            </Group>
            {selectedDate && (
              <MantineBadge color="blue" size="sm" variant="filled">
                Selected: {selectedDate}
              </MantineBadge>
            )}
          </Group>
          <TimeSeriesChart
            dates={data?.series?.dates || []}
            values={data?.series?.contraction || []}
            selectedDate={selectedDate}
            onSelectDate={(d) => setSelectedDate(d)}
          />
        </Paper>

        {/* Candidates Table for Selected Date */}
        <Paper p="md" radius="md" mb="md">
          <Group justify="space-between" mb="sm">
            <Group gap="xs">
              <Text size="xs" fw={700} tt="uppercase" c="dimmed" style={{ letterSpacing: '0.06em' }}>
                Candidates on {selectedDate || '—'}
              </Text>
              <Text size="xs" c="dimmed">
                ({data?.candidates?.length || 0} shown, {data?.total_candidates?.toLocaleString() || 0} total in window)
              </Text>
            </Group>
            <Text size="xs" c="dimmed">
              Click any row for candle & EMA history
            </Text>
          </Group>
          <CandidateTable
            candidates={data?.candidates || []}
            columns={data?.columns || []}
            onSelectSymbol={(sym) => setSelectedSymbol(sym)}
          />
        </Paper>

        {/* Sector Mix */}
        <Paper p="md" radius="md">
          <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb="sm" style={{ letterSpacing: '0.06em' }}>
            Sector Mix of All Candidates in Window
          </Text>
          <SectorChart bySector={data?.by_sector || {}} />
        </Paper>
      </Box>

      {/* Symbol Candlestick & Indicator Modal */}
      <SymbolModal
        symbol={selectedSymbol}
        onClose={() => setSelectedSymbol(null)}
      />
    </Flex>
  );
};
