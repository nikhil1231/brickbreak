import React from 'react';
import { Text, Group, Box, Stack } from '@mantine/core';

interface SectorChartProps {
  bySector: Record<string, number>;
}

export const SectorChart: React.FC<SectorChartProps> = ({ bySector }) => {
  const entries = Object.entries(bySector || {});
  if (!entries.length) {
    return <Text size="xs" c="dimmed">No sector breakdown data</Text>;
  }

  const mx = Math.max(1, ...Object.values(bySector));

  return (
    <Stack gap={6}>
      {entries.map(([sector, count]) => {
        const pct = (count / mx) * 100;
        return (
          <Group key={sector} gap="sm" wrap="nowrap">
            <Text size="xs" c="dimmed" style={{ width: '180px', flexShrink: 0 }} truncate>
              {sector}
            </Text>
            <Box
              style={{
                flex: 1,
                background: 'var(--bg-main)',
                borderRadius: '3px',
                height: '16px',
                overflow: 'hidden',
              }}
            >
              <Box
                style={{
                  width: `${pct}%`,
                  height: '100%',
                  background: 'var(--mantine-color-blue-6)',
                  borderRadius: '3px',
                  transition: 'width 0.2s ease',
                }}
              />
            </Box>
            <Text size="xs" fw={600} className="tabular-nums font-mono" style={{ width: '60px', textAlign: 'right' }}>
              {count.toLocaleString()}
            </Text>
          </Group>
        );
      })}
    </Stack>
  );
};
