import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  Code,
  CopyButton,
  Group,
  List,
  Loader,
  Paper,
  Progress,
  Stack,
  Text,
  TextInput,
  ThemeIcon,
  Tooltip,
} from '@mantine/core';
import {
  IconAlertCircle,
  IconCheck,
  IconCopy,
  IconExternalLink,
  IconKey,
  IconRefresh,
  IconSettings,
} from '@tabler/icons-react';
import { notifications } from '@mantine/notifications';
import { fetchBreezeSettings, fetchBreezeTotp } from '../../services/api';
import { BreezeSettings, BreezeTotp } from '../../types';

export const SettingsView: React.FC = () => {
  const [settings, setSettings] = useState<BreezeSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [totp, setTotp] = useState<BreezeTotp | null>(null);
  const [totpError, setTotpError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchBreezeSettings()
      .then(setSettings)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const loadTotp = useCallback(() => {
    fetchBreezeTotp()
      .then((value) => {
        setTotp(value);
        setTotpError(null);
      })
      .catch((err) => {
        setTotp(null);
        setTotpError(err.message);
      });
  }, []);

  useEffect(() => {
    if (!settings?.totp_configured) {
      setTotp(null);
      setTotpError(null);
      return;
    }
    loadTotp();
    const timer = window.setInterval(loadTotp, 1000);
    return () => window.clearInterval(timer);
  }, [loadTotp, settings?.totp_configured]);

  useEffect(() => {
    window.addEventListener('focus', load);
    return () => window.removeEventListener('focus', load);
  }, [load]);

  useEffect(() => {
    const receiveAuth = (event: MessageEvent) => {
      const backendOrigin = settings ? new URL(settings.callback_url).origin : null;
      if ((event.origin !== window.location.origin && event.origin !== backendOrigin)
          || event.data?.type !== 'breeze-auth-complete') return;
      if (event.data.success) {
        notifications.show({
          title: 'Breeze connected',
          message: 'The verified daily session token was saved to .env.',
          color: 'teal',
          icon: <IconCheck size={16} />,
        });
        load();
      } else {
        notifications.show({
          title: 'Breeze login failed',
          message: 'Review the message in the login window and try again.',
          color: 'red',
        });
      }
    };
    window.addEventListener('message', receiveAuth);
    return () => window.removeEventListener('message', receiveAuth);
  }, [load, settings]);

  const beginLogin = () => {
    if (!settings) return;
    const loginUrl = new URL(settings.login_url || settings.login_path, window.location.href);
    loginUrl.searchParams.set('opener_origin', window.location.origin);
    const loginTab = window.open(loginUrl.toString(), '_blank');
    if (!loginTab) window.location.assign(loginUrl.toString());
  };

  const refreshedAt = settings?.session_refreshed_at
    ? new Date(settings.session_refreshed_at).toLocaleString(undefined, {
        dateStyle: 'medium',
        timeStyle: 'medium',
      })
    : null;

  return (
    <Box p="lg" style={{ maxWidth: '900px', margin: '0 auto' }}>
      <Group gap="sm" mb="lg">
        <ThemeIcon variant="light" color="blue" radius="md">
          <IconSettings size={18} />
        </ThemeIcon>
        <div>
          <Text size="lg" fw={700} c="white">Settings</Text>
          <Text size="xs" c="dimmed">Local integrations and credentials</Text>
        </div>
      </Group>

      <Paper p="xl" radius="md">
        <Group justify="space-between" align="flex-start" mb="lg">
          <Group gap="sm">
            <ThemeIcon variant="light" color="cyan" radius="md">
              <IconKey size={18} />
            </ThemeIcon>
            <div>
              <Text fw={700} c="white">ICICI Direct Breeze</Text>
              <Text size="xs" c="dimmed">Daily browser session for historical market data</Text>
            </div>
          </Group>
          <Stack gap={4} align="flex-end">
            {loading ? (
              <Loader size="sm" />
            ) : settings?.has_session_token ? (
              <Badge color="teal" variant="light">Token saved</Badge>
            ) : (
              <Badge color="yellow" variant="light">Login needed</Badge>
            )}
            {!loading && settings?.has_session_token && (
              <Text size="xs" c="dimmed">
                {refreshedAt ? `Last refreshed ${refreshedAt}` : 'Last refresh time unavailable'}
              </Text>
            )}
          </Stack>
        </Group>

        {(error || settings?.error) && (
          <Alert icon={<IconAlertCircle size={16} />} title="Breeze configuration" color="red" mb="lg">
            {error || settings?.error}
          </Alert>
        )}

        {settings && (
          <Stack gap="lg">
            <div>
              <Text size="sm" fw={600} c="white" mb={6}>Registered callback URL</Text>
              <Text size="xs" c="dimmed" mb="sm">
                Set this exact redirect URL on your Breeze API app once. The port must match the server command.
              </Text>
              <Group gap="xs" wrap="nowrap">
                <TextInput
                  value={settings.callback_url}
                  readOnly
                  aria-label="Breeze callback URL"
                  styles={{ input: { fontFamily: 'var(--mantine-font-family-monospace)' } }}
                  style={{ flex: 1 }}
                />
                <CopyButton value={settings.callback_url} timeout={1600}>
                  {({ copied, copy }) => (
                    <Tooltip label={copied ? 'Copied' : 'Copy callback URL'}>
                      <Button variant="default" onClick={copy} px="sm" aria-label="Copy callback URL">
                        {copied ? <IconCheck size={16} /> : <IconCopy size={16} />}
                      </Button>
                    </Tooltip>
                  )}
                </CopyButton>
              </Group>
            </div>

            <div>
              <Group justify="space-between" mb={6}>
                <div>
                  <Text size="sm" fw={600} c="white">Authenticator code</Text>
                  <Text size="xs" c="dimmed">Generated locally from BREEZE_TOTP_SECRET</Text>
                </div>
                {settings.totp_configured && (
                  <Badge color="violet" variant="light">Auto-refreshing</Badge>
                )}
              </Group>

              {settings.totp_configured ? (
                <Paper p="md" radius="md" bg="#0d1117">
                  {totpError ? (
                    <Alert icon={<IconAlertCircle size={16} />} color="red">
                      {totpError}
                    </Alert>
                  ) : totp ? (
                    <Stack gap="xs">
                      <Group justify="space-between" align="center">
                        <Text
                          ff="monospace"
                          fz={30}
                          fw={700}
                          c="white"
                          style={{ letterSpacing: '0.22em', fontVariantNumeric: 'tabular-nums' }}
                        >
                          {totp.code}
                        </Text>
                        <CopyButton value={totp.code} timeout={1600}>
                          {({ copied, copy }) => (
                            <Button variant="default" onClick={copy} leftSection={copied ? <IconCheck size={15} /> : <IconCopy size={15} />}>
                              {copied ? 'Copied' : 'Copy code'}
                            </Button>
                          )}
                        </CopyButton>
                      </Group>
                      <Progress
                        value={(totp.valid_for_seconds / totp.period_seconds) * 100}
                        color={totp.valid_for_seconds <= 5 ? 'red' : 'violet'}
                        size="sm"
                        animated
                      />
                      <Text size="xs" c="dimmed">
                        Refreshes in {totp.valid_for_seconds}s
                      </Text>
                    </Stack>
                  ) : (
                    <Group gap="xs"><Loader size="xs" /><Text size="xs" c="dimmed">Generating code…</Text></Group>
                  )}
                </Paper>
              ) : (
                <Alert color="gray" variant="light">
                  Add <Code>BREEZE_TOTP_SECRET=YOUR_BASE32_SEED</Code> to <Code>.env</Code>, then restart the server.
                </Alert>
              )}
            </div>

            <Alert color="blue" variant="light" title="How refresh works">
              <List size="sm" spacing={6}>
                <List.Item>brickbreak opens the official ICICI Direct login page.</List.Item>
                <List.Item>ICICI redirects back to this local server with <Code>apisession</Code>.</List.Item>
                <List.Item>The server verifies it with Breeze, then atomically updates only <Code>BREEZE_SESSION_TOKEN</Code> in <Code>.env</Code>.</List.Item>
              </List>
            </Alert>

            <Group justify="space-between" align="center">
              <Text size="xs" c="dimmed" maw={500}>
                Breeze sessions expire daily. API key and secret remain server-side and are never returned to the browser.
              </Text>
              <Button
                leftSection={settings.has_session_token ? <IconRefresh size={16} /> : <IconExternalLink size={16} />}
                onClick={beginLogin}
                disabled={!settings.configured}
              >
                {settings.has_session_token ? 'Refresh Breeze login' : 'Connect Breeze'}
              </Button>
            </Group>
          </Stack>
        )}
      </Paper>
    </Box>
  );
};
