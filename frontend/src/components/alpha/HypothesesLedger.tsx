import React, { useState, useEffect } from 'react';
import { fetchHypotheses } from '../../services/api';
import { Hypothesis } from '../../types';
import { Badge } from '../common/Badge';
import { HypothesisModal } from './HypothesisModal';
import {
  Paper,
  Text,
  Table,
  TextInput,
  Select,
  Group,
  Loader,
  Alert,
  Box,
  ScrollArea,
} from '@mantine/core';
import {
  IconSearch,
  IconBook,
  IconAlertCircle,
  IconChevronUp,
  IconChevronDown,
  IconSelector,
} from '@tabler/icons-react';

type SortColumn = 'id' | 'title' | 'family' | 'status' | 'tags';
type SortDirection = 'asc' | 'desc';

export const HypothesesLedger: React.FC = () => {
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [familyFilter, setFamilyFilter] = useState<string>('all');

  // Default sort by ID descending (H038, H037, ... H001)
  const [sortCol, setSortCol] = useState<SortColumn>('id');
  const [sortDir, setSortDir] = useState<SortDirection>('desc');

  const [selectedHyp, setSelectedHyp] = useState<Hypothesis | null>(null);

  useEffect(() => {
    fetchHypotheses()
      .then((data) => {
        setHypotheses(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  const handleSelectHypothesis = (id: string) => {
    // The modal loads the full record; the row is what to show meanwhile.
    setSelectedHyp(hypotheses.find((h) => h.id === id) || null);
  };

  const handleSort = (col: SortColumn) => {
    if (sortCol === col) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortCol(col);
      // If changing to ID, default to desc; otherwise asc
      setSortDir(col === 'id' ? 'desc' : 'asc');
    }
  };

  const families = Array.from(new Set(hypotheses.map((h) => h.family).filter(Boolean)));
  const statuses = Array.from(new Set(hypotheses.map((h) => h.status).filter(Boolean)));

  const filtered = hypotheses.filter((h) => {
    if (statusFilter !== 'all' && h.status !== statusFilter) return false;
    if (familyFilter !== 'all' && h.family !== familyFilter) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        h.id.toLowerCase().includes(q) ||
        h.title.toLowerCase().includes(q) ||
        h.family?.toLowerCase().includes(q) ||
        h.tags?.some((t) => t.toLowerCase().includes(q))
      );
    }
    return true;
  });

  const sorted = [...filtered].sort((a, b) => {
    let cmp = 0;
    if (sortCol === 'id') {
      const numA = parseInt(a.id.replace(/\D/g, ''), 10) || 0;
      const numB = parseInt(b.id.replace(/\D/g, ''), 10) || 0;
      cmp = numA - numB;
    } else if (sortCol === 'title') {
      cmp = (a.title || '').localeCompare(b.title || '');
    } else if (sortCol === 'family') {
      cmp = (a.family || '').localeCompare(b.family || '');
    } else if (sortCol === 'status') {
      cmp = (a.status || '').localeCompare(b.status || '');
    } else if (sortCol === 'tags') {
      cmp = (a.tags?.join(', ') || '').localeCompare(b.tags?.join(', ') || '');
    }
    return sortDir === 'asc' ? cmp : -cmp;
  });

  const renderSortIcon = (col: SortColumn) => {
    if (sortCol !== col) {
      return <IconSelector size={13} style={{ opacity: 0.3 }} />;
    }
    return sortDir === 'asc' ? (
      <IconChevronUp size={13} style={{ color: 'var(--mantine-color-blue-4)' }} />
    ) : (
      <IconChevronDown size={13} style={{ color: 'var(--mantine-color-blue-4)' }} />
    );
  };

  if (loading) {
    return (
      <Group justify="center" p="xl" style={{ minHeight: '50vh' }}>
        <Loader size="md" color="blue" />
        <Text size="sm" c="dimmed">
          Loading research ledger (H001–H038)...
        </Text>
      </Group>
    );
  }

  return (
    <Box p="lg" style={{ maxWidth: '1300px', margin: '0 auto' }}>
      <Paper p="lg" radius="md" mb="md">
        <Group justify="space-between" mb="md">
          <Group gap="sm">
            <IconBook size={20} color="var(--mantine-color-blue-4)" />
            <Text size="md" fw={700} c="white">
              Research Ledger (H001 – H038)
            </Text>
            <Badge status={`${hypotheses.length} entries`} size="sm" />
          </Group>
          <Text size="xs" c="dimmed">
            Sorted by ID ({sortDir.toUpperCase()}) — click headers to re-sort.
          </Text>
        </Group>

        {error && (
          <Alert icon={<IconAlertCircle size={16} />} title="Ledger Error" color="red" mb="md">
            {error}
          </Alert>
        )}

        {/* Filter Controls */}
        <Group gap="md" mb="md">
          <TextInput
            placeholder="Search hypothesis, title, tags..."
            leftSection={<IconSearch size={14} />}
            value={search}
            onChange={(e) => setSearch(e.currentTarget.value)}
            style={{ flex: 1, minWidth: '220px' }}
            size="xs"
          />
          <Select
            size="xs"
            placeholder="Status"
            value={statusFilter}
            onChange={(v) => setStatusFilter(v || 'all')}
            data={[{ label: 'All Statuses', value: 'all' }, ...statuses.map((s) => ({ label: s, value: s }))]}
            style={{ width: '160px' }}
          />
          <Select
            size="xs"
            placeholder="Family"
            value={familyFilter}
            onChange={(v) => setFamilyFilter(v || 'all')}
            data={[{ label: 'All Families', value: 'all' }, ...families.map((f) => ({ label: f, value: f }))]}
            style={{ width: '180px' }}
          />
        </Group>

        {/* Hypotheses Table */}
        <ScrollArea>
          <Table highlightOnHover style={{ fontSize: '12.5px' }}>
            <Table.Thead>
              <Table.Tr style={{ background: '#0e131a' }}>
                <Table.Th style={{ width: '90px', cursor: 'pointer', userSelect: 'none' }} onClick={() => handleSort('id')}>
                  <Group gap={4} wrap="nowrap">
                    <Text size="xs" fw={700} tt="uppercase" c={sortCol === 'id' ? 'blue.4' : 'dimmed'}>
                      ID
                    </Text>
                    {renderSortIcon('id')}
                  </Group>
                </Table.Th>
                <Table.Th style={{ cursor: 'pointer', userSelect: 'none' }} onClick={() => handleSort('title')}>
                  <Group gap={4} wrap="nowrap">
                    <Text size="xs" fw={700} tt="uppercase" c={sortCol === 'title' ? 'blue.4' : 'dimmed'}>
                      Title
                    </Text>
                    {renderSortIcon('title')}
                  </Group>
                </Table.Th>
                <Table.Th style={{ width: '150px', cursor: 'pointer', userSelect: 'none' }} onClick={() => handleSort('family')}>
                  <Group gap={4} wrap="nowrap">
                    <Text size="xs" fw={700} tt="uppercase" c={sortCol === 'family' ? 'blue.4' : 'dimmed'}>
                      Family
                    </Text>
                    {renderSortIcon('family')}
                  </Group>
                </Table.Th>
                <Table.Th style={{ width: '130px', cursor: 'pointer', userSelect: 'none' }} onClick={() => handleSort('status')}>
                  <Group gap={4} wrap="nowrap">
                    <Text size="xs" fw={700} tt="uppercase" c={sortCol === 'status' ? 'blue.4' : 'dimmed'}>
                      Status
                    </Text>
                    {renderSortIcon('status')}
                  </Group>
                </Table.Th>
                <Table.Th style={{ width: '220px', cursor: 'pointer', userSelect: 'none' }} onClick={() => handleSort('tags')}>
                  <Group gap={4} wrap="nowrap">
                    <Text size="xs" fw={700} tt="uppercase" c={sortCol === 'tags' ? 'blue.4' : 'dimmed'}>
                      Tags
                    </Text>
                    {renderSortIcon('tags')}
                  </Group>
                </Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {sorted.map((h) => (
                <Table.Tr
                  key={h.id}
                  onClick={() => handleSelectHypothesis(h.id)}
                  style={{ cursor: 'pointer' }}
                >
                  <Table.Td>
                    <Text size="xs" fw={700} c="blue.4">
                      {h.id}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" fw={500} c="white">
                      {h.title}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {h.family || '—'}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge status={h.status} size="xs" />
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed" truncate>
                      {h.tags?.join(', ') || '—'}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      </Paper>

      <HypothesisModal
        id={selectedHyp?.id || null}
        fallback={selectedHyp}
        onClose={() => setSelectedHyp(null)}
      />
    </Box>
  );
};
