import React from 'react';
import {
  Group,
  Text,
  Badge as MantineBadge,
  ThemeIcon,
  Loader,
  Box,
  UnstyledButton,
  Menu,
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
  IconSettings,
  IconChevronDown,
  IconChartCandle,
} from '@tabler/icons-react';

export type TabType = 'explore' | 'setups' | 'replays' | 'hypotheses' | 'graph' | 'compare' | 'ledger' | 'catalogue' | 'screener' | 'settings';

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
  const primaryTabs = [
    { id: 'explore', label: 'Explore', icon: IconCompass },
    { id: 'setups', label: 'Setup Review', icon: IconChartCandle },
    { id: 'hypotheses', label: 'Hypotheses', icon: IconBook },
    { id: 'ledger', label: 'Budget Ledger', icon: IconDatabase },
    { id: 'catalogue', label: 'Catalogue', icon: IconLayersLinked },
  ];

  const secondaryTabs = [
    { id: 'replays', label: 'Replays', icon: IconGavel },
    { id: 'graph', label: 'Idea Graph', icon: IconBinaryTree },
    { id: 'compare', label: 'Signal Compare', icon: IconGitCompare },
    { id: 'screener', label: 'Daily Screener', icon: IconAdjustments },
    { id: 'settings', label: 'Settings', icon: IconSettings },
  ];

  return (
    <Box
      component="header"
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
      <Box px={{ base: 'md', md: 'xl' }} style={{ maxWidth: 1120, margin: '0 auto', width: '100%', height: '100%' }}>
        <Group justify="space-between" align="center" style={{ width: '100%', height: '100%' }} wrap="nowrap">
          {/* Left Section: Logo & Nav */}
          <Group gap="xl" wrap="nowrap" style={{ height: '100%' }}>
            {/* Brand Logo & Meta */}
            <Group gap="sm" wrap="nowrap">
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
            <Group gap={1} wrap="nowrap" style={{ height: '56px' }}>
              {primaryTabs.map((tab) => {
                const Icon = tab.icon;
                const isActive = activeTab === tab.id;
                return (
                  <UnstyledButton
                    key={tab.id}
                    onClick={() => onTabChange(tab.id as TabType)}
                    px={8}
                    h="100%"
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      color: isActive ? '#ffffff' : 'var(--mantine-color-gray-5)',
                      fontSize: '12.5px',
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

              <Menu shadow="md" width={200} position="bottom-end" offset={4} withArrow>
                <Menu.Target>
                  <UnstyledButton
                    px={8}
                    h="100%"
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      color: secondaryTabs.some(t => t.id === activeTab) ? '#ffffff' : 'var(--mantine-color-gray-5)',
                      fontSize: '12.5px',
                      fontWeight: secondaryTabs.some(t => t.id === activeTab) ? 600 : 450,
                      borderBottom: secondaryTabs.some(t => t.id === activeTab) ? '2px solid var(--mantine-color-blue-4)' : '2px solid transparent',
                      transition: 'all 0.15s ease',
                      whiteSpace: 'nowrap',
                      position: 'relative',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.color = '#ffffff';
                    }}
                    onMouseLeave={(e) => {
                      if (!secondaryTabs.some(t => t.id === activeTab)) e.currentTarget.style.color = 'var(--mantine-color-gray-5)';
                    }}
                  >
                    <span>More</span>
                    <IconChevronDown size={14} stroke={1.75} />
                  </UnstyledButton>
                </Menu.Target>

                <Menu.Dropdown bg="rgba(15, 19, 24, 0.95)" style={{ border: '1px solid rgba(255, 255, 255, 0.08)' }}>
                  {secondaryTabs.map((tab) => {
                    const Icon = tab.icon;
                    const isActive = activeTab === tab.id;
                    return (
                      <Menu.Item
                        key={tab.id}
                        leftSection={<Icon size={14} />}
                        onClick={() => onTabChange(tab.id as TabType)}
                        style={{
                          color: isActive ? '#ffffff' : 'var(--mantine-color-gray-5)',
                          backgroundColor: isActive ? 'rgba(255, 255, 255, 0.05)' : 'transparent',
                          fontSize: '13px',
                        }}
                      >
                        {tab.label}
                      </Menu.Item>
                    );
                  })}
                </Menu.Dropdown>
              </Menu>
            </Group>
          </Group>

          {/* Status / Activity Indicator */}
          <Box style={{ minWidth: '24px', display: 'flex', justifyContent: 'flex-end' }}>
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
    </Box>
  );
};
