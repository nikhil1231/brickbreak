import React from 'react';
import { Slider as MantineSlider, Text, Group, Box } from '@mantine/core';

interface SliderProps {
  label: string;
  value: number | null | undefined;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  isNullableCeiling?: boolean;
  onChange: (val: number | null) => void;
}

export const Slider: React.FC<SliderProps> = ({
  label,
  value,
  min,
  max,
  step = 1,
  unit = '',
  isNullableCeiling = false,
  onChange,
}) => {
  const currentVal = value != null ? value : max;
  const isOff = isNullableCeiling && (value == null || currentVal >= max);

  const displayVal = isOff
    ? 'off'
    : `${Math.abs(currentVal) < 10 && step < 1 ? currentVal.toFixed(2).replace(/\.00$/, '') : currentVal.toFixed(0)}${unit}`;

  return (
    <Box mb="xs">
      <Group justify="space-between" mb={2}>
        <Text size="xs" c="gray.3">
          {label}
        </Text>
        <Text size="xs" fw={700} c={isOff ? 'dimmed' : 'blue.4'} className="tabular-nums">
          {displayVal}
        </Text>
      </Group>
      <MantineSlider
        min={min}
        max={max}
        step={step}
        value={currentVal}
        size="xs"
        color="blue"
        onChange={(val) => {
          if (isNullableCeiling && val >= max) {
            onChange(null);
          } else {
            onChange(val);
          }
        }}
        label={null}
      />
    </Box>
  );
};
