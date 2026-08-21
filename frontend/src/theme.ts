import { createTheme, MantineColorsTuple } from '@mantine/core';

const brandBlue: MantineColorsTuple = [
  '#e6f1ff',
  '#cce3ff',
  '#99c7ff',
  '#66abff',
  '#338fff',
  '#0073ff',
  '#005cd6',
  '#0045ad',
  '#002e85',
  '#00175c',
];

export const theme = createTheme({
  primaryColor: 'blue',
  colors: {
    brand: brandBlue,
  },
  fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  fontFamilyMonospace: '"SFMono-Regular", Consolas, "Liberation Mono", Menlo, Courier, monospace',
  defaultRadius: 'md',
  components: {
    Paper: {
      defaultProps: {
        bg: '#161b22',
        withBorder: true,
      },
    },
    Card: {
      defaultProps: {
        bg: '#161b22',
        withBorder: true,
      },
    },
    Button: {
      defaultProps: {
        size: 'sm',
      },
    },
    Table: {
      defaultProps: {
        highlightOnHover: true,
        striped: false,
      },
    },
  },
});
