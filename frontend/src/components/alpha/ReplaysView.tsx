import React, { useEffect, useState } from 'react';
import {
  Badge, Box, Card, Code, Group, Loader, ScrollArea, Stack, Table, Text, Title,
} from '@mantine/core';

/**
 * Read-only, on purpose.
 *
 * A replay spends the sample at its reveal phase, and a button that spends
 * sample does not belong on a page somebody opened to look around. Dispatch
 * stays on the CLI, where the phase being run is the thing you typed.
 */

type Phases = Record<string, boolean>;

interface Headline {
  take_rate_pct?: number;
  n_taken?: number;
  taken_mean_excess_bps?: number;
  excess_lift_bps?: number;
  excess_lift_t?: number;
  take_vs_skip_bps?: number;
  lift_over_baseline_bps?: number;
  best_baseline?: string;
  independent_blocks?: number;
  effective_sessions?: number;
}

interface Verdict {
  failure_class?: string;
  passed?: boolean;
  statement?: string;
  sample_caveat?: string;
  checks?: { criterion: string; bar: number; measured: number | null; passed: boolean }[];
}

interface ReplayRow {
  id: string;
  idea?: string;
  hypothesis_id?: string;
  generator?: string;
  partition?: string;
  sample_n?: number;
  anonymised?: boolean;
  primary_horizon?: number;
  phases: Phases;
  next: string | null;
  headline?: Headline;
  verdict?: Verdict;
}

const PHASE_ORDER = ['freeze', 'generate', 'build', 'decide', 'reveal', 'evaluate'];

/** A missing number is not a zero, and must never render as one. */
const bps = (v?: number | null) =>
  v === undefined || v === null || Number.isNaN(v) ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(0)} bps`;

const num = (v?: number | null) =>
  v === undefined || v === null || Number.isNaN(v) ? '—' : String(v);

const verdictColour = (cls?: string) =>
  cls === 'SUCCESS' ? 'teal'
    : cls === 'NO_SIGNAL' ? 'red'
      : cls === 'SIGNAL_TOO_SMALL' ? 'orange'
        : 'gray';

const PhaseTrack: React.FC<{ phases: Phases }> = ({ phases }) => (
  <Group gap={4}>
    {PHASE_ORDER.map((p) => (
      <Badge
        key={p}
        size="xs"
        variant={phases?.[p] ? 'filled' : 'outline'}
        color={phases?.[p] ? 'blue' : 'gray'}
        // The seal sits between decide and reveal; mark where it is.
        style={p === 'reveal' ? { borderLeft: '2px solid #f59f00' } : undefined}
      >
        {p}
      </Badge>
    ))}
  </Group>
);

export const ReplaysView: React.FC = () => {
  const [rows, setRows] = useState<ReplayRow[]>([]);
  const [selected, setSelected] = useState<ReplayRow | null>(null);
  const [caseText, setCaseText] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>('');

  useEffect(() => {
    fetch('/api/replays')
      .then((r) => r.json())
      .then((d) => { setRows(d.replays || []); setLoading(false); })
      .catch((e) => { setError(String(e)); setLoading(false); });
  }, []);

  useEffect(() => {
    if (!selected) { setCaseText(''); return; }
    if (!selected.phases?.build) { setCaseText(''); return; }
    fetch(`/api/replays/${selected.id}/cases?index=0`)
      .then((r) => r.json())
      .then((d) => setCaseText(d.rendered || d.error || ''))
      .catch(() => setCaseText(''));
  }, [selected]);

  if (loading) return <Box p="xl"><Loader /></Box>;
  if (error) return <Box p="xl"><Text c="red">{error}</Text></Box>;

  if (!rows.length) {
    return (
      <Box p="xl">
        <Title order={4} c="gray.3">No replays yet</Title>
        <Text size="sm" c="dimmed" mt="sm">
          Start one from the CLI. Dispatch lives there because the reveal phase
          spends sample, and that should be something you typed.
        </Text>
        <Code block mt="md">
          python -m src.cli opportunity &quot;&lt;your idea&gt;&quot; --hypothesis H041 -n 500{'\n'}
          python -m src.cli replay &lt;ID&gt; --phase generate
        </Code>
      </Box>
    );
  }

  const h = selected?.headline;
  const v = selected?.verdict;

  return (
    <Box p="md">
      <Title order={4} c="gray.3" mb="sm">Discretionary replays</Title>
      <Table highlightOnHover striped withTableBorder>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Replay</Table.Th>
            <Table.Th>Idea</Table.Th>
            <Table.Th>Progress</Table.Th>
            <Table.Th>Lift vs pool</Table.Th>
            <Table.Th>Verdict</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((r) => (
            <Table.Tr
              key={r.id}
              onClick={() => setSelected(r)}
              style={{ cursor: 'pointer',
                background: selected?.id === r.id ? '#1c2128' : undefined }}
            >
              <Table.Td><Code>{r.id}</Code></Table.Td>
              <Table.Td>
                <Text size="sm" lineClamp={1}>{r.idea}</Text>
                <Text size="xs" c="dimmed">
                  {r.hypothesis_id} · {r.generator} · {r.partition} · n={r.sample_n}
                  {r.anonymised === false && ' · IDENTITY REVEALED'}
                </Text>
              </Table.Td>
              <Table.Td><PhaseTrack phases={r.phases} /></Table.Td>
              <Table.Td>{bps(r.headline?.excess_lift_bps)}</Table.Td>
              <Table.Td>
                {r.verdict?.failure_class && (
                  <Badge color={verdictColour(r.verdict.failure_class)} variant="light">
                    {r.verdict.failure_class}
                  </Badge>
                )}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>

      {selected && (
        <Stack mt="lg" gap="md">
          {h && (
            <Card bg="#161b22" withBorder>
              <Title order={5} c="gray.4" mb="xs">Did selection help?</Title>
              <Text size="xs" c="dimmed" mb="sm">
                Per-session paired, Hansen-Hodrick corrected. Outcomes are excess
                over the equal-weighted market, so market exposure is the zero line.
              </Text>
              <Group gap="xl">
                <Box>
                  <Text size="xs" c="dimmed">vs the pool it was given</Text>
                  <Text size="lg">{bps(h.excess_lift_bps)}
                    <Text span size="xs" c="dimmed"> t={num(h.excess_lift_t)}</Text>
                  </Text>
                </Box>
                <Box>
                  <Text size="xs" c="dimmed">vs what it skipped</Text>
                  <Text size="lg">{bps(h.take_vs_skip_bps)}</Text>
                </Box>
                <Box>
                  <Text size="xs" c="dimmed">vs {h.best_baseline || 'baseline'}</Text>
                  <Text size="lg">{bps(h.lift_over_baseline_bps)}</Text>
                </Box>
                <Box>
                  <Text size="xs" c="dimmed">take rate</Text>
                  <Text size="lg">{num(h.take_rate_pct)}%
                    <Text span size="xs" c="dimmed"> ({h.n_taken} taken)</Text>
                  </Text>
                </Box>
              </Group>
              {h.independent_blocks !== undefined && (
                <Text size="xs" c="orange.4" mt="sm">
                  ~{h.independent_blocks} independent blocks
                  ({h.effective_sessions} sessions at a {selected.primary_horizon}-session
                  horizon). Do not promote on the t-statistic.
                </Text>
              )}
            </Card>
          )}

          {v && (
            <Card bg="#161b22" withBorder>
              <Group>
                <Badge color={verdictColour(v.failure_class)}>{v.failure_class}</Badge>
                <Text size="sm">{v.statement}</Text>
              </Group>
              {v.checks?.map((c) => (
                <Text key={c.criterion} size="xs" c={c.passed ? 'teal' : 'red'} mt={4}>
                  [{c.passed ? 'PASS' : 'FAIL'}] {c.criterion}: measured {num(c.measured)} against a bar of {c.bar}
                </Text>
              ))}
              {v.sample_caveat && (
                <Text size="xs" c="dimmed" mt="sm">{v.sample_caveat}</Text>
              )}
            </Card>
          )}

          {caseText && (
            <Card bg="#161b22" withBorder>
              <Title order={5} c="gray.4" mb="xs">
                What the judge was shown (case 0)
              </Title>
              <ScrollArea h={360}>
                <Code block style={{ fontSize: 11 }}>{caseText}</Code>
              </ScrollArea>
            </Card>
          )}
        </Stack>
      )}
    </Box>
  );
};
