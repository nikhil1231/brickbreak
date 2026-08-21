import React, { useEffect, useState } from 'react';
import { fetchCatalogue } from '../../services/api';
import { CatalogueData } from '../../types';
import {
  Paper,
  Text,
  Table,
  TextInput,
  Select,
  Group,
  Loader,
  Alert,
  Badge as MantineBadge,
  ScrollArea,
  Code,
  Box,
} from '@mantine/core';
import {
  IconLayersLinked,
  IconAlertCircle,
  IconSearch,
} from '@tabler/icons-react';

export const CatalogueView: React.FC = () => {
  const [data, setData] = useState<CatalogueData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState<string>('');
  const [ownerFilter, setOwnerFilter] = useState<string>('all');

  useEffect(() => {
    fetchCatalogue()
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
          Loading feature catalogue...
        </Text>
      </Group>
    );
  }

  const features = data?.features || [];
  const owners = Array.from(new Set(features.map((f) => f.owner).filter(Boolean)));

  const filtered = features.filter((f) => {
    if (ownerFilter !== 'all' && f.owner !== ownerFilter) return false;
    if (search) {
      const q = search.toLowerCase();
      return f.name.toLowerCase().includes(q) || f.owner.toLowerCase().includes(q);
    }
    return true;
  });

  return (
    <Box p="lg" style={{ maxWidth: '1200px', margin: '0 auto' }}>
      <Paper p="lg" radius="md">
        <Group justify="space-between" mb="sm">
          <Group gap="sm">
            <IconLayersLinked size={20} color="var(--mantine-color-blue-4)" />
            <Text size="md" fw={700} c="white">
              Feature Catalogue
            </Text>
            <MantineBadge color="blue" size="sm">
              {features.length} Registered Features
            </MantineBadge>
          </Group>
          <Text size="xs" c="dimmed">
            {data?.summary}
          </Text>
        </Group>

        {error && (
          <Alert icon={<IconAlertCircle size={16} />} title="Catalogue Error" color="red" mb="md">
            {error}
          </Alert>
        )}

        <Group gap="md" mb="md">
          <TextInput
            placeholder="Search feature name..."
            leftSection={<IconSearch size={14} />}
            value={search}
            onChange={(e) => setSearch(e.currentTarget.value)}
            style={{ flex: 1, minWidth: '220px' }}
            size="xs"
          />
          <Select
            size="xs"
            placeholder="Owner"
            value={ownerFilter}
            onChange={(v) => setOwnerFilter(v || 'all')}
            data={[{ label: 'All Owners', value: 'all' }, ...owners.map((o) => ({ label: o, value: o }))]}
            style={{ width: '180px' }}
          />
        </Group>

        <ScrollArea>
          <Table highlightOnHover style={{ fontSize: '12.5px' }}>
            <Table.Thead>
              <Table.Tr style={{ background: '#0e131a' }}>
                <Table.Th>Feature Name</Table.Th>
                <Table.Th style={{ width: '130px' }}>Owner</Table.Th>
                <Table.Th style={{ width: '120px' }}>As-Of</Table.Th>
                <Table.Th style={{ width: '100px' }}>Lookback</Table.Th>
                <Table.Th style={{ width: '100px', textAlign: 'center' }}>PIT (Safe)</Table.Th>
                <Table.Th style={{ width: '110px', textAlign: 'center' }}>Scorable</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {filtered.map((f) => (
                <Table.Tr key={f.name}>
                  <Table.Td>
                    <Code color="blue" style={{ fontSize: '12px' }}>
                      {f.name}
                    </Code>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="white">
                      {f.owner}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {f.available_as_of}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {f.lookback || '—'}
                    </Text>
                  </Table.Td>
                  <Table.Td style={{ textAlign: 'center' }}>
                    {f.point_in_time ? (
                      <MantineBadge color="teal" size="xs" variant="light">
                        PIT ✅
                      </MantineBadge>
                    ) : (
                      <MantineBadge color="red" size="xs" variant="light">
                        No ❌
                      </MantineBadge>
                    )}
                  </Table.Td>
                  <Table.Td style={{ textAlign: 'center' }}>
                    {f.scorable ? (
                      <MantineBadge color="blue" size="xs" variant="filled">
                        Scorable
                      </MantineBadge>
                    ) : (
                      <MantineBadge color="yellow" size="xs" variant="outline">
                        Locked 🔒
                      </MantineBadge>
                    )}
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
