import React, { useEffect, useRef, useState } from 'react';
import {
  Badge as MantineBadge,
  Box,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  ThemeIcon,
  Tooltip,
} from '@mantine/core';
import { IconActivity, IconAlertTriangle, IconCheck, IconClock } from '@tabler/icons-react';
import { fetchJobs } from '../../services/api';
import { HypothesisModal } from './HypothesisModal';
import { JobRow } from '../../types';

interface Props {
  /** Bumped by the parent when a launch starts or finishes, to poll at once. */
  reloadToken: number;
}

const ACTIVE_STATES = ['queued', 'running'];
const IDLE_POLL_MS = 15000;
const ACTIVE_POLL_MS = 2500;

function isActive(job: JobRow): boolean {
  return ACTIVE_STATES.includes(job.state);
}

function stateColor(state: string): string {
  if (state === 'succeeded') return 'teal';
  if (state === 'blocked' || state === 'interrupted') return 'yellow';
  if (state === 'failed' || state === 'timeout') return 'red';
  return 'blue';
}

function secondsSince(stamp: string, now: number): number | null {
  const t = Date.parse((stamp || '').replace(' ', 'T'));
  return Number.isNaN(t) ? null : Math.max(0, Math.round((now - t) / 1000));
}

function clock(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  return `${m}m ${String(seconds % 60).padStart(2, '0')}s`;
}

/**
 * Evidence that a long phase is progressing rather than stuck.
 *
 * `writing the signal` is most of a run's wall-clock and reports nothing on
 * its own, so the worktree stands in for it: whether the worker has produced
 * `job/signal.py` yet, and when it last touched anything.
 */
function phaseDetail(job: JobRow, now: number): string | null {
  const inPhase = secondsSince(job.phase_started_at, now);
  const parts: string[] = [];
  if (inPhase !== null) {
    parts.push(
      job.timeout_s
        ? `${clock(inPhase)} in this step of a ${Math.round(job.timeout_s / 60)}m limit`
        : `${clock(inPhase)} in this step`
    );
  }
  const w = job.worker;
  if (w && job.phase === 'writing the signal') {
    parts.push(
      w.signal_written
        ? `signal.py written (${w.signal_bytes.toLocaleString()} bytes)`
        : 'signal.py not written yet — the worker is still reading and thinking'
    );
    if (w.seconds_since_change !== null) {
      parts.push(`worktree last changed ${clock(Math.round(w.seconds_since_change))} ago`);
    }
  }
  if (job.turns) parts.push(`${job.turns} turns`);
  return parts.length ? parts.join(' · ') : null;
}

function elapsed(job: JobRow, now: number): string {
  if (!isActive(job)) return `${job.runtime_s}s`;
  // `created_at` is local wall-clock from the server, which is this machine.
  const started = Date.parse(job.created_at.replace(' ', 'T'));
  if (Number.isNaN(started)) return '—';
  return `${Math.max(0, Math.round((now - started) / 1000))}s`;
}

/**
 * The run as its sequence of steps, with the one it is on.
 *
 * A bar filling to 60% says nothing about what is happening; the phase names
 * do, and seeing which are behind it makes a long step legible as progress
 * rather than as a stall.
 */
const Pipeline: React.FC<{ phases: string[]; current: string; failed: boolean }> = ({
  phases,
  current,
  failed,
}) => {
  const at = phases.indexOf(current);
  return (
    <Group gap={0} mt={10} wrap="wrap" style={{ rowGap: 6 }}>
      {phases.map((phase, idx) => {
        const done = at >= 0 && idx < at;
        const here = idx === at;
        const colour = here
          ? failed
            ? 'var(--mantine-color-red-5)'
            : 'var(--mantine-color-blue-4)'
          : done
            ? 'var(--mantine-color-teal-6)'
            : 'var(--mantine-color-dark-3)';
        return (
          <React.Fragment key={phase}>
            {idx > 0 && (
              <Box
                style={{
                  width: 14,
                  height: 1,
                  background: done || here ? 'var(--mantine-color-teal-8)' : 'var(--border)',
                  margin: '0 4px',
                }}
              />
            )}
            <Group gap={5} wrap="nowrap">
              <Box
                style={{
                  width: here ? 8 : 6,
                  height: here ? 8 : 6,
                  borderRadius: '50%',
                  background: colour,
                  boxShadow: here && !failed ? `0 0 0 3px rgba(51,143,255,0.18)` : undefined,
                }}
              />
              <Text
                size="xs"
                c={here ? (failed ? 'red.4' : 'blue.4') : done ? 'teal.7' : 'dark.2'}
                fw={here ? 700 : 400}
              >
                {phase}
              </Text>
            </Group>
          </React.Fragment>
        );
      })}
    </Group>
  );
};

export const ExplorationStatus: React.FC<Props> = ({ reloadToken }) => {
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [loaded, setLoaded] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState<number>(Date.now());
  const timer = useRef<number | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    const poll = async () => {
      try {
        const data = await fetchJobs(controller.signal);
        if (cancelled) return;
        setJobs(data.jobs);
        setError(null);
        setLoaded(true);
        // Watch closely only while something is actually running.
        const delay = data.jobs.some(isActive) ? ACTIVE_POLL_MS : IDLE_POLL_MS;
        timer.current = window.setTimeout(poll, delay);
      } catch (err: any) {
        if (cancelled || err?.name === 'AbortError') return;
        setError(err.message || 'Could not read exploration status');
        setLoaded(true);
        timer.current = window.setTimeout(poll, IDLE_POLL_MS);
      }
    };

    poll();
    return () => {
      cancelled = true;
      controller.abort();
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [reloadToken]);

  // A ticking elapsed counter, so a long phase still looks alive.
  useEffect(() => {
    if (!jobs.some(isActive)) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [jobs]);

  const [openHypId, setOpenHypId] = useState<string | null>(null);
  const running = jobs.filter(isActive);

  if (loaded && jobs.length === 0 && !error) return null;

  return (
    <Box mb="xl">
      <Group justify="space-between" align="flex-end" mb="sm">
        <Group gap="sm">
          <ThemeIcon size="lg" radius="md" variant="light" color={running.length ? 'blue' : 'gray'}>
            {running.length ? <Loader size={14} color="blue" /> : <IconActivity size={18} />}
          </ThemeIcon>
          <div>
            <Text size="md" fw={700} c="white" style={{ letterSpacing: '-0.02em' }}>
              Explorations
            </Text>
            <Text size="xs" c="dimmed">
              {running.length > 0
                ? `${running.length} running — ${running
                    .map((j) => j.phase || j.state)
                    .join(', ')}`
                : 'Nothing running. The most recent runs and what they returned.'}
            </Text>
          </div>
        </Group>
      </Group>

      {error && (
        <Text size="xs" c="red.5" mb="xs">
          {error}
        </Text>
      )}

      <Stack gap="xs">
        {jobs.map((job) => {
          const active = isActive(job);
          const stalled = ['failed', 'timeout', 'interrupted', 'blocked'].includes(job.state);

          return (
            <Paper
              key={job.job_id}
              p="sm"
              radius="md"
              bg="#161b22"
              onClick={() => {
                if (!active && job.hypothesis_id) setOpenHypId(job.hypothesis_id);
              }}
              style={{
                border: active ? '1px solid var(--mantine-color-blue-8)' : '1px solid var(--border)',
                cursor: !active && job.hypothesis_id ? 'pointer' : 'default',
              }}
            >
              <Group justify="space-between" align="flex-start" wrap="nowrap" gap="md">
                <Box style={{ flex: 1, minWidth: 0 }}>
                  <Group gap={6} mb={4}>
                    <MantineBadge
                      size="xs"
                      radius="sm"
                      variant={active ? 'filled' : 'light'}
                      color={stateColor(job.state)}
                      leftSection={
                        active ? (
                          <IconClock size={10} />
                        ) : job.state === 'succeeded' ? (
                          <IconCheck size={10} />
                        ) : (
                          <IconAlertTriangle size={10} />
                        )
                      }
                    >
                      {active ? job.phase || job.state : job.state}
                    </MantineBadge>
                    {job.hypothesis_id && (
                      <MantineBadge size="xs" variant="light" color="gray" radius="sm">
                        {job.hypothesis_id}
                      </MantineBadge>
                    )}
                    {job.failure_class && (
                      <MantineBadge
                        size="xs"
                        variant="light"
                        radius="sm"
                        color={job.failure_class === 'SUCCESS' ? 'teal' : 'gray'}
                      >
                        {job.failure_class}
                      </MantineBadge>
                    )}
                    <Text size="xs" c="dimmed" style={{ fontFamily: 'monospace' }}>
                      {job.signal_name}
                    </Text>
                  </Group>

                  <Text size="sm" c="gray.2" fw={500} lineClamp={1}>
                    {job.title || job.question || job.job_id}
                  </Text>

                  {(active || stalled) && (
                    <Pipeline phases={job.phases} current={job.phase} failed={stalled} />
                  )}

                  {active && phaseDetail(job, now) && (
                    <Text size="xs" c="blue.4" mt={6}>
                      {phaseDetail(job, now)}
                    </Text>
                  )}

                  {stalled && job.error && (
                    <Text size="xs" c="red.5" mt={6} lineClamp={1}>
                      {job.error.split('\n')[0]}
                    </Text>
                  )}
                </Box>

                <Stack gap={2} align="flex-end" style={{ whiteSpace: 'nowrap' }}>
                  <Tooltip label={`${job.provider}/${job.model} · ${job.created_at}`} position="left">
                    <Text size="xs" c={active ? 'blue.4' : 'dimmed'} fw={600}>
                      {elapsed(job, now)}
                    </Text>
                  </Tooltip>
                </Stack>
              </Group>
            </Paper>
          );
        })}
      </Stack>

      <HypothesisModal id={openHypId} onClose={() => setOpenHypId(null)} />
    </Box>
  );
};
