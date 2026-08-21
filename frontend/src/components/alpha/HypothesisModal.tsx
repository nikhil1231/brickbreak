import React, { useEffect, useState } from 'react';
import {
  Box,
  Code,
  Divider,
  Group,
  Loader,
  Modal,
  Paper,
  Stack,
  Text,
} from '@mantine/core';
import { IconArrowRight } from '@tabler/icons-react';
import { fetchHypothesisDetail } from '../../services/api';
import { Hypothesis } from '../../types';
import { Badge } from '../common/Badge';

interface Props {
  /** The hypothesis to show; null closes the modal. */
  id: string | null;
  /** What is already known about it, shown while the full record loads. */
  fallback?: Hypothesis | null;
  onClose: () => void;
}

/**
 * One hypothesis, with its lineage and every piece of evidence recorded
 * against it.
 *
 * Shared on purpose. The ledger and the exploration list are two routes to
 * the same object, and a second rendering of it would drift — the ledger's
 * copy of this once showed evidence the other did not.
 */
export const HypothesisModal: React.FC<Props> = ({ id, fallback = null, onClose }) => {
  const [detail, setDetail] = useState<Hypothesis | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  useEffect(() => {
    if (!id) {
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    fetchHypothesisDetail(id, controller.signal)
      .then((full) => setDetail(full))
      .catch((err: Error) => {
        // The summary from the caller is better than an empty modal.
        if (err.name !== 'AbortError') setDetail(null);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [id]);

  const hyp = detail || fallback;

  return (
    <Modal
      opened={!!id}
      onClose={onClose}
      size="lg"
      radius="md"
      title={
        hyp ? (
          <Group gap="sm">
            <Text fw={700} c="blue.4">
              {hyp.id}
            </Text>
            <Text fw={600} c="white">
              {hyp.title}
            </Text>
            <Badge status={hyp.status} size="sm" />
          </Group>
        ) : (
          <Text fw={600} c="white">
            {id}
          </Text>
        )
      }
    >
      {!hyp && loading && (
        <Group gap="xs">
          <Loader size="xs" />
          <Text size="sm" c="dimmed">
            Loading {id}…
          </Text>
        </Group>
      )}

      {!hyp && !loading && (
        <Text size="sm" c="dimmed">
          {id} is not in the ledger.
        </Text>
      )}

      {hyp && (
        <Stack gap="md">
          <Box>
            <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={4}>
              Statement
            </Text>
            <Text size="sm" c="gray.2">
              {hyp.statement || 'No statement registered.'}
            </Text>
          </Box>

          <Box>
            <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={4}>
              Economic / Behavioural Rationale
            </Text>
            <Text size="sm" c="gray.4">
              {hyp.rationale || 'No rationale registered.'}
            </Text>
          </Box>

          {hyp.edges && hyp.edges.length > 0 && (
            <Box>
              <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={6}>
                Idea Graph Lineage / Edges
              </Text>
              <Stack gap={4}>
                {hyp.edges.map((e, idx) => (
                  <Group key={idx} gap={6}>
                    <IconArrowRight size={14} color="var(--mantine-color-blue-4)" />
                    <Code color="blue">{e.relation}</Code>
                    <Text size="xs" fw={600} c="white">
                      {e.target_id}
                    </Text>
                  </Group>
                ))}
              </Stack>
            </Box>
          )}

          {hyp.evidence && hyp.evidence.length > 0 && (
            <Box>
              <Divider color="var(--border)" mb="xs" />
              <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={6}>
                Recorded Evidence ({hyp.evidence.length})
              </Text>
              <Stack gap="xs">
                {hyp.evidence.map((ev, idx) => (
                  <Paper key={idx} p="xs" bg="#0d1117" radius="sm">
                    <Group justify="space-between" mb={4}>
                      <Group gap={6}>
                        <Badge status={ev.role} size="xs" />
                        <Text size="xs" c="dimmed">
                          Partition: <strong>{ev.partition}</strong>
                        </Text>
                      </Group>
                      <Badge status={ev.verdict} size="xs" />
                    </Group>
                    <Text size="xs" c="white" mb={4}>
                      {ev.verdict_statement}
                    </Text>
                    {ev.metrics && (
                      <Code block style={{ fontSize: '10px' }}>
                        {JSON.stringify(ev.metrics, null, 2)}
                      </Code>
                    )}
                  </Paper>
                ))}
              </Stack>
            </Box>
          )}

          {loading && (
            <Group gap="xs">
              <Loader size="xs" />
              <Text size="xs" c="dimmed">
                Loading the full record…
              </Text>
            </Group>
          )}
        </Stack>
      )}
    </Modal>
  );
};
