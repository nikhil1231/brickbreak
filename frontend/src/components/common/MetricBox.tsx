import React from 'react';
import { Paper, Text, Stack } from '@mantine/core';

interface MetricBoxProps {
  label: string;
  value: React.ReactNode;
  subtext?: string;
  isBig?: boolean;
  highlight?: 'accent' | 'green' | 'red' | 'yellow' | 'none';
}

export const MetricBox: React.FC<MetricBoxProps> = ({
  label,
  value,
  subtext,
  isBig = false,
  highlight = 'none',
}) => {
  let valColor = 'white';
  if (highlight === 'accent') valColor = 'var(--mantine-color-blue-4)';
  if (highlight === 'green') valColor = 'var(--mantine-color-teal-4)';
  if (highlight === 'red') valColor = 'var(--mantine-color-red-4)';
  if (highlight === 'yellow') valColor = 'var(--mantine-color-yellow-4)';

  return (
    <Paper p="md" radius="md" bg="#11151c" style={{ border: '1px solid var(--border)', textAlign: 'center' }}>
      <Stack gap={4} align="center">
        <Text size="xs" c="dimmed" fw={700} tt="uppercase" style={{ letterSpacing: '0.05em' }}>
          {label}
        </Text>
        <Text
          className="tabular-nums"
          fw={700}
          style={{
            fontSize: isBig ? '24px' : '18px',
            color: valColor,
            lineHeight: 1.2,
          }}
        >
          {value ?? '—'}
        </Text>
        {subtext && (
          <Text size="xs" c="dimmed">
            {subtext}
          </Text>
        )}
      </Stack>
    </Paper>
  );
};
