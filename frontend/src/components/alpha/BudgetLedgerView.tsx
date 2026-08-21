import React, { useEffect, useState } from 'react';
import { fetchLedger } from '../../services/api';
import { LedgerData } from '../../types';
import { Badge } from '../common/Badge';
import {
  Paper,
  Text,
  Table,
  Group,
  Loader,
  Alert,
  Badge as MantineBadge,
  ScrollArea,
  Box,
} from '@mantine/core';
import { IconDatabase, IconAlertCircle } from '@tabler/icons-react';

export const BudgetLedgerView: React.FC = () => {
  const [data, setData] = useState<LedgerData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchLedger()
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <Group justify="center" p="xl" style={{ minHeight: '50vh' }}>
        <Loader size="md" color="blue" />
        <Text size="sm" c="dimmed">
          Loading sample budget ledger...
        </Text>
      </Group>
    );
  }

  return (
    <Box p="lg" style={{ maxWidth: '1200px', margin: '0 auto' }}>
      <Paper p="lg" radius="md">
        <Group justify="space-between" mb="md">
          <Group gap="sm">
            <IconDatabase size={20} color="var(--mantine-color-blue-4)" />
            <Text size="md" fw={700} c="white">
              Sample Budget Ledger
            </Text>
            {data && <MantineBadge color="blue" size="sm">{data.n_entries} Recorded Reads</MantineBadge>}
          </Group>
          <Text size="xs" c="dimmed">
            Tracks consumed data partitions & quarters to prevent multiple testing contamination.
          </Text>
        </Group>

        {error && (
          <Alert icon={<IconAlertCircle size={16} />} title="Ledger Error" color="red" mb="md">
            {error}
          </Alert>
        )}

        <ScrollArea>
          <Table highlightOnHover style={{ fontSize: '12.5px' }}>
            <Table.Thead>
              <Table.Tr style={{ background: '#0e131a' }}>
                <Table.Th style={{ width: '160px' }}>Timestamp</Table.Th>
                <Table.Th style={{ width: '120px' }}>Hypothesis</Table.Th>
                <Table.Th style={{ width: '160px' }}>Family</Table.Th>
                <Table.Th style={{ width: '120px' }}>Role</Table.Th>
                <Table.Th style={{ width: '120px' }}>Partition</Table.Th>
                <Table.Th>Quarters Consumed</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {(data?.entries || []).map((entry, idx) => (
                <Table.Tr key={idx}>
                  <Table.Td style={{ color: 'var(--text-muted)' }} className="font-mono">
                    {entry.timestamp || '—'}
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" fw={700} c="blue.4">
                      {entry.hypothesis_id}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {entry.family || '—'}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge status={entry.role} size="xs" />
                  </Table.Td>
                  <Table.Td>
                    <Badge status={entry.partition} size="xs" />
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="gray.3" className="font-mono">
                      {entry.quarters?.join(', ') || '—'}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      </Paper>
    </Box>
  );
};
