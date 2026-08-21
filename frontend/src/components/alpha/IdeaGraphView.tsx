import React, { useEffect, useMemo, useState } from 'react';
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  SimulationLinkDatum,
  SimulationNodeDatum,
} from 'd3-force';
import { fetchHypothesisDetail, fetchIdeaGraph } from '../../services/api';
import { Hypothesis, IdeaGraphData, IdeaGraphEdge, IdeaGraphNode } from '../../types';
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
  Drawer,
  Stack,
  Divider,
  ScrollArea,
} from '@mantine/core';
import {
  IconBinaryTree,
  IconAlertCircle,
  IconTable,
  IconNetwork,
  IconArrowRight,
  IconFocus2,
} from '@tabler/icons-react';

const NODE_WIDTH = 232;
const NODE_HEIGHT = 78;

const LINEAGE_RELATIONS = new Set([
  'specialises',
  'generalises',
  'conditions-on',
  'subsumed-by',
  'retest-of',
]);

const RELATION_STYLE: Record<string, { color: string; dash?: string }> = {
  specialises: { color: '#58a6ff' },
  generalises: { color: '#58a6ff' },
  'conditions-on': { color: '#bc8cff' },
  'subsumed-by': { color: '#d29922' },
  'retest-of': { color: '#3fb950' },
  contradicts: { color: '#f85149', dash: '6 4' },
  'adjacent-to': { color: '#8b949e', dash: '3 5' },
};

const STATUS_COLOR: Record<string, string> = {
  validated: '#3fb950',
  promising: '#3fb950',
  rejected: '#f85149',
  superseded: '#bc8cff',
  exploring: '#58a6ff',
  proposed: '#8b949e',
  decayed: '#d29922',
};

type GraphNodeData = {
  label: React.ReactNode;
  hypothesis: IdeaGraphNode;
  placeholder: boolean;
};

function graphNodesWithPlaceholders(data: IdeaGraphData): IdeaGraphNode[] {
  const byId = new Map(data.nodes.map((node) => [node.id, node]));
  data.edges.forEach((edge) => {
    [edge.source, edge.target].forEach((id) => {
      if (!byId.has(id)) {
        byId.set(id, {
          id,
          title: 'Unregistered follow-up',
          family: 'proposal',
          status: 'proposed',
          tags: [],
          placeholder: true,
        });
      }
    });
  });
  return Array.from(byId.values());
}

type ForceNode = SimulationNodeDatum & { id: string };
type ForceEdge = SimulationLinkDatum<ForceNode> & IdeaGraphEdge;

/** The simulation is deterministic so the research map does not jump on reload. */
function seededRandom(): () => number {
  let seed = 0x5f3759df;
  return () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 0x100000000;
  };
}

/**
 * Place hypotheses from their persisted edge topology. Strong lineage edges
 * pull their nodes closer; lateral relationships still influence clusters but
 * do not overpower the family tree.
 */
export function layoutIdeaGraph(
  graphNodes: IdeaGraphNode[],
  graphEdges: IdeaGraphEdge[],
): Map<string, { x: number; y: number }> {
  const knownIds = new Set(graphNodes.map((node) => node.id));
  const nodes: ForceNode[] = graphNodes.map((node) => ({ id: node.id }));
  const links: ForceEdge[] = graphEdges
    .filter((edge) => knownIds.has(edge.source) && knownIds.has(edge.target))
    .map((edge) => ({ ...edge }));

  const simulation = forceSimulation<ForceNode>(nodes)
    .randomSource(seededRandom())
    .force(
      'link',
      forceLink<ForceNode, ForceEdge>(links)
        .id((node) => node.id)
        .distance((edge) => (LINEAGE_RELATIONS.has(edge.relation) ? 160 : 210))
        .strength((edge) => (LINEAGE_RELATIONS.has(edge.relation) ? 0.7 : 0.28)),
    )
    .force('charge', forceManyBody<ForceNode>().strength(-500).distanceMax(800))
    .force('collide', forceCollide<ForceNode>(110).strength(0.95).iterations(3))
    .force('center', forceCenter(0, 0).strength(0.08))
    .force('x', forceX<ForceNode>(0).strength(0.025))
    .force('y', forceY<ForceNode>(0).strength(0.04))
    .stop();

  for (let tick = 0; tick < 450; tick += 1) simulation.tick();

  const minX = Math.min(...nodes.map((node) => node.x || 0));
  const minY = Math.min(...nodes.map((node) => node.y || 0));
  const margin = 36;
  return new Map(
    nodes.map((node) => {
      return [
        node.id,
        {
          x: (node.x || 0) - minX + margin,
          y: (node.y || 0) - minY + margin,
        },
      ];
    }),
  );
}

function nodeLabel(node: IdeaGraphNode, placeholder: boolean): React.ReactNode {
  return (
    <div data-testid={`idea-node-${node.id}`} style={{ textAlign: 'left', padding: '1px 2px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
        <strong style={{ color: placeholder ? '#d29922' : '#58a6ff', fontSize: 12 }}>{node.id}</strong>
        <span style={{ fontSize: 9, textTransform: 'uppercase', color: '#8b949e' }}>
          {placeholder ? 'follow-up' : node.status}
        </span>
      </div>
      <div
        style={{
          fontSize: 11,
          color: '#c9d1d9',
          marginTop: 3,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          maxWidth: 194,
        }}
      >
        {node.title}
      </div>
      <div style={{ fontSize: 9, color: '#6e7681', marginTop: 2 }}>{node.family || 'general'}</div>
    </div>
  );
}

function toFlowGraph(data: IdeaGraphData): { nodes: Node<GraphNodeData>[]; edges: Edge[] } {
  const allGraphNodes = graphNodesWithPlaceholders(data);
  const positions = layoutIdeaGraph(allGraphNodes, data.edges || []);

  const nodes: Node<GraphNodeData>[] = allGraphNodes.map((node) => {
    const placeholder = Boolean(node.placeholder);
    return {
      id: node.id,
      position: positions.get(node.id) || { x: 0, y: 0 },
      data: { label: nodeLabel(node, placeholder), hypothesis: node, placeholder },
      style: {
        background: placeholder ? '#1c1912' : '#161b22',
        color: '#c9d1d9',
        border: `1px ${placeholder ? 'dashed' : 'solid'} ${placeholder ? '#9e6a03' : '#30363d'}`,
        borderLeft: `3px solid ${STATUS_COLOR[node.status] || '#8b949e'}`,
        borderRadius: 8,
        padding: '8px 10px',
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        boxShadow: '0 4px 12px rgba(0,0,0,0.28)',
        cursor: 'pointer',
      },
      ariaLabel: `${node.id}: ${node.title}. Click for details.`,
    };
  });

  const knownIds = new Set(allGraphNodes.map((node) => node.id));
  const edges: Edge[] = (data.edges || [])
    .filter((edge) => knownIds.has(edge.source) && knownIds.has(edge.target))
    .map((edge, index) => {
      const relationStyle = RELATION_STYLE[edge.relation] || { color: '#58a6ff' };
      return {
        id: `e-${edge.source}-${edge.target}-${index}`,
        source: edge.source,
        target: edge.target,
        data: { relation: edge.relation },
        type: 'smoothstep',
        label: undefined,
        labelStyle: { fill: relationStyle.color, fontSize: 10, fontFamily: 'monospace' },
        labelBgStyle: { fill: '#0d1117', fillOpacity: 0.92 },
        labelBgPadding: [5, 3] as [number, number],
        labelBgBorderRadius: 4,
        style: {
          stroke: relationStyle.color,
          strokeWidth: LINEAGE_RELATIONS.has(edge.relation) ? 1.7 : 1.1,
          strokeDasharray: relationStyle.dash,
          opacity: LINEAGE_RELATIONS.has(edge.relation) ? 0.48 : 0.2,
        },
        markerEnd: { type: MarkerType.ArrowClosed, color: relationStyle.color, width: 14, height: 14 },
      };
    });

  return { nodes, edges };
}

export const IdeaGraphView: React.FC = () => {
  const [data, setData] = useState<IdeaGraphData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<string>('graph');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedHypothesis, setSelectedHypothesis] = useState<Hypothesis | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [nodes, setNodes, onNodesChange] = useNodesState<Node<GraphNodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  useEffect(() => {
    const controller = new AbortController();
    fetchIdeaGraph(controller.signal)
      .then((res) => {
        const flowGraph = toFlowGraph(res);
        setData(res);
        setNodes(flowGraph.nodes);
        setEdges(flowGraph.edges);
        setLoading(false);
      })
      .catch((err) => {
        if (err.name === 'AbortError') return;
        setError(err.message);
        setLoading(false);
      });
    return () => controller.abort();
  }, [setNodes, setEdges]);

  const connectedIds = useMemo(() => {
    if (!selectedId) return new Set<string>();
    const ids = new Set<string>([selectedId]);
    edges.forEach((edge) => {
      if (edge.source === selectedId) ids.add(edge.target);
      if (edge.target === selectedId) ids.add(edge.source);
    });
    return ids;
  }, [edges, selectedId]);

  const visibleNodes = useMemo(
    () =>
      nodes.map((node) => {
        const isSelected = node.id === selectedId;
        const isConnected = !selectedId || connectedIds.has(node.id);
        return {
          ...node,
          selected: isSelected,
          style: {
            ...node.style,
            opacity: isConnected ? 1 : 0.18,
            borderColor: isSelected ? '#79c0ff' : node.style?.borderColor,
            boxShadow: isSelected
              ? '0 0 0 2px rgba(88,166,255,0.32), 0 8px 22px rgba(0,0,0,0.4)'
              : node.style?.boxShadow,
          },
        };
      }),
    [nodes, connectedIds, selectedId],
  );

  const visibleEdges = useMemo(
    () =>
      edges.map((edge) => {
        const isConnected = Boolean(
          selectedId && (edge.source === selectedId || edge.target === selectedId),
        );
        const relation = String(edge.data?.relation || '');
        return {
          ...edge,
          label: isConnected ? relation : undefined,
          animated: isConnected && LINEAGE_RELATIONS.has(relation),
          zIndex: isConnected ? 5 : 0,
          style: {
            ...edge.style,
            opacity: selectedId ? (isConnected ? 1 : 0.035) : edge.style?.opacity,
            strokeWidth: isConnected ? 2.5 : edge.style?.strokeWidth,
          },
        };
      }),
    [edges, selectedId],
  );

  const handleSelectNode = async (id: string) => {
    setSelectedId(id);
    setSelectedHypothesis(null);

    const node = nodes.find((candidate) => candidate.id === id);
    if (node?.data.placeholder) return;

    setDetailLoading(true);
    try {
      setSelectedHypothesis(await fetchHypothesisDetail(id));
    } catch (err: any) {
      setError(err.message || `Failed to load ${id}`);
    } finally {
      setDetailLoading(false);
    }
  };

  const selectedNode = nodes.find((node) => node.id === selectedId)?.data.hypothesis;
  const selectedEdges = (data?.edges || []).filter(
    (edge) => edge.source === selectedId || edge.target === selectedId,
  );

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
    <Box p="lg" style={{ maxWidth: '1500px', margin: '0 auto' }}>
      <Paper p="lg" radius="md" mb="md">
        <Group justify="space-between" mb="sm">
          <Group gap="sm">
            <IconBinaryTree size={20} color="var(--mantine-color-blue-4)" />
            <Text size="md" fw={700} c="white">
              Idea Graph Network
            </Text>
            {data && <MantineBadge color="blue" size="sm">{data.edges?.length || 0} Typed Edges</MantineBadge>}
          </Group>
          <Text size="xs" c="dimmed">
            {data?.summary || 'Hypothesis lineage connections and relationship edges.'}
          </Text>
        </Group>

        {error && (
          <Alert
            icon={<IconAlertCircle size={16} />}
            title="Graph Error"
            color="red"
            mb="md"
            withCloseButton
            onClose={() => setError(null)}
          >
            {error}
          </Alert>
        )}

        <Tabs value={activeTab} onChange={(value) => setActiveTab(value || 'graph')} mb="md">
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
          <>
            <Group justify="space-between" mb="xs" gap="md">
              <Text size="xs" c="dimmed">
                Nodes are ranked from the stored edge topology. Click one to inspect it and focus its immediate neighborhood.
              </Text>
              <Group gap="sm" wrap="wrap">
                {Object.entries(RELATION_STYLE).map(([relation, relationStyle]) => (
                  <Group key={relation} gap={4} wrap="nowrap">
                    <Box
                      w={18}
                      style={{
                        borderTop: `2px ${relationStyle.dash ? 'dashed' : 'solid'} ${relationStyle.color}`,
                      }}
                    />
                    <Text size="10px" c="dimmed">{relation}</Text>
                  </Group>
                ))}
              </Group>
            </Group>
            <Box
              style={{
                height: '680px',
                border: '1px solid var(--border)',
                borderRadius: 8,
                overflow: 'hidden',
                background: '#0d1117',
              }}
            >
              <ReactFlow
                nodes={visibleNodes}
                edges={visibleEdges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onNodeClick={(_, node) => handleSelectNode(node.id)}
                onPaneClick={() => setSelectedId(null)}
                fitView
                fitViewOptions={{ padding: 0.14, maxZoom: 0.9 }}
                minZoom={0.08}
                maxZoom={1.8}
                colorMode="dark"
                nodesFocusable
                edgesFocusable
              >
                <Background color="#21262d" gap={18} size={1} />
                <Controls />
                <MiniMap
                  nodeColor={(node) =>
                    STATUS_COLOR[String((node.data as GraphNodeData | undefined)?.hypothesis?.status)] ||
                    '#30363d'
                  }
                  maskColor="rgba(13, 17, 23, 0.72)"
                  style={{ background: '#161b22', border: '1px solid #30363d' }}
                  pannable
                  zoomable
                />
              </ReactFlow>
            </Box>
          </>
        ) : (
          <ScrollArea h={680}>
            <Table highlightOnHover stickyHeader style={{ fontSize: '12.5px' }}>
              <Table.Thead>
                <Table.Tr style={{ background: '#0e131a' }}>
                  <Table.Th>Source Hypothesis</Table.Th>
                  <Table.Th>Relationship / Edge Type</Table.Th>
                  <Table.Th>Target Hypothesis</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {(data?.edges || []).map((edge, index) => (
                  <Table.Tr key={`${edge.source}-${edge.target}-${index}`}>
                    <Table.Td>
                      <Text size="xs" fw={700} c="blue.4">{edge.source}</Text>
                    </Table.Td>
                    <Table.Td><Code color="blue">{edge.relation}</Code></Table.Td>
                    <Table.Td>
                      <Text size="xs" fw={700} c="white">{edge.target}</Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea>
        )}
      </Paper>

      <Drawer
        opened={Boolean(selectedId)}
        onClose={() => {
          setSelectedId(null);
          setSelectedHypothesis(null);
        }}
        position="right"
        size="lg"
        title={
          selectedNode && (
            <Group gap="sm" wrap="nowrap">
              <IconFocus2 size={18} color="var(--mantine-color-blue-4)" />
              <Text fw={700} c="blue.4">{selectedNode.id}</Text>
              <MantineBadge color="gray" variant="light" size="sm">{selectedNode.status}</MantineBadge>
            </Group>
          )
        }
      >
        {selectedNode && (
          <Stack gap="md">
            <div>
              <Text size="lg" fw={650} c="white">{selectedNode.title}</Text>
              <Text size="xs" c="dimmed" mt={4}>{selectedNode.family || 'general'} family</Text>
            </div>

            {detailLoading && <Loader size="sm" />}

            {selectedNode.placeholder ? (
              <Alert color="yellow" title="Unregistered follow-up">
                This edge points to a proposed next move that has not been promoted to a hypothesis yet.
              </Alert>
            ) : selectedHypothesis ? (
              <>
                <div>
                  <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={4}>Statement</Text>
                  <Text size="sm" c="gray.2">
                    {selectedHypothesis.statement || 'No statement registered.'}
                  </Text>
                </div>
                <div>
                  <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={4}>Rationale</Text>
                  <Text size="sm" c="gray.4">
                    {selectedHypothesis.rationale || 'No rationale registered.'}
                  </Text>
                </div>
              </>
            ) : null}

            <Divider color="var(--border)" />
            <div>
              <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={7}>
                Direct graph relationships ({selectedEdges.length})
              </Text>
              <Stack gap={6}>
                {selectedEdges.length === 0 && <Text size="sm" c="dimmed">No recorded edges.</Text>}
                {selectedEdges.map((edge, index) => (
                  <Paper key={`${edge.source}-${edge.target}-${index}`} p="xs" bg="#0d1117" radius="sm">
                    <Group gap={6} wrap="nowrap">
                      <Text size="xs" fw={700} c={edge.source === selectedId ? 'blue.4' : 'white'}>
                        {edge.source}
                      </Text>
                      <IconArrowRight size={13} color={RELATION_STYLE[edge.relation]?.color || '#58a6ff'} />
                      <Code color="blue">{edge.relation}</Code>
                      <IconArrowRight size={13} color={RELATION_STYLE[edge.relation]?.color || '#58a6ff'} />
                      <Text size="xs" fw={700} c={edge.target === selectedId ? 'blue.4' : 'white'}>
                        {edge.target}
                      </Text>
                    </Group>
                  </Paper>
                ))}
              </Stack>
            </div>

            {selectedHypothesis?.evidence && selectedHypothesis.evidence.length > 0 && (
              <div>
                <Divider color="var(--border)" mb="md" />
                <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={7}>
                  Recorded evidence ({selectedHypothesis.evidence.length})
                </Text>
                <Stack gap="xs">
                  {selectedHypothesis.evidence.map((evidence, index) => (
                    <Paper key={evidence.evidence_id || index} p="xs" bg="#0d1117" radius="sm">
                      <Group gap={6} mb={4}>
                        <MantineBadge size="xs" color="blue" variant="light">{evidence.role}</MantineBadge>
                        <Text size="xs" c="dimmed">{evidence.partition}</Text>
                      </Group>
                      <Text size="xs" c="white">{evidence.verdict_statement}</Text>
                    </Paper>
                  ))}
                </Stack>
              </div>
            )}
          </Stack>
        )}
      </Drawer>
    </Box>
  );
};
