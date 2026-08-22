import React from 'react';
import {
  Group,
  Text,
  Badge as MantineBadge,
  ThemeIcon,
  Loader,
  Box,
  UnstyledButton,
} from '@mantine/core';
import {
  IconCompass,
  IconBook,
  IconGavel,
  IconBinaryTree,
  IconGitCompare,
  IconDatabase,
  IconLayersLinked,
  IconAdjustments,
  IconFlame,
} from '@tabler/icons-react';

export type TabType = 'explore' | 'replays' | 'hypotheses' | 'graph' | 'compare' | 'ledger' | 'catalogue' | 'screener';

interface HeaderProps {
  activeTab: TabType;
  onTabChange: (tab: TabType) => void;
  statusText?: string;
  metaText?: string;
}

export const Header: React.FC<HeaderProps> = ({
  activeTab,
  onTabChange,
  statusText,
  metaText,
}) => {
  const tabs = [
    { id: 'explore', label: 'Explore', icon: IconCompass },
    { id: 'replays', label: 'Replays', icon: IconGavel },
    { id: 'hypotheses', label: 'Hypotheses', icon: IconBook },
    { id: 'graph', label: 'Idea Graph', icon: IconBinaryTree },
    { id: 'compare', label: 'Signal Compare', icon: IconGitCompare },
    { id: 'ledger', label: 'Budget Ledger', icon: IconDatabase },
    { id: 'catalogue', label: 'Catalogue', icon: IconLayersLinked },
    { id: 'screener', label: 'Daily Screener', icon: IconAdjustments },
  ];

  return (
    <Box
      component="header"
      px="xl"
      h={56}
      bg="rgba(15, 19, 24, 0.85)"
      style={{
        backdropFilter: 'blur(12px)',
        borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
        position: 'sticky',
        top: 0,
        zIndex: 100,
        display: 'flex',
        alignItems: 'center',
      }}
    >
      <Group justify="space-between" align="center" style={{ width: '100%' }} wrap="nowrap">
        {/* Brand Logo & Meta */}
        <Group gap="md" wrap="nowrap">
          <Group gap={8} align="center" wrap="nowrap" style={{ cursor: 'pointer' }} onClick={() => onTabChange('explore')}>
            <ThemeIcon size="sm" radius="sm" variant="gradient" gradient={{ from: 'blue.5', to: 'cyan.4', deg: 135 }}>
              <IconFlame size={14} />
            </ThemeIcon>
            <Text size="sm" fw={700} c="white" style={{ letterSpacing: '-0.02em', whiteSpace: 'nowrap' }}>
              brickbreak <Text span c="blue.4" fw={500}>lab</Text>
            </Text>
          </Group>

          {metaText && (
            <MantineBadge
              variant="subtle"
              color="gray"
              size="xs"
              radius="sm"
              style={{
                background: 'rgba(255, 255, 255, 0.03)',
                border: '1px solid rgba(255, 255, 255, 0.06)',
                color: 'var(--mantine-color-gray-5)',
                fontWeight: 500,
              }}
            >
              {metaText}
            </MantineBadge>
          )}
        </Group>

        {/* Lightweight Modern Navigation Tabs */}
        <Group gap={4} wrap="nowrap" style={{ height: '56px' }}>
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <UnstyledButton
                key={tab.id}
                onClick={() => onTabChange(tab.id as TabType)}
                px="sm"
                h="100%"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  color: isActive ? '#ffffff' : 'var(--mantine-color-gray-5)',
                  fontSize: '13px',
                  fontWeight: isActive ? 600 : 450,
                  borderBottom: isActive ? '2px solid var(--mantine-color-blue-4)' : '2px solid transparent',
                  transition: 'all 0.15s ease',
                  whiteSpace: 'nowrap',
                  position: 'relative',
                }}
                onMouseEnter={(e) => {
                  if (!isActive) e.currentTarget.style.color = '#ffffff';
                }}
                onMouseLeave={(e) => {
                  if (!isActive) e.currentTarget.style.color = 'var(--mantine-color-gray-5)';
                }}
              >
                <Icon size={15} stroke={isActive ? 2 : 1.75} style={{ opacity: isActive ? 1 : 0.7 }} />
                <span>{tab.label}</span>
              </UnstyledButton>
            );
          })}
        </Group>

        {/* Status / Activity Indicator */}
        <Box style={{ minWidth: '80px', display: 'flex', justifyContent: 'flex-end' }}>
          {statusText ? (
            <Group gap={6} wrap="nowrap">
              <Loader size={12} color="blue" />
              <Text size="xs" c="blue.4" fw={500}>
                {statusText}
              </Text>
            </Group>
          ) : (
            <Box />
          )}
        </Box>
      </Group>
    </Box>
  );
};
