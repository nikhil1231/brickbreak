import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  Center,
  Divider,
  Grid,
  Group,
  Loader,
  NumberInput,
  Paper,
  Progress,
  ScrollArea,
  SegmentedControl,
  Select,
  Slider,
  Spoiler,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  IconCheck,
  IconChevronLeft,
  IconChevronRight,
  IconEyeOff,
  IconInfoCircle,
  IconLock,
  IconTarget,
} from '@tabler/icons-react';
import {
  fetchSetupReview,
  fetchSetupReviewCase,
  fetchSetupReviewQueues,
  finalizeSetupReview,
  saveSetupReviewDraft,
} from '../../services/api';
import {
  SetupReviewCase,
  SetupReviewField,
  SetupReviewQueue,
  SetupReviewSummary,
} from '../../types';
import { SetupGrindPane } from './SetupGrindPane';

const REVIEWER_KEY = 'brickbreak.setupReviewer';

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'number') return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(4).replace(/0+$/, '').replace(/\.$/, '');
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  return String(value);
}

function options(field: SetupReviewField) {
  return (field.options || []).map((option) => typeof option === 'string'
    ? { value: option, label: option }
    : option);
}

function conditionMet(field: SetupReviewField, values: Record<string, unknown>) {
  if (!field.required_when) return true;
  return Object.entries(field.required_when).every(([name, value]) => values[name] === value);
}

const CHART_HEIGHT = 450;
const PRICE_TOP = 18;
const PRICE_BOTTOM = Math.floor(CHART_HEIGHT * 0.76);
const JUDGE_COLOURS = ['green', 'blue', 'grape', 'orange'];

export const SetupReviewView: React.FC = () => {
  const initialReviewer = localStorage.getItem(REVIEWER_KEY) || 'owner';
  const [queues, setQueues] = useState<SetupReviewSummary[]>([]);
  const [reviewId, setReviewId] = useState('');
  const [reviewer, setReviewer] = useState(initialReviewer);
  const [reviewerInput, setReviewerInput] = useState(initialReviewer);
  const [queue, setQueue] = useState<SetupReviewQueue | null>(null);
  const [caseId, setCaseId] = useState('');
  const [current, setCurrent] = useState<SetupReviewCase | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    fetchSetupReviewQueues(controller.signal)
      .then((items) => {
        setQueues(items);
        setReviewId((existing) => existing || items[0]?.review_id || '');
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!reviewId || !reviewer) return;
    const controller = new AbortController();
    setLoading(true);
    setError('');
    fetchSetupReview(reviewId, reviewer, controller.signal)
      .then((result) => {
        setQueue(result);
        setCaseId((existing) => {
          if (result.cases.some((item) => item.case_id === existing)) return existing;
          return result.cases.find((item) => !item.reviewed)?.case_id || result.cases[0]?.case_id || '';
        });
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [reviewId, reviewer]);

  useEffect(() => {
    if (!reviewId || !caseId || !reviewer) return;
    // Switching queues changes reviewId before the new queue resolves, so this
    // effect would otherwise fire once with the previous queue's case id and
    // surface a spurious "unknown case" error. Wait until the loaded queue is
    // the one being asked about and actually contains the case.
    if (!queue || queue.review_id !== reviewId) return;
    if (!queue.cases.some((item) => item.case_id === caseId)) return;
    const controller = new AbortController();
    setCurrent(null);
    fetchSetupReviewCase(reviewId, caseId, reviewer, controller.signal)
      .then((result) => {
        setCurrent(result);
        setValues(result.draft || {});
      })
      .catch((err) => setError(err.message));
    return () => controller.abort();
  }, [reviewId, caseId, reviewer, queue]);

  const grind = queue?.schema.ui_mode === 'grind';
  const currentIndex = queue?.cases.findIndex((item) => item.case_id === caseId) ?? -1;
  const scalarSidecar = useMemo(() => Object.entries(current?.sidecar || {})
    .filter(([, value]) => !Array.isArray(value) && (typeof value !== 'object' || value === null)), [current]);
  const relativeBars = Array.isArray(current?.sidecar?.relative_bars)
    ? current?.sidecar.relative_bars as Array<Record<string, unknown>>
    : [];
  const pickerField = queue?.schema.fields.find((field) => field.ui_control === 'chart_level_atr');

  const chartLinePosition = (offset: unknown): number | null => {
    if (!current || typeof offset !== 'number') return null;
    const last = Number(current.sidecar.last_close_rebased);
    const atr = Number(current.sidecar.atr_20_rebased);
    const visibleLow = Number(current.sidecar.visible_low_rebased);
    const visibleHigh = Number(current.sidecar.visible_high_rebased);
    if (![last, atr, visibleLow, visibleHigh].every(Number.isFinite) || atr <= 0 || visibleHigh <= visibleLow) return null;
    const padding = Math.max((visibleHigh - visibleLow) * 0.05, 0.05);
    const low = visibleLow - padding;
    const high = visibleHigh + padding;
    const price = last + offset * atr;
    const y = PRICE_TOP + (high - price) / (high - low) * (PRICE_BOTTOM - PRICE_TOP);
    return y < PRICE_TOP || y > PRICE_BOTTOM ? null : y / CHART_HEIGHT * 100;
  };

  const pickChartLevel = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!pickerField || !current || queue?.finalized || !conditionMet(pickerField, values)) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const y = (event.clientY - rect.top) / rect.height * CHART_HEIGHT;
    if (y < PRICE_TOP || y > PRICE_BOTTOM) {
      notifications.show({ color: 'yellow', message: 'Click inside the candle area, above the volume bars.' });
      return;
    }
    const last = Number(current.sidecar.last_close_rebased);
    const atr = Number(current.sidecar.atr_20_rebased);
    const visibleLow = Number(current.sidecar.visible_low_rebased);
    const visibleHigh = Number(current.sidecar.visible_high_rebased);
    if (![last, atr, visibleLow, visibleHigh].every(Number.isFinite) || atr <= 0 || visibleHigh <= visibleLow) {
      notifications.show({ color: 'red', message: 'This setup does not contain enough scale information for chart picking.' });
      return;
    }
    const padding = Math.max((visibleHigh - visibleLow) * 0.05, 0.05);
    const high = visibleHigh + padding;
    const low = visibleLow - padding;
    const price = high - (y - PRICE_TOP) / (PRICE_BOTTOM - PRICE_TOP) * (high - low);
    const rawOffset = (price - last) / atr;
    const step = pickerField.step || 0.05;
    updateValue(pickerField, Math.round(rawOffset / step) * step);
  };

  const applyReviewer = () => {
    const clean = reviewerInput.trim();
    if (!/^[A-Za-z0-9_.-]+$/.test(clean)) {
      notifications.show({ color: 'red', message: 'Reviewer ID may use letters, numbers, dot, dash and underscore.' });
      return;
    }
    localStorage.setItem(REVIEWER_KEY, clean);
    setReviewer(clean);
  };

  const updateValue = (field: SetupReviewField, value: unknown) => {
    setValues((previous) => {
      const next = { ...previous, [field.name]: value };
      for (const dependent of queue?.schema.fields || []) {
        if (dependent.required_when && field.name in dependent.required_when && !conditionMet(dependent, next)) {
          next[dependent.name] = null;
        }
      }
      return next;
    });
  };

  const move = (delta: number) => {
    if (!queue || currentIndex < 0) return;
    const target = queue.cases[currentIndex + delta];
    if (target) setCaseId(target.case_id);
  };

  // `commit` takes its values explicitly rather than reading state. The grind
  // keyboard handlers decide and save in one keystroke, and a handler that
  // closed over `values` would persist the state from before the keystroke.
  const commit = async (payload: Record<string, unknown>, advance: boolean, quiet = false) => {
    if (!queue || !current) return;
    setSaving(true);
    try {
      const updated = await saveSetupReviewDraft(queue.review_id, reviewer, current.case_id, payload);
      setQueue(updated);
      if (!quiet) notifications.show({ color: 'green', icon: <IconCheck size={16} />, message: 'Review saved locally.' });
      if (!advance) return;
      // In grind mode the deck is walked in its frozen order: jumping to the
      // first unreviewed case anywhere would let a repeat land next to its
      // original, which is the one thing the deck order exists to prevent.
      const next = grind
        ? updated.cases[currentIndex + 1]
        : updated.cases.find((item, index) => !item.reviewed && index > currentIndex)
          || updated.cases.find((item) => !item.reviewed);
      if (next) setCaseId(next.case_id);
    } catch (err) {
      notifications.show({ color: 'red', message: err instanceof Error ? err.message : String(err) });
    } finally {
      setSaving(false);
    }
  };

  const save = () => commit(values, true);

  const finalize = async () => {
    if (!queue || queue.progress.completed !== queue.progress.total) return;
    if (!window.confirm(`Finalize ${queue.progress.total} reviews as ${reviewer}? This pass cannot be edited afterwards.`)) return;
    setSaving(true);
    try {
      const updated = await finalizeSetupReview(queue.review_id, reviewer);
      setQueue(updated);
      const revealed = await fetchSetupReviewCase(queue.review_id, caseId, reviewer);
      setCurrent(revealed);
      notifications.show({ color: 'green', icon: <IconLock size={16} />, message: 'Human pass finalized and frozen.' });
    } catch (err) {
      notifications.show({ color: 'red', message: err instanceof Error ? err.message : String(err) });
    } finally {
      setSaving(false);
    }
  };

  const renderField = (field: SetupReviewField) => {
    const enabled = conditionMet(field, values);
    const value = values[field.name];
    const common = (
      <Box mb="md" key={`${field.name}-label`}>
        <Group gap={6} mb={4}>
          <Text size="sm" fw={600}>{field.label}</Text>
          {(field.required || (field.required_when && enabled)) && <Text c="red.5">*</Text>}
        </Group>
        {field.description && <Text size="xs" c="dimmed" mb={7}>{field.description}</Text>}
      </Box>
    );
    let control: React.ReactNode;
    if (field.type === 'boolean') {
      control = <SegmentedControl fullWidth styles={{ root: { maxWidth: '100%' }, label: { whiteSpace: 'normal', wordBreak: 'break-word', lineHeight: 1.25, paddingTop: 6, paddingBottom: 6 } }} disabled={!enabled || queue?.finalized} value={typeof value === 'boolean' ? String(value) : ''}
        data={[{ value: 'true', label: 'Yes' }, { value: 'false', label: 'No' }]}
        onChange={(next) => updateValue(field, next === 'true')} />;
    } else if (field.type === 'choice') {
      const data = options(field);
      control = data.length <= 4
        ? <SegmentedControl fullWidth styles={{ root: { maxWidth: '100%' }, label: { whiteSpace: 'normal', wordBreak: 'break-word', lineHeight: 1.25, paddingTop: 6, paddingBottom: 6 } }} disabled={!enabled || queue?.finalized} value={typeof value === 'string' ? value : ''} data={data} onChange={(next) => updateValue(field, next)} />
        : <Select disabled={!enabled || queue?.finalized} value={typeof value === 'string' ? value : null} data={data} onChange={(next) => updateValue(field, next)} />;
    } else if (field.type === 'number') {
      control = <Stack gap={6}>
        <NumberInput disabled={!enabled || queue?.finalized} value={typeof value === 'number' ? value : ''} min={field.min} max={field.max} step={field.step || 0.1} decimalScale={4} onChange={(next) => updateValue(field, next === '' ? null : Number(next))} />
        {field.ui_control === 'chart_level_atr' && enabled && !queue?.finalized && <Text size="xs" c="blue.4" fw={600}>Tip: click the candle chart to place this level visually.</Text>}
      </Stack>;
    } else if (field.type === 'scale') {
      const min = field.min ?? 0;
      const max = field.max ?? 1;
      const sliderValue = typeof value === 'number' ? value : min;
      control = <Stack gap={6}>
        <Group justify="space-between"><Text size="xs" c="dimmed">{min}</Text><Text size="sm" fw={700} c={typeof value === 'number' ? 'blue.4' : 'dimmed'}>{typeof value === 'number' ? value.toFixed(2) : 'Not set'}</Text><Text size="xs" c="dimmed">{max}</Text></Group>
        <Slider disabled={!enabled || queue?.finalized} value={sliderValue} min={min} max={max} step={field.step || 0.05} onChange={(next) => updateValue(field, next)} />
      </Stack>;
    } else {
      control = <Textarea disabled={!enabled || queue?.finalized} value={typeof value === 'string' ? value : ''} autosize minRows={3} maxRows={7} maxLength={field.max_length} onChange={(event) => updateValue(field, event.currentTarget.value)} />;
    }
    return <Box key={field.name} mb="lg" opacity={enabled ? 1 : 0.45}>{common}{control}</Box>;
  };

  if (loading && !queue) return <Center h="calc(100vh - 56px)"><Loader /></Center>;

  return (
    <Box p={{ base: 'md', lg: 'xl' }} maw={1500} mx="auto">
      <Group justify="space-between" align="flex-start" mb="lg">
        <Box>
          <Group gap="sm"><Title order={2}>Setup review</Title><Badge color="green" variant="light" leftSection={<IconEyeOff size={12} />}>Outcome locked</Badge></Group>
          <Text c="dimmed" mt={4}>A generic queue for reviewing suggested market setups exactly as they appeared at decision time.</Text>
        </Box>
        <Group align="flex-end">
          {queues.length > 1 && <Select label="Queue" value={reviewId} data={queues.map((item) => ({ value: item.review_id, label: item.title }))} onChange={(value) => setReviewId(value || '')} />}
          <TextInput label="Reviewer ID" value={reviewerInput} onChange={(event) => setReviewerInput(event.currentTarget.value)} onKeyDown={(event) => event.key === 'Enter' && applyReviewer()} />
          <Button variant="default" onClick={applyReviewer}>Use</Button>
        </Group>
      </Group>

      {error && <Alert color="red" mb="md" title="Review queue unavailable">{error}</Alert>}
      {!queue && !loading && <Alert color="gray">No frozen setup-review bundle is available.</Alert>}
      {queue && (
        <>
          <Paper p="md" mb="md">
            <Group justify="space-between" align="flex-start">
              <Box maw={800}>
                <Text fw={700}>{queue.schema.title}</Text>
                <Text size="sm" c="dimmed">{queue.schema.description}</Text>
              </Box>
              <Group gap="xs">
                <Badge variant="outline" color="gray">{reviewer}</Badge>
                {queue.finalized && <Badge color="green" leftSection={<IconLock size={12} />}>Finalized</Badge>}
              </Group>
            </Group>
            <Progress value={queue.progress.total ? queue.progress.completed / queue.progress.total * 100 : 0} mt="md" />
            <Text size="xs" c="dimmed" mt={5}>{queue.progress.completed} of {queue.progress.total} setups saved</Text>
          </Paper>

          {queue.schema.guide && (!grind || queue.progress.completed === 0) && <Paper p="lg" mb="md" style={{ borderColor: 'rgba(88, 166, 255, .4)' }}>
            <Group gap="sm" mb={5}><IconTarget size={21} color="var(--mantine-color-blue-4)" /><Text fw={750} size="lg">{queue.schema.guide.heading}</Text></Group>
            <Text c="dimmed" maw={1000}>{queue.schema.guide.summary}</Text>
            {queue.schema.guide.steps && <Grid gap="sm" mt="md">
              {queue.schema.guide.steps.map((step) => <Grid.Col key={step.title} span={{ base: 12, sm: 4 }}>
                <Box p="sm" h="100%" bg="rgba(88,166,255,.06)" style={{ border: '1px solid rgba(88,166,255,.16)', borderRadius: 8 }}>
                  <Text fw={700} size="sm" c="blue.3">{step.title}</Text>
                  <Text size="sm" mt={4}>{step.body}</Text>
                </Box>
              </Grid.Col>)}
            </Grid>}
            {queue.schema.guide.glossary && <Group gap="xs" mt="md">
              <Text size="xs" fw={700} c="dimmed" tt="uppercase">Terms</Text>
              {queue.schema.guide.glossary.map((item) => <Badge key={item.term} variant="light" color="gray" size="lg" tt="none" title={item.definition}>{item.term}: {item.definition}</Badge>)}
            </Group>}
          </Paper>}

          {grind ? (
            <SetupGrindPane queue={queue} current={current} currentIndex={currentIndex}
                            values={values} setValues={setValues} commit={(payload, advance) => commit(payload, advance, true)}
                            move={move} saving={saving} />
          ) : (
          <Grid gap="md">
            <Grid.Col span={{ base: 12, md: 2 }}>
              <Paper p="xs" h={{ base: 180, md: 'calc(100vh - 260px)' }}>
                <Text size="xs" fw={700} c="dimmed" tt="uppercase" p="xs">Setups</Text>
                <ScrollArea h={{ base: 130, md: 'calc(100vh - 310px)' }}>
                  <Stack gap={4}>
                    {queue.cases.map((item, index) => (
                      <Button key={item.case_id} variant={item.case_id === caseId ? 'light' : 'subtle'} color={item.reviewed ? 'green' : 'gray'} justify="space-between" fullWidth onClick={() => setCaseId(item.case_id)} rightSection={item.reviewed ? <IconCheck size={14} /> : null}>
                        <Text size="xs" ff="monospace">{String(index + 1).padStart(2, '0')}</Text>
                      </Button>
                    ))}
                  </Stack>
                </ScrollArea>
              </Paper>
            </Grid.Col>

            <Grid.Col span={{ base: 12, md: 7 }}>
              <Stack gap="md">
                <Paper p="md">
                  <Group justify="space-between" mb="sm">
                    <Text fw={700}>Setup {currentIndex + 1} of {queue.cases.length}</Text>
                    <Group gap="xs"><Button variant="default" size="xs" disabled={currentIndex <= 0} onClick={() => move(-1)} leftSection={<IconChevronLeft size={14} />}>Previous</Button><Button variant="default" size="xs" disabled={currentIndex >= queue.cases.length - 1} onClick={() => move(1)} rightSection={<IconChevronRight size={14} />}>Next</Button></Group>
                  </Group>
                  {pickerField && !queue.finalized && <Alert color={values.zone_exists === true ? 'blue' : 'gray'} mb="sm" icon={<IconInfoCircle size={16} />}>
                    {conditionMet(pickerField, values)
                      ? 'Click the centre of the strongest horizontal area on the chart. The blue line can be moved with another click.'
                      : 'First decide whether a convincing horizontal area exists. Choose “Yes” to enable click-to-place.'}
                  </Alert>}
                  {!current ? <Center h={480}><Loader /></Center> : current.media.kind === 'image' ? (
                    <Box pos="relative" onClick={pickChartLevel} style={{ cursor: pickerField && conditionMet(pickerField, values) && !queue.finalized ? 'crosshair' : 'default' }}>
                      <Box component="img" src={current.media.url} alt={`Anonymised setup ${currentIndex + 1}`} w="100%" display="block" style={{ borderRadius: 6, background: '#0d1117' }} />
                      {!current.finalized && chartLinePosition(values[pickerField?.name || '']) !== null && <Box pos="absolute" left="5.25%" right="2%" top={`${chartLinePosition(values[pickerField?.name || ''])}%`} style={{ borderTop: '2px solid var(--mantine-color-blue-4)', pointerEvents: 'none' }}><Badge pos="absolute" right={0} bottom={4} color="blue" size="xs">Your level · {Number(values[pickerField?.name || '']).toFixed(2)} ATR</Badge></Box>}
                      {current.finalized && current.judgements?.map((judgement, index) => {
                        const offset = judgement.values[pickerField?.name || ''];
                        const top = chartLinePosition(offset);
                        if (top === null) return null;
                        const label = judgement.annotator_kind === 'human' ? 'You' : judgement.model.replace('gpt-5.6-', '') || judgement.annotator;
                        return <Box key={judgement.annotator} pos="absolute" left="5.25%" right="2%" top={`${top}%`} style={{ borderTop: `2px solid var(--mantine-color-${JUDGE_COLOURS[index % JUDGE_COLOURS.length]}-5)`, pointerEvents: 'none' }}><Badge pos="absolute" right={0} bottom={4 + index * 18} color={JUDGE_COLOURS[index % JUDGE_COLOURS.length]} size="xs">{label} · {Number(offset).toFixed(2)} ATR</Badge></Box>;
                      })}
                    </Box>
                  ) : <Alert color="yellow">Unsupported media type: {current.media.kind}</Alert>}
                </Paper>

                {current?.finalized && current.reveal && <Paper p="md" style={{ borderColor: 'rgba(255,209,102,.45)' }}>
                  <Group gap="xs" mb="sm"><IconLock size={18} color="var(--mantine-color-yellow-5)" /><Text fw={700}>Ground truth</Text></Group>
                  <Text size="sm" c="dimmed" mb="md">Revealed because your pass is frozen. It could not have reached this screen before you committed.</Text>
                  <Grid gap="xs">
                    {Object.entries(current.reveal).map(([key, value]) => <Grid.Col span={{ base: 6, sm: 3 }} key={key}><Box p="xs" bg="rgba(255,209,102,.07)" style={{ borderRadius: 6 }}><Text size="xs" c="dimmed">{key.replace(/_/g, ' ')}</Text><Text fw={700} ff="monospace">{displayValue(value)}</Text></Box></Grid.Col>)}
                  </Grid>
                </Paper>}

                {current?.finalized && current.judgements && <Paper p="md" style={{ borderColor: 'rgba(63,185,80,.35)' }}>
                  <Group gap="xs" mb="sm"><IconCheck size={18} color="var(--mantine-color-green-5)" /><Text fw={700}>Blind judgements revealed</Text></Group>
                  <Text size="sm" c="dimmed" mb="md">Your full pass is frozen, so the independent model answers can no longer influence it.</Text>
                  <Grid gap="sm">
                    {current.judgements.map((judgement, index) => {
                      const name = judgement.annotator_kind === 'human' ? 'You' : judgement.model.replace('gpt-5.6-', '') || judgement.annotator;
                      return <Grid.Col key={judgement.annotator} span={{ base: 12, sm: 4 }}><Box p="sm" h="100%" bg="rgba(255,255,255,.025)" style={{ borderTop: `3px solid var(--mantine-color-${JUDGE_COLOURS[index % JUDGE_COLOURS.length]}-5)`, borderRadius: 6 }}><Text fw={750} mb="xs">{name}</Text>{queue.schema.fields.map((field) => <Box key={field.name} mb={7}><Text size="xs" c="dimmed">{field.label}</Text><Text size="sm" fw={field.name === 'notes' ? 400 : 650}>{displayValue(judgement.values[field.name])}</Text></Box>)}</Box></Grid.Col>;
                    })}
                  </Grid>
                </Paper>}

                <Paper p="md">
                  <Text fw={700} mb="sm">Context available at decision time</Text>
                  <Grid gap="xs">
                    {scalarSidecar.map(([key, value]) => <Grid.Col span={{ base: 6, sm: 4 }} key={key}><Box p="xs" bg="rgba(255,255,255,.025)" style={{ borderRadius: 6 }}><Text size="xs" c="dimmed">{key.replace(/_/g, ' ')}</Text><Text fw={600} ff="monospace">{displayValue(value)}</Text></Box></Grid.Col>)}
                  </Grid>
                  {relativeBars.length > 0 && <><Divider my="md" /><Text size="sm" fw={600} mb="xs">Recent bars</Text><ScrollArea><Table fz="xs" withTableBorder withColumnBorders><Table.Thead><Table.Tr>{Object.keys(relativeBars[0]).map((key) => <Table.Th key={key}>{key.toUpperCase()}</Table.Th>)}</Table.Tr></Table.Thead><Table.Tbody>{relativeBars.map((bar, index) => <Table.Tr key={index}>{Object.keys(relativeBars[0]).map((key) => <Table.Td key={key} ff="monospace">{displayValue(bar[key])}</Table.Td>)}</Table.Tr>)}</Table.Tbody></Table></ScrollArea></>}
                </Paper>
              </Stack>
            </Grid.Col>

            <Grid.Col span={{ base: 12, md: 3 }}>
              <Paper p="md" h={{ md: 'calc(100vh - 260px)' }}>
                <ScrollArea h={{ md: 'calc(100vh - 350px)' }} offsetScrollbars>
                  <Text fw={700} mb={4}>Your judgement</Text>
                  <Alert color="gray" mb="md" icon={<IconEyeOff size={15} />}>
                    Judge independently. Model answers stay hidden until all {queue.progress.total} setups are finalized.
                  </Alert>
                  <Spoiler maxHeight={82} showLabel="Show full instructions" hideLabel="Hide instructions" mb="lg">
                    <Text size="xs" c="dimmed" style={{ whiteSpace: 'pre-line' }}>{queue.schema.instructions}</Text>
                  </Spoiler>
                  {queue.schema.fields.map(renderField)}
                </ScrollArea>
                <Divider my="md" />
                <Button fullWidth loading={saving} disabled={queue.finalized || !current} onClick={save}>Save & next unreviewed</Button>
              </Paper>
            </Grid.Col>
          </Grid>)}

          <Paper p="md" mt="md">
            <Group justify="space-between">
              <Box><Text fw={700}>Freeze this review pass</Text><Text size="xs" c="dimmed">Finalization writes one complete, immutable human pass to the experiment bundle.</Text></Box>
              <Button color="green" leftSection={<IconLock size={15} />} loading={saving} disabled={queue.finalized || queue.progress.completed !== queue.progress.total} onClick={finalize}>{queue.finalized ? 'Pass finalized' : 'Finalize all reviews'}</Button>
            </Group>
          </Paper>
        </>
      )}
    </Box>
  );
};
