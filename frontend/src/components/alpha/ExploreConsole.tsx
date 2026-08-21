import React, { useEffect, useState } from 'react';
import { fetchHypotheses, fetchProviders, runExploration } from '../../services/api';
import { ExplorationResult, Hypothesis, ProviderCatalogue } from '../../types';
import { Badge } from '../common/Badge';
import { MetricBox } from '../common/MetricBox';
import {
  Paper,
  Text,
  TextInput,
  Textarea,
  Select,
  Button,
  SimpleGrid,
  Group,
  Stack,
  Alert,
  Code,
  List,
  ThemeIcon,
  Box,
  Badge as MantineBadge,
} from '@mantine/core';
import {
  IconPlayerPlay,
  IconArrowRight,
  IconHash,
  IconAlertCircle,
  IconSparkles,
} from '@tabler/icons-react';

function getNextHypothesisId(hypList: Hypothesis[]): string {
  let maxNum = 0;
  for (const h of hypList) {
    const match = h.id.match(/^H(\d+)$/i);
    if (match) {
      const num = parseInt(match[1], 10);
      if (num > maxNum) maxNum = num;
    }
  }
  const nextNum = maxNum > 0 ? maxNum + 1 : 1;
  return `H${nextNum.toString().padStart(3, '0')}`;
}

export const ExploreConsole: React.FC = () => {
  const [hypId, setHypId] = useState<string>('H039');
  const [question, setQuestion] = useState<string>(
    'Does relative strength against market and sector breadth predict 10-session forward returns?'
  );
  const [signalName, setSignalName] = useState<string>('custom_composite_rs');
  const [partition, setPartition] = useState<string>('train');
  const [provider, setProvider] = useState<string>('claude');
  const [model, setModel] = useState<string>('');
  const [providers, setProviders] = useState<ProviderCatalogue | null>(null);
  const [providerError, setProviderError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [result, setResult] = useState<ExplorationResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    // Fetch existing hypotheses to auto-increment the ID
    fetchHypotheses(controller.signal)
      .then((hyps) => {
        const nextId = getNextHypothesisId(hyps);
        setHypId(nextId);
        setSignalName(`${nextId.toLowerCase()}_signal`);
      })
      .catch(() => {
        // Fallback default
        setHypId('H039');
      });

    // Fetch LLM providers
    fetchProviders(controller.signal)
      .then((catalogue) => {
        setProviders(catalogue);
        const preferred =
          catalogue.providers.find((item) => item.id === catalogue.default_provider && item.available) ||
          catalogue.providers.find((item) => item.available);
        if (preferred) {
          setProvider(preferred.id);
          setModel(preferred.default_model || '');
        }
      })
      .catch((err: Error) => setProviderError(err.message));

    return () => controller.abort();
  }, []);

  const selectedProvider = providers?.providers.find((item) => item.id === provider);
  const providerChoices = (providers?.providers || []).map((item) => ({
    value: item.id,
    label: `${item.label}${item.available ? '' : ' (not installed)'}`,
    disabled: !item.available,
  }));
  const modelChoices = (selectedProvider?.models || []).map((item) => ({
    value: item.id || '__default__',
    label: item.label,
  }));

  const handleLaunch = async () => {
    if (!question.trim()) {
      setError('Please provide a research question.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await runExploration({
        hypothesis_id: hypId,
        question,
        signal_name: signalName || `${hypId.toLowerCase()}_signal`,
        partition,
        provider,
        model: model || undefined,
      });
      setResult(res);
    } catch (err: any) {
      setError(err.message || 'Exploration failed');
    } finally {
      setLoading(false);
    }
  };

  const pc = result?.evaluation?.predictive_content?.primary_ic;
  const q = result?.evaluation?.quantiles;

  return (
    <Box p="xl" style={{ maxWidth: '1200px', margin: '0 auto' }}>
      {/* Hero Exploration Form */}
      <Paper
        p="xl"
        radius="lg"
        mb="xl"
        bg="#161b22"
        style={{
          border: '1px solid var(--border)',
          boxShadow: '0 8px 30px rgba(0, 0, 0, 0.4)',
        }}
      >
        <Group justify="space-between" align="center" mb="lg">
          <Group gap="sm">
            <ThemeIcon size="lg" radius="md" variant="gradient" gradient={{ from: 'blue.5', to: 'cyan.4', deg: 135 }}>
              <IconSparkles size={18} />
            </ThemeIcon>
            <div>
              <Text size="lg" fw={700} c="white" style={{ letterSpacing: '-0.02em' }}>
                Formulate an Alpha Hypothesis
              </Text>
              <Text size="xs" c="dimmed">
                Describe a market anomaly or price action hypothesis in natural language.
              </Text>
            </div>
          </Group>

          <Group gap="xs">
            <Text size="xs" c="dimmed" fw={600} tt="uppercase" style={{ letterSpacing: '0.05em' }}>
              Auto-Assigned ID:
            </Text>
            <MantineBadge color="blue" variant="filled" size="lg" radius="sm" style={{ fontFamily: 'monospace' }}>
              {hypId}
            </MantineBadge>
          </Group>
        </Group>

        {/* Hero Input Element */}
        <Stack gap="md">
          <Textarea
            placeholder="Type your hypothesis question here... e.g. Do stocks with volume dry-up during consolidation breakout with higher expectancy across small-cap regimes?"
            minRows={4}
            autosize
            maxRows={10}
            value={question}
            onChange={(e) => setQuestion(e.currentTarget.value)}
            styles={{
              input: {
                fontSize: '16px',
                lineHeight: '1.6',
                padding: '16px 18px',
                background: '#0d1117',
                border: '1px solid var(--border)',
                borderRadius: '8px',
                color: '#ffffff',
                transition: 'border-color 0.2s ease, box-shadow 0.2s ease',
              },
            }}
          />

          {/* Secondary Controls Grid */}
          <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }} spacing="md" mt="xs">
            <TextInput
              label="Signal Name"
              size="xs"
              value={signalName}
              onChange={(e) => setSignalName(e.currentTarget.value)}
            />
            <Select
              label="Data Partition"
              size="xs"
              value={partition}
              onChange={(v) => setPartition(v || 'train')}
              data={[
                { label: 'train (exploration)', value: 'train' },
                { label: 'validation (intermediate tune)', value: 'validation' },
                { label: 'test (shuffled holdout)', value: 'test' },
                { label: 'forward (chronological live lane)', value: 'forward' },
              ]}
            />
            <Select
              label="LLM Provider"
              size="xs"
              value={provider}
              data={providerChoices}
              disabled={!providers}
              error={providerError}
              onChange={(value) => {
                const next = value || 'claude';
                setProvider(next);
                const option = providers?.providers.find((item) => item.id === next);
                setModel(option?.default_model || '');
              }}
            />
            <Select
              label="Model"
              size="xs"
              value={model || '__default__'}
              data={modelChoices}
              disabled={!selectedProvider?.available}
              onChange={(value) => setModel(value === '__default__' ? '' : (value || ''))}
            />
          </SimpleGrid>

          {/* Prominent Launch Button */}
          <Button
            leftSection={<IconPlayerPlay size={18} />}
            color="blue"
            size="lg"
            radius="md"
            mt="sm"
            fullWidth
            loading={loading}
            disabled={!selectedProvider?.available}
            onClick={handleLaunch}
            style={{
              fontWeight: 650,
              fontSize: '15px',
              letterSpacing: '0.01em',
              boxShadow: '0 4px 14px rgba(88, 166, 255, 0.25)',
            }}
          >
            Launch Autonomous Exploration
          </Button>
        </Stack>
      </Paper>

      {error && (
        <Alert icon={<IconAlertCircle size={16} />} title="Exploration Failed" color="red" mb="lg" radius="md">
          {error}
        </Alert>
      )}

      {/* Results Section */}
      {result && (
        <Paper p="lg" radius="md">
          <Group justify="space-between" mb="sm">
            <Group gap="sm">
              <Text size="md" fw={700} c="white">
                Exploration Result ({result.hypothesis_id})
              </Text>
              <Badge status={result.failure_class} size="lg" />
            </Group>
            {result.runtime_seconds != null && (
              <Text size="xs" c="dimmed">
                {result.provider || result.manifest?.provider_used}/
                {result.model || result.manifest?.model_used || 'cli-default'} · Runtime: {result.runtime_seconds}s
              </Text>
            )}
          </Group>

          <Alert
            variant="light"
            color={result.failure_class === 'VALIDATED' || result.failure_class === 'PROMISSING' ? 'teal' : 'blue'}
            radius="md"
            mb="md"
          >
            <Text size="sm" fw={500}>
              {result.interpretation}
            </Text>
          </Alert>

          <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md" mb="md">
            <SimpleGrid cols={2} spacing="sm">
              <MetricBox
                label="Mean Rank IC"
                value={pc?.mean_ic != null ? pc.mean_ic.toFixed(4) : '—'}
                highlight={pc?.mean_ic != null && pc.mean_ic > 0.03 ? 'green' : 'none'}
              />
              <MetricBox
                label="IC t-statistic"
                value={pc?.t_stat != null ? pc.t_stat.toFixed(2) : '—'}
                highlight={pc?.t_stat != null && Math.abs(pc.t_stat) >= 2.0 ? 'green' : 'none'}
              />
              <MetricBox
                label="Q5 - Q1 Spread"
                value={q?.q5_spread_bps != null ? `${q.q5_spread_bps.toFixed(0)} bps` : '—'}
              />
              <MetricBox
                label="Monotonicity"
                value={q?.q5_monotonicity != null ? q.q5_monotonicity.toFixed(3) : '—'}
              />
            </SimpleGrid>

            <Stack gap="xs">
              <Group gap={6}>
                <IconHash size={14} color="var(--mantine-color-dimmed)" />
                <Text size="xs" fw={700} tt="uppercase" c="dimmed">
                  Immutable Manifest Hash
                </Text>
              </Group>
              <Code block style={{ fontSize: '11px', maxHeight: '140px', overflowY: 'auto' }}>
                {JSON.stringify(result.manifest, null, 2)}
              </Code>
            </Stack>
          </SimpleGrid>

          {/* Suggested Next Moves */}
          {result.suggested_next_moves && result.suggested_next_moves.length > 0 && (
            <Box mt="md" pt="md" style={{ borderTop: '1px solid var(--border)' }}>
              <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb="xs">
                Suggested Next Moves
              </Text>
              <List
                spacing="xs"
                size="sm"
                icon={
                  <ThemeIcon color="blue" size={18} radius="xl">
                    <IconArrowRight size={12} />
                  </ThemeIcon>
                }
              >
                {result.suggested_next_moves.map((m, idx) => (
                  <List.Item key={idx}>
                    <Text size="xs">
                      <strong style={{ color: 'var(--text-bright)' }}>{m.action}</strong>{' '}
                      <span style={{ color: 'var(--mantine-color-blue-4)' }}>({m.relation})</span>: {m.rationale}
                    </Text>
                  </List.Item>
                ))}
              </List>
            </Box>
          )}
        </Paper>
      )}
    </Box>
  );
};
