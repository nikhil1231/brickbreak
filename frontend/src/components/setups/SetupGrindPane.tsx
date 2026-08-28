import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Badge, Box, Center, Group, Kbd, Loader, Paper, Progress, Stack, Text } from '@mantine/core';
import { SetupReviewCase, SetupReviewQueue } from '../../types';

/**
 * The grind layout: one chart, two keys, and nothing else on the screen.
 *
 * The deliberative review layout beside this one is right for sixty cases that
 * each deserve a paragraph. It is wrong for a hundred and fifty where the
 * measurement *is* how fast the no's go by -- a form that takes twenty seconds
 * to fill turns a four-second judgement into a twenty-four-second one, and the
 * take rate it produces is a fact about the form.
 *
 * So: F and J decide, three clicks place the prices, 1-3 sets conviction and
 * the deck advances on its own. The next charts are preloaded so a decision is
 * never waiting on a network round trip, and the clock that measures the pace
 * starts when the image is actually on screen rather than when it was asked for.
 */

type Axis = {
  width: number; height: number; left: number; right: number;
  price_top: number; price_bottom: number; price_low: number; price_high: number;
};

const LEVELS = ['entry_atr', 'stop_atr', 'target_atr'] as const;
const LEVEL_LABEL: Record<string, string> = { entry_atr: 'Entry', stop_atr: 'Stop', target_atr: 'Target' };
const LEVEL_COLOUR: Record<string, string> = { entry_atr: '#58a6ff', stop_atr: '#ff6b6b', target_atr: '#42d392' };

function axisOf(current: SetupReviewCase | null): Axis | null {
  const axis = current?.sidecar?.axis as Axis | undefined;
  if (!axis || !Number.isFinite(axis.price_high) || axis.price_high <= axis.price_low) return null;
  return axis;
}

function priceFromY(axis: Axis, y: number): number {
  const span = axis.price_bottom - axis.price_top;
  return axis.price_low + (axis.price_bottom - y) / span * (axis.price_high - axis.price_low);
}

function yFromPrice(axis: Axis, price: number): number {
  const span = axis.price_bottom - axis.price_top;
  return axis.price_bottom - (price - axis.price_low) / (axis.price_high - axis.price_low) * span;
}

interface Props {
  queue: SetupReviewQueue;
  current: SetupReviewCase | null;
  currentIndex: number;
  values: Record<string, unknown>;
  setValues: React.Dispatch<React.SetStateAction<Record<string, unknown>>>;
  commit: (values: Record<string, unknown>, advance: boolean) => Promise<void>;
  move: (delta: number) => void;
  saving: boolean;
}

export const SetupGrindPane: React.FC<Props> = ({ queue, current, currentIndex, values, setValues, commit, move, saving }) => {
  const [shownAt, setShownAt] = useState<number | null>(null);
  const [flash, setFlash] = useState('');
  const rootRef = useRef<HTMLDivElement | null>(null);
  const axis = axisOf(current);
  const atr = Number(current?.sidecar?.atr_rebased);
  const lastClose = Number(current?.sidecar?.last_close_rebased ?? 100);
  const action = typeof values.action === 'string' ? values.action : '';

  // The next few charts are fetched now so that pressing J never waits. Three
  // is enough to stay ahead of a four-second pace without hoarding memory.
  useEffect(() => {
    for (const item of queue.cases.slice(currentIndex + 1, currentIndex + 4)) {
      const image = new Image();
      image.src = `/api/setup-reviews/${queue.review_id}/charts/${item.case_id}.png`;
    }
  }, [queue, currentIndex]);

  // Started on arrival and refined when the image paints. A cached preload can
  // fire `onLoad` before this component hears about it, and a null clock would
  // silently drop the pace measurement -- the whole reason Stage 0 exists -- so
  // the arrival time is the floor rather than nothing.
  useEffect(() => { setShownAt(Date.now()); }, [current?.case_id]);

  // Whatever the reviewer last touched -- the queue picker, a button -- keeps
  // focus otherwise, and a focused input swallows the first F. Losing the very
  // first keystroke with no explanation is how someone concludes the keys do
  // not work, so the pane takes focus for itself and takes it back on arrival
  // at each chart.
  useEffect(() => {
    const active = document.activeElement as HTMLElement | null;
    if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) active.blur();
    rootRef.current?.focus({ preventScroll: true });
  }, [current?.case_id]);

  const nextLevel = useMemo(() => LEVELS.find((name) => typeof values[name] !== 'number'), [values]);

  const elapsed = useCallback(() => (shownAt === null ? null : Math.round((Date.now() - shownAt) / 100) / 10), [shownAt]);

  const commitWith = useCallback(async (next: Record<string, unknown>) => {
    await commit({ ...next, seconds_elapsed: elapsed() }, true);
  }, [commit, elapsed]);

  const setAction = useCallback((value: string) => {
    if (queue.finalized) return;
    if (value === 'skip') {
      void commitWith({ action: 'skip', entry_atr: null, stop_atr: null, target_atr: null, conviction: null, notes: values.notes ?? null });
      return;
    }
    setValues((previous) => ({ ...previous, action: 'take' }));
  }, [queue.finalized, commitWith, setValues, values.notes]);

  const setConviction = useCallback((level: number) => {
    if (queue.finalized || action !== 'take') return;
    const next: Record<string, unknown> = { ...values, conviction: level };
    const complete = LEVELS.every((name) => typeof next[name] === 'number');
    if (!complete) {
      setValues(next);
      setFlash('Place entry, stop and target first.');
      return;
    }
    const entry = Number(next.entry_atr), stop = Number(next.stop_atr), target = Number(next.target_atr);
    if (!((stop < entry && entry < target) || (stop > entry && entry > target))) {
      setValues(next);
      setFlash('Entry must sit between the stop and the target.');
      return;
    }
    void commitWith(next);
  }, [queue.finalized, action, values, setValues, commitWith]);

  const place = useCallback((event: React.MouseEvent<HTMLImageElement>) => {
    if (queue.finalized || action !== 'take' || !axis || !Number.isFinite(atr) || atr <= 0) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const y = (event.clientY - rect.top) * (axis.height / rect.height);
    if (y < axis.price_top || y > axis.price_bottom) {
      setFlash('Click inside the price panel, above the volume bars.');
      return;
    }
    const offset = (priceFromY(axis, y) - lastClose) / atr;
    const target = nextLevel || 'entry_atr';
    setFlash('');
    setValues((previous) => ({ ...previous, [target]: Math.round(offset / 0.05) * 0.05 }));
  }, [queue.finalized, action, axis, atr, lastClose, nextLevel, setValues]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const tag = (event.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || event.metaKey || event.ctrlKey || event.altKey) return;
      const key = event.key.toLowerCase();
      if (key === 'f') { event.preventDefault(); setAction('take'); }
      else if (key === 'j') { event.preventDefault(); setAction('skip'); }
      else if (key === '1' || key === '2' || key === '3') { event.preventDefault(); setConviction(Number(key)); }
      else if (key === 'u') { event.preventDefault(); move(-1); }
      else if (key === 'backspace') {
        event.preventDefault();
        setFlash('');
        setValues((previous) => ({ ...previous, entry_atr: null, stop_atr: null, target_atr: null, conviction: null }));
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [setAction, setConviction, move, setValues]);

  const rr = useMemo(() => {
    const entry = Number(values.entry_atr), stop = Number(values.stop_atr), target = Number(values.target_atr);
    if (![entry, stop, target].every(Number.isFinite)) return null;
    const risk = Math.abs(entry - stop);
    return risk > 0 ? (Math.abs(target - entry) / risk) : null;
  }, [values]);

  const done = queue.progress.completed;
  const total = queue.progress.total;

  return (
    <Stack gap="sm" ref={rootRef} tabIndex={-1} style={{ outline: 'none' }}>
      <Paper p="sm">
        <Group justify="space-between" mb={6}>
          <Group gap="sm">
            <Text fw={750} ff="monospace">{String(currentIndex + 1).padStart(3, '0')} / {total}</Text>
            <Badge variant="light" color="gray">{done} saved</Badge>
            {saving && <Loader size="xs" />}
          </Group>
          <Group gap={6}>
            <Kbd>F</Kbd><Text size="xs" c="dimmed">take</Text>
            <Kbd>J</Kbd><Text size="xs" c="dimmed">skip</Text>
            <Kbd>1..3</Kbd><Text size="xs" c="dimmed">conviction</Text>
            <Kbd>U</Kbd><Text size="xs" c="dimmed">back</Text>
            <Kbd>⌫</Kbd><Text size="xs" c="dimmed">clear</Text>
          </Group>
        </Group>
        <Progress value={total ? done / total * 100 : 0} size="sm" />
      </Paper>

      <Paper p={0} style={{ overflow: 'hidden' }}>
        {!current ? <Center h={600}><Loader /></Center> : (
          <Box pos="relative">
            <Box
              component="img"
              key={current.case_id}
              src={current.media.url}
              alt={`Chart ${currentIndex + 1}`}
              w="100%"
              display="block"
              onLoad={() => setShownAt(Date.now())}
              onClick={place}
              style={{ cursor: action === 'take' ? 'crosshair' : 'default', background: '#0b1020' }}
            />
            {axis && Number.isFinite(atr) && LEVELS.map((name) => {
              const value = values[name];
              if (typeof value !== 'number') return null;
              const y = yFromPrice(axis, lastClose + value * atr);
              if (y < axis.price_top || y > axis.price_bottom) return null;
              return (
                <Box key={name} pos="absolute" left={`${axis.left / axis.width * 100}%`} right={`${(axis.width - axis.right) / axis.width * 100}%`}
                     top={`${y / axis.height * 100}%`}
                     style={{ borderTop: `2px solid ${LEVEL_COLOUR[name]}`, pointerEvents: 'none' }}>
                  <Badge pos="absolute" right={0} bottom={3} size="xs" styles={{ root: { background: LEVEL_COLOUR[name], color: '#0b1020' } }}>
                    {LEVEL_LABEL[name]} · {value.toFixed(2)} ATR
                  </Badge>
                </Box>
              );
            })}
          </Box>
        )}
      </Paper>

      <Paper p="sm">
        {action !== 'take' ? (
          <Group justify="space-between">
            <Text size="sm" c="dimmed">
              Is this a setup you would trade? <Kbd>F</Kbd> yes · <Kbd>J</Kbd> no. Most are a no.
            </Text>
            {queue.finalized && <Badge color="green">Pass frozen</Badge>}
          </Group>
        ) : (
          <Group justify="space-between" wrap="nowrap">
            <Group gap="lg">
              {LEVELS.map((name) => (
                <Box key={name}>
                  <Text size="xs" c="dimmed">{LEVEL_LABEL[name]}</Text>
                  <Text fw={700} ff="monospace" c={typeof values[name] === 'number' ? undefined : 'dimmed'}
                        style={{ color: typeof values[name] === 'number' ? LEVEL_COLOUR[name] : undefined }}>
                    {typeof values[name] === 'number' ? `${Number(values[name]).toFixed(2)} ATR` : '—'}
                  </Text>
                </Box>
              ))}
              <Box>
                <Text size="xs" c="dimmed">Reward : risk</Text>
                <Text fw={700} ff="monospace">{rr === null ? '—' : `${rr.toFixed(2)} R`}</Text>
              </Box>
            </Group>
            <Text size="sm" c={flash ? 'red.4' : 'blue.4'} fw={600} ta="right">
              {flash || (nextLevel ? `Click the chart to place the ${LEVEL_LABEL[nextLevel].toLowerCase()}.` : 'Press 1, 2 or 3 for conviction.')}
            </Text>
          </Group>
        )}
      </Paper>

      {queue.finalized && <Alert color="green">This pass is frozen. Nothing here can be edited.</Alert>}
    </Stack>
  );
};
