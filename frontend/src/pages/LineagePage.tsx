import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Upload, X, ChevronRight, Database, ArrowRight, Layers, GitBranch, Search, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react';
import { Card } from '../components/ui/Card';
import { Empty } from '../components/ui/Empty';
import { Spinner } from '../components/ui/Spinner';
import { useToast } from '../components/ui/Toast';
import { lineageApi } from '../api/client';

interface Props {
  selectedCdm: string | null;
}

interface LineageNode {
  table: string;
  layer: string;
  system: string;
}

interface ColumnMapping {
  source: string;
  destination: string;
  type?: string;
  comment?: string;
  default_value?: string;
}

interface LineageEdge {
  source: string;
  target: string;
  transformation_file: string;
  description: string;
  layer: string;
  column_mappings: ColumnMapping[];
  sql?: string;
  transformation_code?: string;
  where_filter?: string;
}

interface ChainEntry {
  from: string;
  to: string;
  file: string;
  description: string;
  columns_count: number;
  upstream?: ChainEntry[];
}

interface LineageData {
  metadata: { doc_date: string; author: string; total_nodes: number; total_edges: number };
  source_systems: Record<string, { name: string; type: string; description: string }>;
  nodes: Record<string, LineageNode>;
  edges: LineageEdge[];
  omop_chains: Record<string, ChainEntry[]>;
}

const LAYER_COLORS: Record<string, { bg: string; border: string; text: string; label: string }> = {
  source:    { bg: '#1e3a5f', border: '#3b82f6', text: '#60a5fa', label: 'Sources' },
  staging:   { bg: '#1a3a2a', border: '#22c55e', text: '#4ade80', label: 'Staging' },
  omop:      { bg: '#3b1f4a', border: '#a855f7', text: '#c084fc', label: 'OMOP CDM' },
  reference: { bg: '#3a2f1a', border: '#f59e0b', text: '#fbbf24', label: 'Reference' },
};

const LAYER_HEADERS: Record<string, string> = {
  source: 'SYSTEMES SOURCES',
  staging: 'COUCHE STAGING',
  omop: 'OMOP CDM',
};

export default function LineagePage({ selectedCdm }: Props) {
  const { t } = useTranslation();
  const toast = useToast();
  const svgRef = useRef<SVGSVGElement>(null);
  const gRef = useRef<SVGGElement>(null);

  const [lineage, setLineage] = useState<LineageData | null>(null);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [hasDoc, setHasDoc] = useState<boolean | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [visibleLayers, setVisibleLayers] = useState(new Set(['source', 'staging', 'omop', 'reference']));
  const [viewMode, setViewMode] = useState<'omop' | 'full'>('omop');
  const [searchTerm, setSearchTerm] = useState('');

  // Zoom/pan state
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const dragRef = useRef<{ dragging: boolean; startX: number; startY: number } | null>(null);

  const fetchLineage = useCallback(async () => {
    if (!selectedCdm) return;
    setLoading(true);
    try {
      const res = await lineageApi.get(selectedCdm);
      setLineage(res.data.lineage);
      setHasDoc(true);
    } catch (e: any) {
      if (e?.response?.status === 404) {
        setHasDoc(false);
      } else {
        toast.error('Failed to load lineage');
      }
    } finally {
      setLoading(false);
    }
  }, [selectedCdm]);

  useEffect(() => {
    setLineage(null);
    setHasDoc(null);
    setSelectedNode(null);
    fetchLineage();
  }, [selectedCdm]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !selectedCdm) return;
    setUploading(true);
    try {
      await lineageApi.upload(selectedCdm, file);
      toast.success('Lineage uploaded');
      await fetchLineage();
    } catch {
      toast.error('Upload failed');
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  // Compute filtered nodes & edges
  const { filteredNodes, filteredEdges } = useMemo(() => {
    if (!lineage) return { filteredNodes: {}, filteredEdges: [] };

    let edges = lineage.edges;
    let nodes = lineage.nodes;

    if (viewMode === 'omop') {
      const omopTables = new Set(Object.entries(nodes).filter(([, v]) => v.layer === 'omop').map(([k]) => k));
      // BFS backwards from OMOP tables
      const byTarget: Record<string, LineageEdge[]> = {};
      edges.forEach(e => { (byTarget[e.target] = byTarget[e.target] || []).push(e); });
      const result = new Set<LineageEdge>();
      const queue = [...omopTables];
      const visited = new Set<string>();
      while (queue.length) {
        const table = queue.shift()!;
        if (visited.has(table)) continue;
        visited.add(table);
        (byTarget[table] || []).forEach(e => { result.add(e); queue.push(e.source); });
      }
      edges = [...result];
      const usedNodes = new Set<string>();
      edges.forEach(e => { usedNodes.add(e.source); usedNodes.add(e.target); });
      nodes = Object.fromEntries(Object.entries(nodes).filter(([k]) => usedNodes.has(k)));
    }

    // Apply layer filter
    edges = edges.filter(e => visibleLayers.has(e.layer));
    const usedInEdges = new Set<string>();
    edges.forEach(e => { usedInEdges.add(e.source); usedInEdges.add(e.target); });
    nodes = Object.fromEntries(Object.entries(nodes).filter(([k, v]) =>
      usedInEdges.has(k) && visibleLayers.has(v.layer)));

    // Apply search
    if (searchTerm) {
      const lower = searchTerm.toLowerCase();
      const matchNodes = new Set(Object.keys(nodes).filter(k => k.toLowerCase().includes(lower)));
      // Include edges connected to matched nodes
      edges = edges.filter(e => matchNodes.has(e.source) || matchNodes.has(e.target));
      const used = new Set<string>();
      edges.forEach(e => { used.add(e.source); used.add(e.target); });
      nodes = Object.fromEntries(Object.entries(nodes).filter(([k]) => used.has(k)));
    }

    return { filteredNodes: nodes, filteredEdges: edges };
  }, [lineage, viewMode, visibleLayers, searchTerm]);

  // Compute layout
  const layout = useMemo(() => {
    const columns: Record<string, string[]> = { source: [], staging: [], omop: [] };
    Object.entries(filteredNodes).forEach(([name, info]) => {
      if (columns[info.layer]) columns[info.layer].push(name);
    });

    // Sort for better edge routing
    const targetOrder: Record<string, number> = {};
    filteredEdges.filter(e => filteredNodes[e.target]?.layer === 'omop')
      .forEach((e, i) => { if (!(e.target in targetOrder)) targetOrder[e.target] = i; });
    columns.omop.sort((a, b) => (targetOrder[a] || 0) - (targetOrder[b] || 0));

    const stagingToOmop: Record<string, number> = {};
    filteredEdges.filter(e => filteredNodes[e.source]?.layer === 'staging' && filteredNodes[e.target]?.layer === 'omop')
      .forEach(e => { if (!(e.source in stagingToOmop)) stagingToOmop[e.source] = targetOrder[e.target] || 0; });
    columns.staging.sort((a, b) => (stagingToOmop[a] || 0) - (stagingToOmop[b] || 0));

    const sourceToStaging: Record<string, number> = {};
    filteredEdges.filter(e => filteredNodes[e.source]?.layer === 'source' && filteredNodes[e.target]?.layer === 'staging')
      .forEach(e => { if (!(e.source in sourceToStaging)) sourceToStaging[e.source] = stagingToOmop[e.target] || 0; });
    columns.source.sort((a, b) => (sourceToStaging[a] || 0) - (sourceToStaging[b] || 0));

    const nodeW = 200, nodeH = 38, gapY = 10, gapX = 120;
    const positions: Record<string, { x: number; y: number; w: number; h: number }> = {};
    const colX: Record<string, number> = {};
    let xOffset = 40;

    (['source', 'staging', 'omop'] as const).forEach(layer => {
      if (!columns[layer].length) return;
      colX[layer] = xOffset;
      columns[layer].forEach((name, i) => {
        positions[name] = { x: xOffset, y: 50 + i * (nodeH + gapY), w: nodeW, h: nodeH };
      });
      xOffset += nodeW + gapX;
    });

    return { positions, colX };
  }, [filteredNodes, filteredEdges]);

  // Auto-fit on layout change
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg || !Object.keys(layout.positions).length) return;
    fitView();
  }, [layout]);

  const fitView = useCallback(() => {
    const svg = svgRef.current;
    if (!svg || !Object.keys(layout.positions).length) return;
    const allPos = Object.values(layout.positions);
    const minX = Math.min(...allPos.map(p => p.x)) - 40;
    const minY = Math.min(...allPos.map(p => p.y)) - 40;
    const maxX = Math.max(...allPos.map(p => p.x + p.w)) + 40;
    const maxY = Math.max(...allPos.map(p => p.y + p.h)) + 40;
    const bw = maxX - minX, bh = maxY - minY;
    const sw = svg.clientWidth, sh = svg.clientHeight;
    const scale = Math.min(sw / bw, sh / bh, 1.2) * 0.9;
    setTransform({
      x: (sw - bw * scale) / 2 - minX * scale,
      y: (sh - bh * scale) / 2 - minY * scale,
      scale,
    });
  }, [layout]);

  // Wheel zoom
  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 0.92 : 1.08;
    const rect = svgRef.current!.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    setTransform(prev => ({
      x: mx - (mx - prev.x) * factor,
      y: my - (my - prev.y) * factor,
      scale: prev.scale * factor,
    }));
  }, []);

  // Pan
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if ((e.target as Element).closest('.lineage-node')) return;
    dragRef.current = { dragging: true, startX: e.clientX - transform.x, startY: e.clientY - transform.y };
  }, [transform]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragRef.current?.dragging) return;
    setTransform(prev => ({ ...prev, x: e.clientX - dragRef.current!.startX, y: e.clientY - dragRef.current!.startY }));
  }, []);

  const handleMouseUp = useCallback(() => {
    if (dragRef.current) dragRef.current.dragging = false;
  }, []);

  // Edge paths
  const edgePaths = useMemo(() => {
    return filteredEdges.map((e, i) => {
      const src = layout.positions[e.source];
      const tgt = layout.positions[e.target];
      if (!src || !tgt) return null;
      const sx = src.x + src.w, sy = src.y + src.h / 2;
      const tx = tgt.x, ty = tgt.y + tgt.h / 2;
      const mx = (sx + tx) / 2;
      const isHighlighted = hoveredNode === e.source || hoveredNode === e.target;
      return (
        <path
          key={i}
          d={`M${sx},${sy} C${mx},${sy} ${mx},${ty} ${tx},${ty}`}
          fill="none"
          stroke={LAYER_COLORS[e.layer]?.border || '#555'}
          strokeWidth={isHighlighted ? 2.5 : 1.5}
          opacity={isHighlighted ? 1 : hoveredNode ? 0.15 : 0.4}
          markerEnd={`url(#arrow-${e.layer})`}
        />
      );
    });
  }, [filteredEdges, layout, hoveredNode]);

  // Detail panel data
  const detailData = useMemo(() => {
    if (!selectedNode || !lineage) return null;
    const node = lineage.nodes[selectedNode];
    if (!node) return null;
    const incoming = lineage.edges.filter(e => e.target === selectedNode);
    const outgoing = lineage.edges.filter(e => e.source === selectedNode);
    const chain = lineage.omop_chains?.[selectedNode];
    return { node, incoming, outgoing, chain };
  }, [selectedNode, lineage]);

  if (!selectedCdm) return <Empty variant="no-cdm" />;
  if (loading) return <div className="flex items-center justify-center h-64"><Spinner size="large" /></div>;

  if (hasDoc === false) {
    return (
      <div className="py-6 flex flex-col items-center gap-4">
        <Empty variant="no-data" title="No lineage data" description="Upload an ETL HTML documentation to visualize data lineage" />
        <label className="flex items-center gap-2 px-4 py-2 rounded-lg bg-accent-green text-white cursor-pointer hover:bg-accent-green/80 transition">
          <Upload size={16} />
          <span className="text-sm font-medium">Upload ETL Doc (.html)</span>
          <input type="file" accept=".html" className="hidden" onChange={handleUpload} disabled={uploading} />
        </label>
        {uploading && <Spinner size="small" tip="Parsing ETL doc..." />}
      </div>
    );
  }

  if (!lineage) return null;

  return (
    <div className="h-[calc(100vh-80px)] flex flex-col">
      {/* Toolbar */}
      <div className="flex items-center gap-3 px-3 py-2 bg-surface-card border-b border-border-subtle">
        <GitBranch size={16} className="text-accent-green" />
        <span className="text-sm font-semibold text-text-bright">Lineage</span>
        <span className="text-xs text-text-muted">{lineage.metadata.author} — {lineage.metadata.doc_date}</span>

        {/* Stats */}
        <div className="flex gap-4 ml-4">
          <Stat label="Tables" value={Object.keys(filteredNodes).length} />
          <Stat label="Flux" value={filteredEdges.length} />
          <Stat label="Sources" value={Object.keys(lineage.source_systems).length} />
        </div>

        {/* Search */}
        <div className="ml-auto flex items-center gap-2">
          <div className="relative">
            <Search size={14} className="absolute left-2 top-1/2 -translate-y-1/2 text-text-muted" />
            <input
              className="pl-7 pr-3 py-1 text-xs rounded bg-surface-base border border-border-subtle text-text-bright placeholder-text-muted focus:border-accent-green focus:outline-none w-48"
              placeholder="Search tables..."
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
            />
          </div>

          {/* Upload */}
          <label className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-surface-base border border-border-subtle text-text-muted hover:text-text-bright cursor-pointer transition">
            <Upload size={12} />
            <span>Re-upload</span>
            <input type="file" accept=".html" className="hidden" onChange={handleUpload} disabled={uploading} />
          </label>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Left controls */}
        <div className="w-44 flex-shrink-0 bg-surface-card border-r border-border-subtle p-3 space-y-4 overflow-y-auto">
          {/* View mode */}
          <div>
            <div className="text-[10px] font-semibold text-text-muted uppercase tracking-wider mb-2">Vue</div>
            <div className="flex flex-col gap-1">
              {(['omop', 'full'] as const).map(v => (
                <button
                  key={v}
                  onClick={() => setViewMode(v)}
                  className={`text-xs px-2 py-1 rounded transition ${viewMode === v
                    ? 'bg-accent-green text-white font-semibold'
                    : 'bg-surface-base text-text-muted hover:text-text-bright'}`}
                >
                  {v === 'omop' ? 'OMOP Lineage' : 'Full ETL'}
                </button>
              ))}
            </div>
          </div>

          {/* Layer toggles */}
          <div>
            <div className="text-[10px] font-semibold text-text-muted uppercase tracking-wider mb-2">Couches</div>
            {Object.entries(LAYER_COLORS).map(([layer, color]) => (
              <label key={layer} className="flex items-center gap-2 text-xs py-0.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={visibleLayers.has(layer)}
                  onChange={() => {
                    setVisibleLayers(prev => {
                      const next = new Set(prev);
                      next.has(layer) ? next.delete(layer) : next.add(layer);
                      return next;
                    });
                  }}
                  className="accent-[#2bc459]"
                />
                <span className="w-2.5 h-2.5 rounded-sm" style={{ background: color.border }} />
                <span className="text-text-dim">{color.label}</span>
              </label>
            ))}
          </div>

          {/* Legend */}
          <div>
            <div className="text-[10px] font-semibold text-text-muted uppercase tracking-wider mb-2">Sources</div>
            {Object.entries(lineage.source_systems).map(([key, sys]) => (
              <div key={key} className="text-[10px] text-text-muted py-0.5">
                <span className="font-medium text-text-dim">{sys.name}</span>
                <span className="ml-1 text-text-muted">({sys.type})</span>
              </div>
            ))}
          </div>

          {/* Zoom controls */}
          <div className="flex gap-1">
            <button onClick={() => setTransform(p => ({ ...p, scale: p.scale * 1.2 }))} className="p-1 rounded bg-surface-base hover:bg-surface-light text-text-muted"><ZoomIn size={14} /></button>
            <button onClick={() => setTransform(p => ({ ...p, scale: p.scale * 0.83 }))} className="p-1 rounded bg-surface-base hover:bg-surface-light text-text-muted"><ZoomOut size={14} /></button>
            <button onClick={fitView} className="p-1 rounded bg-surface-base hover:bg-surface-light text-text-muted"><Maximize2 size={14} /></button>
          </div>
        </div>

        {/* SVG Canvas */}
        <div className="flex-1 relative overflow-hidden bg-deep-base">
          <svg
            ref={svgRef}
            className="w-full h-full"
            onWheel={handleWheel}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
          >
            <defs>
              {Object.entries(LAYER_COLORS).map(([layer, color]) => (
                <marker key={layer} id={`arrow-${layer}`} viewBox="0 0 10 7" refX="10" refY="3.5" markerWidth="8" markerHeight="6" orient="auto">
                  <path d="M0,0 L10,3.5 L0,7 Z" fill={color.border} />
                </marker>
              ))}
            </defs>
            <g ref={gRef} transform={`translate(${transform.x},${transform.y}) scale(${transform.scale})`}>
              {/* Layer headers */}
              {Object.entries(layout.colX).map(([layer, x]) => (
                <text key={layer} x={x + 70} y={25} fill="#4b5563" fontSize={11} fontWeight={700} letterSpacing={1}>
                  {LAYER_HEADERS[layer] || layer.toUpperCase()}
                </text>
              ))}

              {/* Edges */}
              {edgePaths}

              {/* Nodes */}
              {Object.entries(layout.positions).map(([name, pos]) => {
                const node = filteredNodes[name];
                if (!node) return null;
                const color = LAYER_COLORS[node.layer] || LAYER_COLORS.source;
                const shortName = name.split('.').pop()?.substring(0, 28) || name;
                const schema = name.includes('.') ? name.split('.').slice(0, -1).join('.') : '';
                const isSelected = selectedNode === name;

                return (
                  <g
                    key={name}
                    className="lineage-node cursor-pointer"
                    transform={`translate(${pos.x}, ${pos.y})`}
                    onClick={() => setSelectedNode(name)}
                    onMouseEnter={() => setHoveredNode(name)}
                    onMouseLeave={() => setHoveredNode(null)}
                  >
                    <rect
                      width={pos.w} height={pos.h} rx={6} ry={6}
                      fill={color.bg} stroke={isSelected ? '#fff' : color.border}
                      strokeWidth={isSelected ? 2.5 : 1.5}
                      opacity={hoveredNode && hoveredNode !== name && !filteredEdges.some(e => (e.source === hoveredNode && e.target === name) || (e.target === hoveredNode && e.source === name)) ? 0.3 : 1}
                    />
                    <text x={8} y={18} fill="#e0e0e0" fontSize={11} fontWeight={600}>{shortName}</text>
                    {schema && <text x={8} y={31} fill="#9ca3af" fontSize={9}>{schema}</text>}
                  </g>
                );
              })}
            </g>
          </svg>
        </div>

        {/* Detail Panel */}
        <div className={`flex-shrink-0 bg-surface-card border-l border-border-subtle transition-all duration-200 overflow-y-auto ${selectedNode && detailData ? 'w-[420px]' : 'w-0'}`}>
          {selectedNode && detailData && (
            <div className="p-4 space-y-4">
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-sm font-semibold text-accent-green break-all">{selectedNode}</h2>
                  <div className="flex gap-1 mt-1">
                    <span className="text-[10px] px-1.5 py-0.5 rounded font-semibold" style={{ background: LAYER_COLORS[detailData.node.layer]?.bg, color: LAYER_COLORS[detailData.node.layer]?.text }}>
                      {detailData.node.layer.toUpperCase()}
                    </span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded font-semibold bg-[#1e3a5f] text-[#60a5fa]">
                      {detailData.node.system}
                    </span>
                  </div>
                </div>
                <button onClick={() => setSelectedNode(null)} className="text-text-muted hover:text-text-bright"><X size={16} /></button>
              </div>

              {/* Incoming edges */}
              {detailData.incoming.length > 0 && (
                <div>
                  <h3 className="text-xs font-semibold text-purple-400 mb-2">Alimentee par ({detailData.incoming.length})</h3>
                  {detailData.incoming.map((e, i) => (
                    <EdgeDetail key={i} edge={e} onNavigate={setSelectedNode} />
                  ))}
                </div>
              )}

              {/* Outgoing edges */}
              {detailData.outgoing.length > 0 && (
                <div>
                  <h3 className="text-xs font-semibold text-purple-400 mb-2">Alimente ({detailData.outgoing.length})</h3>
                  {detailData.outgoing.map((e, i) => (
                    <button
                      key={i}
                      onClick={() => setSelectedNode(e.target)}
                      className="w-full text-left mb-1 px-2 py-1.5 rounded bg-surface-base border border-border-subtle hover:border-accent-green/50 transition"
                    >
                      <span className="text-xs text-purple-300">{e.target}</span>
                      <span className="text-[10px] text-text-muted ml-2">{e.column_mappings.length} colonnes</span>
                    </button>
                  ))}
                </div>
              )}

              {/* Upstream chain */}
              {detailData.chain && (
                <div>
                  <h3 className="text-xs font-semibold text-purple-400 mb-2">Chaine complete (upstream)</h3>
                  <div className="bg-surface-base border border-border-subtle rounded-lg p-3 font-mono text-[11px]">
                    <ChainView chain={detailData.chain} onNavigate={setSelectedNode} />
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="text-center">
      <div className="text-sm font-bold text-text-bright">{value}</div>
      <div className="text-[9px] text-text-muted uppercase">{label}</div>
    </div>
  );
}

function EdgeDetail({ edge, onNavigate }: { edge: LineageEdge; onNavigate: (n: string) => void }) {
  const [showCols, setShowCols] = useState(false);
  const [showSql, setShowSql] = useState(false);
  const [showCode, setShowCode] = useState(false);

  const realCols = edge.column_mappings.filter(c => c.source && c.source !== '.');
  const defaultCols = edge.column_mappings.filter(c => !c.source || c.source === '.');

  return (
    <div className="mb-2 p-2.5 rounded-lg bg-surface-base border border-border-subtle">
      <button onClick={() => onNavigate(edge.source)} className="text-xs font-semibold text-blue-400 hover:underline">
        {edge.source}
      </button>
      {edge.description && <p className="text-[10px] text-text-muted mt-0.5">{edge.description}</p>}
      {edge.transformation_file && <p className="text-[9px] text-text-muted">Fichier: {edge.transformation_file}</p>}

      {/* Column mappings */}
      {realCols.length > 0 && (
        <details className="mt-1.5" open={showCols} onToggle={e => setShowCols((e.target as any).open)}>
          <summary className="text-[10px] text-text-muted cursor-pointer hover:text-text-dim">{realCols.length} colonnes mappees</summary>
          <table className="w-full text-[10px] mt-1">
            <thead><tr className="text-text-muted"><th className="text-left p-0.5">Source</th><th className="text-left p-0.5">Dest</th><th className="text-left p-0.5">Type</th></tr></thead>
            <tbody>
              {realCols.map((c, i) => (
                <tr key={i} className="border-t border-border-subtle/30">
                  <td className="p-0.5 text-blue-400">{c.source}</td>
                  <td className="p-0.5 text-purple-300">{c.destination}</td>
                  <td className="p-0.5 text-text-muted">{c.type || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      {defaultCols.length > 0 && (
        <details className="mt-1">
          <summary className="text-[10px] text-text-muted cursor-pointer">{defaultCols.length} colonne(s) par defaut</summary>
          <table className="w-full text-[10px] mt-1">
            <tbody>
              {defaultCols.map((c, i) => (
                <tr key={i} className="border-t border-border-subtle/30">
                  <td className="p-0.5 text-text-muted">-</td>
                  <td className="p-0.5 text-purple-300">{c.destination}</td>
                  <td className="p-0.5 text-text-muted">{c.default_value ? `= "${c.default_value}"` : c.comment || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      {/* SQL */}
      {edge.sql && (
        <details className="mt-1">
          <summary className="text-[10px] text-text-muted cursor-pointer">SQL source</summary>
          <pre className="mt-1 p-2 rounded bg-deep-base border border-border-subtle text-[10px] text-green-400 overflow-x-auto max-h-36 overflow-y-auto whitespace-pre-wrap">{edge.sql}</pre>
        </details>
      )}

      {/* Transformation code */}
      {edge.transformation_code && (
        <details className="mt-1">
          <summary className="text-[10px] text-text-muted cursor-pointer">Code transformation</summary>
          <pre className="mt-1 p-2 rounded bg-deep-base border border-border-subtle text-[10px] text-orange-400 overflow-x-auto max-h-36 overflow-y-auto whitespace-pre-wrap">{edge.transformation_code}</pre>
        </details>
      )}

      {/* WHERE filter */}
      {edge.where_filter && (
        <details className="mt-1">
          <summary className="text-[10px] text-text-muted cursor-pointer">Filtre WHERE</summary>
          <pre className="mt-1 p-2 rounded bg-deep-base border border-border-subtle text-[10px] text-green-400 overflow-x-auto whitespace-pre-wrap">{edge.where_filter}</pre>
        </details>
      )}
    </div>
  );
}

function ChainView({ chain, depth = 0, onNavigate }: { chain: ChainEntry[]; depth?: number; onNavigate: (n: string) => void }) {
  return (
    <>
      {chain.map((entry, i) => (
        <div key={i} style={{ paddingLeft: depth * 16 }}>
          <div className="flex items-center gap-1 py-0.5">
            <ArrowRight size={10} className="text-yellow-500" />
            <button onClick={() => onNavigate(entry.from)} className="text-blue-400 hover:underline">{entry.from}</button>
            <span className="text-text-muted">[{entry.columns_count} cols]</span>
            {entry.description && <span className="text-text-muted">({entry.description})</span>}
          </div>
          {entry.upstream && <ChainView chain={entry.upstream} depth={depth + 1} onNavigate={onNavigate} />}
        </div>
      ))}
    </>
  );
}
