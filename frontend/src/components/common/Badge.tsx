import React from 'react';
import { Badge as MantineBadge, MantineColor } from '@mantine/core';

interface BadgeProps {
  status: string;
  className?: string;
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
  variant?: 'light' | 'filled' | 'outline' | 'dot';
}

export const Badge: React.FC<BadgeProps> = ({
  status,
  className,
  size = 'sm',
  variant = 'light',
}) => {
  const norm = (status || '').toLowerCase().replace(/[^a-z0-9_]/g, '_');

  let color: MantineColor = 'gray';

  if (['promising', 'validated', 'success', 'supported', 'train'].includes(norm)) {
    color = 'teal';
  } else if (['rejected', 'no_signal', 'fail', 'decayed'].includes(norm)) {
    color = 'red';
  } else if (['exploring', 'proposed', 'exploratory', 'validation'].includes(norm)) {
    color = 'blue';
  } else if (['signal_but_beta', 'unstable', 'inconclusive', 'test'].includes(norm)) {
    color = 'yellow';
  } else if (['high_turnover', 'superseded', 'forward', 'confirmatory'].includes(norm)) {
    color = 'grape';
  }

  return (
    <MantineBadge
      color={color}
      variant={variant}
      size={size}
      className={className}
      radius="sm"
      style={{ textTransform: 'uppercase', letterSpacing: '0.04em' }}
    >
      {status}
    </MantineBadge>
  );
};
