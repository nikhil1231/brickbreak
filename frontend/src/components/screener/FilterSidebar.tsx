import React from 'react';
import { ScreenConfig } from '../../types';
import { Slider } from '../common/Slider';
import {
  Paper,
  Stack,
  Text,
  Select,
  Checkbox,
  SegmentedControl,
  Divider,
  ScrollArea,
  Box,
} from '@mantine/core';

interface FilterSidebarProps {
  config: ScreenConfig;
  onChange: (newConfig: Partial<ScreenConfig>) => void;
  onPresetSelect: (minRank: number, maxRank: number) => void;
}

export const FilterSidebar: React.FC<FilterSidebarProps> = ({
  config,
  onChange,
  onPresetSelect,
}) => {
  const currentPreset =
    config.min_size_rank === 250 && config.max_size_rank === 100000
      ? '>250'
      : config.min_size_rank === 250 && config.max_size_rank === 500
      ? '251–500'
      : config.min_size_rank === 500 && config.max_size_rank === 750
      ? '501–750'
      : config.min_size_rank === 750 && config.max_size_rank === 100000
      ? '751+'
      : config.min_size_rank === 0 && config.max_size_rank === 100000
      ? 'all'
      : '';

  const handlePresetChange = (val: string) => {
    switch (val) {
      case '>250':
        onPresetSelect(250, 100000);
        break;
      case '251–500':
        onPresetSelect(250, 500);
        break;
      case '501–750':
        onPresetSelect(500, 750);
        break;
      case '751+':
        onPresetSelect(750, 100000);
        break;
      case 'all':
        onPresetSelect(0, 100000);
        break;
    }
  };

  return (
    <Paper
      component="aside"
      p="md"
      radius={0}
      bg="#161b22"
      style={{
        borderRight: '1px solid var(--border)',
        width: '320px',
        minWidth: '320px',
        height: 'calc(100vh - 65px)',
      }}
    >
      <ScrollArea h="100%" type="scroll" offsetScrollbars>
        <Stack gap="md" pr="xs">
          {/* Size Bucket */}
          <Box>
            <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={8} style={{ letterSpacing: '0.07em' }}>
              Size Bucket
            </Text>
            <SegmentedControl
              size="xs"
              fullWidth
              mb="xs"
              value={currentPreset}
              onChange={handlePresetChange}
              data={[
                { label: '>250', value: '>250' },
                { label: '251–500', value: '251–500' },
                { label: '501–750', value: '501–750' },
                { label: '751+', value: '751+' },
                { label: 'all', value: 'all' },
              ]}
            />
            <Slider
              label="Exclude top N"
              value={config.min_size_rank}
              min={0}
              max={1000}
              step={50}
              onChange={(v) => onChange({ min_size_rank: v })}
            />
            <Select
              size="xs"
              label="Max tier"
              value={String(config.max_size_rank ?? 100000)}
              onChange={(v) => onChange({ max_size_rank: v ? parseInt(v, 10) : 100000 })}
              data={[
                { label: 'No cap', value: '100000' },
                { label: '≤ 500', value: '500' },
                { label: '≤ 750', value: '750' },
                { label: '≤ 200', value: '200' },
              ]}
              comboboxProps={{ shadow: 'md' }}
            />
          </Box>

          <Divider color="var(--border)" />

          {/* Liquidity */}
          <Box>
            <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={8} style={{ letterSpacing: '0.07em' }}>
              Liquidity
            </Text>
            <Slider
              label="Median 20d traded value ≥"
              value={config.min_median_tv_cr}
              min={0}
              max={25}
              step={0.25}
              unit=" ₹ cr"
              onChange={(v) => onChange({ min_median_tv_cr: v })}
            />
            <Slider
              label="Min price"
              value={config.min_price}
              min={0}
              max={500}
              step={10}
              unit=" ₹"
              onChange={(v) => onChange({ min_price: v })}
            />
          </Box>

          <Divider color="var(--border)" />

          {/* Sector Uptrend */}
          <Box>
            <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={8} style={{ letterSpacing: '0.07em' }}>
              Sector Uptrend
            </Text>
            <Select
              size="xs"
              label="Mode"
              mb="xs"
              value={config.sector_mode || 'index'}
              onChange={(v) => onChange({ sector_mode: v || 'index' })}
              data={[
                { label: 'EW index EMA', value: 'index' },
                { label: 'Breadth', value: 'breadth' },
                { label: 'Either', value: 'either' },
                { label: 'Both', value: 'both' },
                { label: 'Off', value: 'off' },
              ]}
            />
            <Slider
              label="Min EMA slope (%/10d)"
              value={config.sector_min_slope}
              min={-5}
              max={8}
              step={0.25}
              unit="%"
              onChange={(v) => onChange({ sector_min_slope: v })}
            />
            <Slider
              label="Min breadth (%)"
              value={config.sector_min_breadth}
              min={0}
              max={100}
              step={5}
              unit="%"
              onChange={(v) => onChange({ sector_min_breadth: v })}
            />
            <Checkbox
              size="xs"
              mt="xs"
              label="Require sector label"
              checked={!!config.sector_require_labelled}
              onChange={(e) => onChange({ sector_require_labelled: e.currentTarget.checked })}
            />
          </Box>

          <Divider color="var(--border)" />

          {/* Stock Trend */}
          <Box>
            <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={8} style={{ letterSpacing: '0.07em' }}>
              Stock Trend
            </Text>
            <Checkbox
              size="xs"
              mb="xs"
              label="EMA stack (20 > 50 > 200)"
              checked={!!config.require_ema_stack}
              onChange={(e) => onChange({ require_ema_stack: e.currentTarget.checked })}
            />
            <Checkbox
              size="xs"
              mb="xs"
              label="Close above EMA50"
              checked={!!config.require_above_ema_mid}
              onChange={(e) => onChange({ require_above_ema_mid: e.currentTarget.checked })}
            />
            <Slider
              label="Min 60d return (%)"
              value={config.min_ret_60d}
              min={-50}
              max={60}
              step={5}
              unit="%"
              onChange={(v) => onChange({ min_ret_60d: v })}
            />
          </Box>

          <Divider color="var(--border)" />

          {/* Contraction */}
          <Box>
            <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={8} style={{ letterSpacing: '0.07em' }}>
              Contraction
            </Text>
            <Slider
              label="ATR(5)/ATR(20) ≤"
              value={config.max_atr_ratio}
              min={0.3}
              max={1.6}
              step={0.05}
              isNullableCeiling
              onChange={(v) => onChange({ max_atr_ratio: v })}
            />
            <Slider
              label="Base depth ≤ (%)"
              value={config.max_base_depth}
              min={2}
              max={40}
              step={1}
              unit="%"
              isNullableCeiling
              onChange={(v) => onChange({ max_base_depth: v })}
            />
            <Slider
              label="BB width pctile ≤"
              value={config.max_bb_width_pctile}
              min={1}
              max={100}
              step={1}
              isNullableCeiling
              onChange={(v) => onChange({ max_bb_width_pctile: v })}
            />
            <Slider
              label="Range% MA ≤"
              value={config.max_range_pct_ma}
              min={0}
              max={12}
              step={0.25}
              isNullableCeiling
              onChange={(v) => onChange({ max_range_pct_ma: v })}
            />
            <Select
              size="xs"
              label="Min contraction steps"
              mb="xs"
              value={config.min_contraction_steps != null ? String(config.min_contraction_steps) : ''}
              onChange={(v) => onChange({ min_contraction_steps: v ? parseInt(v, 10) : null })}
              data={[
                { label: 'Off', value: '' },
                { label: '≥ 1', value: '1' },
                { label: '≥ 2', value: '2' },
              ]}
            />
            <Select
              size="xs"
              label="Min small bodies (of 5)"
              mb="xs"
              value={config.min_small_bodies_5 != null ? String(config.min_small_bodies_5) : ''}
              onChange={(v) => onChange({ min_small_bodies_5: v ? parseInt(v, 10) : null })}
              data={[
                { label: 'Off', value: '' },
                { label: '≥ 1', value: '1' },
                { label: '≥ 2', value: '2' },
                { label: '≥ 3', value: '3' },
              ]}
            />
            <Slider
              label="Vol squeeze (5d/20d) ≤"
              value={config.max_vol_squeeze}
              min={0.2}
              max={2.0}
              step={0.05}
              isNullableCeiling
              onChange={(v) => onChange({ max_vol_squeeze: v })}
            />
            <Checkbox
              size="xs"
              mt="xs"
              label="Require narrowest-range day"
              checked={!!config.require_nr_k}
              onChange={(e) => onChange({ require_nr_k: e.currentTarget.checked })}
            />
          </Box>
        </Stack>
      </ScrollArea>
    </Paper>
  );
};
