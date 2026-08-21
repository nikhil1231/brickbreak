import React, { useEffect, useState } from 'react';
import { fetchIdeaGraph } from '../../services/api';
import { IdeaGraphData } from '../../types';
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  Node,
  Edge,
  MarkerType,
} from '@xyflow/react';
import {
  Paper,
  Text,
  Table,
  Group,
  Loader,
  Alert,
  Code,
  Tabs,
  Badge as MantineBadge,
  Box,
} from '@mantine/core';
import {
  IconBinaryTree,
  IconAlertCircle,
  IconTable,
  IconNetwork,
} from '@tabler/icons-react';

export const IdeaGraphView: React.FC = () => {
  const [data, setData] = useState<IdeaGraphData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<string>('graph');

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  useEffect(() => {
    fetchIdeaGraph()
      .then((res) => {
        setData(res);
        setLoading(false);

        // Layout nodes in columns/grid based on family or ID
        const nodeMap = new Map();
        const initialNodes: Node[] = [];

        const spacingX = 260;
        const spacingY = 100;
        const cols = 4;

        (res.nodes || []).forEach((n, idx) => {
          const row = Math.floor(idx / cols);
          const col = idx % cols;
          const nodeObj: Node = {
            id: n.id,
            position: { x: col * spacingX + 40, y: row * spacingY + 40 },
            data: {
              label: (
                <div style={{ textAlign: 'left', padding: '2px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '6px' }}>
                    <strong style={{ color: '#58a6ff', fontSize: '12px' }}>{n.id}</strong>
                    <span style={{ fontSize: '9px', textTransform: 'uppercase', color: '#8b949e' }}>{n.status}</span>
                  </div>
                  <div style={{ fontSize: '11px', color: '#c9d1d9', marginTop: '2px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '180px' }}>
                    {n.title}
                  </div>
                </div>
              ),
            },
            style: {
              background: '#161b22',
              color: '#c9d1d9',
              border: '1px solid #30363d',
              borderRadius: '8px',
              padding: '8px 12px',
              width: 210,
              boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
            },
          };
          nodeMap.set(n.id, nodeObj);
          initialNodes.push(nodeObj);
        });

        const initialEdges: Edge[] = (res.edges || []).map((e, idx) => ({
          id: `e-${e.source}-${e.target}-${idx}`,
          source: e.source,
          target: e.target,
          label: e.relation,
          labelStyle: { fill: '#79c0ff', fontSize: 10, fontFamily: 'monospace' },
          labelBgStyle: { fill: '#0d1117', fillOpacity: 0.8 },
          labelBgPadding: [4, 2] as [number, number],
          labelBgBorderRadius: 4,
          style: { stroke: '#58a6ff', strokeWidth: 1.5 },
          markerEnd: { type: MarkerType.ArrowClosed, color: '#58a6ff' },
          animated: e.relation === 'specialises' || e.relation === 'conditions-on',
        }));

        setNodes(initialNodes);
        setEdges(initialEdges);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, [setNodes, setEdges]);

  if (loading) {
    return (
      <Group justify="center" p="xl" style={{ minHeight: '50vh' }}>
        <Loader size="md" color="blue" />
        <Text size="sm" c="dimmed">
          Building idea graph network...
        </Text>
      </Group>
    );
  }

  return (
    <Box p="lg" style={{ maxWidth: '1400px', margin: '0 auto' }}>
      <Paper p="lg" radius="md" mb="md">
        <Group justify="space-between" mb="sm">
          <Group gap="sm">
            <IconBinaryTree size={20} color="var(--mantine-color-blue-4)" />
            <Text size="md" fw={700} c="white">
              Idea Graph Network
            </Text>
            {data && <MantineBadge color="blue" size="sm">{data.edges?.length || 0} Lineage Edges</MantineBadge>}
          </Group>
          <Text size="xs" c="dimmed">
            {data?.summary || 'Hypothesis lineage connections and relationship edges.'}
          </Text>
        </Group>

        {error && (
          <Alert icon={<IconAlertCircle size={16} />} title="Graph Error" color="red" mb="md">
            {error}
          </Alert>
        )}

        <Tabs value={activeTab} onChange={(v) => setActiveTab(v || 'graph')} mb="md">
          <Tabs.List>
            <Tabs.Tab value="graph" leftSection={<IconNetwork size={14} />}>
              Interactive Network View
            </Tabs.Tab>
            <Tabs.Tab value="table" leftSection={<IconTable size={14} />}>
              Edges Ledger Table
            </Tabs.Tab>
          </Tabs.List>
        </Tabs>

        {activeTab === 'graph' ? (
          <Box
            style={{
              height: '620px',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              overflow: 'hidden',
              background: '#0d1117',
            }}
          >
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              fitView
              colorMode="dark"
            >
              <Background color="#21262d" gap={16} size={1} />
              <Controls />
              <MiniMap
                nodeColor="#30363d"
                maskColor="rgba(13, 17, 23, 0.7)"
                style={{ background: '#161b22', border: '1px solid #30363d' }}
              />
            </ReactFlow>
          </Box>
        ) : (
          <Table highlightOnHover style={{ fontSize: '12.5px' }}>
            <Table.Thead>
              <Table.Tr style={{ background: '#0e131a' }}>
                <Table.Th>Source Hypothesis</Table.Th>
                <Table.Th>Relationship / Edge Type</Table.Th>
                <Table.Th>Target Hypothesis</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {(data?.edges || []).map((e, idx) => (
                <Table.Tr key={idx}>
                  <Table.Td>
                    <Text size="xs" fw={700} c="blue.4">
                      {e.source}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Code color="blue">{e.relation}</Code>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" fw={700} c="white">
                      {e.target}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Paper>
    </Box>
  );
};
