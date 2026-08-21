import React, { useState } from 'react';
import { runCompare } from '../../services/api';
import { CompareResult } from '../../types';
import { MetricBox } from '../common/MetricBox';
import {
  Paper,
  Text,
  TagsInput,
  Button,
  Table,
  Group,
  Stack,
  Alert,
  SimpleGrid,
  Box,
} from '@mantine/core';
import {
  IconGitCompare,
  IconPlayerPlay,
  IconAlertCircle,
} from '@tabler/icons-react';

export const SignalCompare: React.FC = () => {
  const [signals, setSignals] = useState<string[]>([
    'rs_60d_vs_mkt',
    'sector_breadth',
    'dist_52w_high',
  ]);
  const [loading, setLoading] = useState<boolean>(false);
  const [result, setResult] = useState<CompareResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleCompare = async () => {
    if (signals.length < 2) {
      setError('Please provide at least 2 valid registered signal names.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await runCompare(signals);
      setResult(res);
    } catch (err: any) {
      setError(err.message || 'Signal comparison failed');
    } finally {
      setLoading(false);
    }
  };

  const corrMatrix = result?.pairwise_rank_correlation;
  const overlapMatrix = result?.pairwise_top_k_overlap_pct;
  const ensemble = result?.combined_ensemble;

  const signalKeys = corrMatrix ? Object.keys(corrMatrix) : [];

  return (
    <Box p="lg" style={{ maxWidth: '1200px', margin: '0 auto' }}>
      <Paper p="lg" radius="md" mb="lg">
        <Group justify="space-between" mb="xs">
          <Group gap="sm">
            <IconGitCompare size={20} color="var(--mantine-color-blue-4)" />
            <Text size="md" fw={700} c="white">
              Signal Compare & Ensembling
            </Text>
          </Group>
          <Text size="xs" c="dimmed">
            Evaluate signal correlation, top-pick overlap, and multi-signal ensemble portfolios.
          </Text>
        </Group>

        <Stack gap="sm" mt="md">
          <TagsInput
            label="Signals to Compare"
            description="Type registered feature names from the catalogue"
            placeholder="Add signal and press enter"
            value={signals}
            onChange={setSignals}
            clearable
          />
          <Group justify="flex-start" mt="xs">
            <Button
              leftSection={<IconPlayerPlay size={16} />}
              color="blue"
              loading={loading}
              onClick={handleCompare}
            >
              Run Multi-Signal Comparison
            </Button>
          </Group>
        </Stack>
      </Paper>

      {error && (
        <Alert icon={<IconAlertCircle size={16} />} title="Comparison Error" color="red" mb="lg">
          {error}
        </Alert>
      )}

      {result && (
        <Stack gap="lg">
          {/* Pairwise Rank Correlation Matrix */}
          {corrMatrix && signalKeys.length > 0 && (
            <Paper p="lg" radius="md">
              <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb="sm" style={{ letterSpacing: '0.06em' }}>
                Pairwise Cross-Sectional Rank Correlation
              </Text>
              <Table style={{ fontSize: '12px' }}>
                <Table.Thead>
                  <Table.Tr style={{ background: '#0e131a' }}>
                    <Table.Th>Signal</Table.Th>
                    {signalKeys.map((k) => (
                      <Table.Th key={k} style={{ textAlign: 'right' }}>
                        {k}
                      </Table.Th>
                    ))}
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {signalKeys.map((rowKey) => (
                    <Table.Tr key={rowKey}>
                      <Table.Td fw={600} c="blue.4">
                        {rowKey}
                      </Table.Td>
                      {signalKeys.map((colKey) => {
                        const val = corrMatrix[rowKey]?.[colKey];
                        const isSelf = rowKey === colKey;
                        return (
                          <Table.Td
                            key={colKey}
                            style={{
                              textAlign: 'right',
                              color: isSelf ? 'var(--text-muted)' : val > 0.6 ? 'var(--red)' : val < 0.2 ? 'var(--green)' : 'inherit',
                              fontWeight: isSelf ? 400 : 600,
                            }}
                            className="tabular-nums font-mono"
                          >
                            {val != null ? val.toFixed(3) : '—'}
                          </Table.Td>
                        );
                      })}
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Paper>
          )}

          {/* Pairwise Top-K Pick Overlap */}
          {overlapMatrix && signalKeys.length > 0 && (
            <Paper p="lg" radius="md">
              <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb="sm" style={{ letterSpacing: '0.06em' }}>
                Pairwise Top-K Pick Overlap %
              </Text>
              <Table style={{ fontSize: '12px' }}>
                <Table.Thead>
                  <Table.Tr style={{ background: '#0e131a' }}>
                    <Table.Th>Signal</Table.Th>
                    {signalKeys.map((k) => (
                      <Table.Th key={k} style={{ textAlign: 'right' }}>
                        {k}
                      </Table.Th>
                    ))}
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {signalKeys.map((rowKey) => (
                    <Table.Tr key={rowKey}>
                      <Table.Td fw={600} c="blue.4">
                        {rowKey}
                      </Table.Td>
                      {signalKeys.map((colKey) => {
                        const val = overlapMatrix[rowKey]?.[colKey];
                        return (
                          <Table.Td key={colKey} style={{ textAlign: 'right' }} className="tabular-nums font-mono">
                            {val != null ? `${val.toFixed(1)}%` : '—'}
                          </Table.Td>
                        );
                      })}
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Paper>
          )}

          {/* Combined Ensemble Performance */}
          {ensemble && (
            <Paper p="lg" radius="md">
              <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb="md" style={{ letterSpacing: '0.06em' }}>
                Combined Multi-Signal Ensemble Performance
              </Text>
              <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
                <MetricBox
                  label="Equal-Weight Ensemble Rank IC"
                  value={ensemble.equal_weight?.ic != null ? ensemble.equal_weight.ic.toFixed(4) : '—'}
                  subtext={`t-statistic: ${ensemble.equal_weight?.t_stat?.toFixed(2) ?? '—'}`}
                  highlight="green"
                />
                <MetricBox
                  label="Rank-Weighted Ensemble IC"
                  value={ensemble.rank_weight?.ic != null ? ensemble.rank_weight.ic.toFixed(4) : '—'}
                  subtext={`t-statistic: ${ensemble.rank_weight?.t_stat?.toFixed(2) ?? '—'}`}
                  highlight="accent"
                />
              </SimpleGrid>
            </Paper>
          )}
        </Stack>
      )}
    </Box>
  );
};
