import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchConnections, fetchMemories } from '../api/nexus';
import type { ConnNode, ConnNodeType, ConnEdge } from '../types/nexus';

const TYPE_COLOR: Record<ConnNodeType, string> = {
  memory: '#66fcf1',
  entity: '#b967ff',
  opinion: '#ff3cac',
  mind: '#ffd166',
  agent: '#63ff9f',
};

const TYPE_GLYPH: Record<ConnNodeType, string> = {
  memory: '◆',
  entity: '⬡',
  opinion: '✦',
  mind: '◎',
  agent: '◈',
};

const EDGE_KIND: Record<string, { color: string; width: number; pattern?: string }> = {
  saved: { color: 'rgba(99,255,159,.5)', width: 1 },
  mentions: { color: 'rgba(102,252,241,.35)', width: 1, pattern: '2 4' },
  relation: { color: 'rgba(185,103,255,.55)', width: 1.4 },
  evidence: { color: 'rgba(255,60,172,.65)', width: 1.8 },
  holds: { color: 'rgba(255,209,102,.65)', width: 1.5 },
  knows: { color: 'rgba(255,209,102,.35)', width: 1, pattern: '4 3' },
};

interface P { x: number; y: number; vx: number; vy: number; pulse: number }

function forceLayout(nodes: ConnNode[], edges: ConnEdge[], w: number, h: number): P[] {
  const n = nodes.length;
  if (!n) return [];
  const pos: P[] = nodes.map((_, i) => {
    const a = (i / n) * Math.PI * 2;
    const r = Math.min(w, h) * 0.38;
    return { x: w / 2 + Math.cos(a) * r, y: h / 2 + Math.sin(a) * r, vx: 0, vy: 0, pulse: Math.random() * Math.PI * 2 };
  });
  const idx = new Map(nodes.map((nd, i) => [nd.id, i]));
  const links = edges
    .map((e) => [idx.get(e.from), idx.get(e.to)] as [number | undefined, number | undefined])
    .filter((l): l is [number, number] => l[0] != null && l[1] != null);

  const REST = 110;
  for (let iter = 0; iter < 380; iter++) {
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let dx = pos[i].x - pos[j].x;
        let dy = pos[i].y - pos[j].y;
        const d2 = dx * dx + dy * dy + 0.01;
        const d = Math.sqrt(d2);
        const f = 2200 / d2;
        dx /= d; dy /= d;
        pos[i].vx += f * dx; pos[i].vy += f * dy;
        pos[j].vx -= f * dx; pos[j].vy -= f * dy;
      }
    }
    for (const [a, b] of links) {
      let dx = pos[b].x - pos[a].x;
      let dy = pos[b].y - pos[a].y;
      const d = Math.sqrt(dx * dx + dy * dy) + 0.01;
      const f = 0.022 * (d - REST);
      dx /= d; dy /= d;
      pos[a].vx += f * dx; pos[a].vy += f * dy;
      pos[b].vx -= f * dx; pos[b].vy -= f * dy;
    }
    for (let i = 0; i < n; i++) {
      pos[i].vx += (w / 2 - pos[i].x) * 0.0015;
      pos[i].vy += (h / 2 - pos[i].y) * 0.0015;
      pos[i].x += Math.max(-26, Math.min(26, pos[i].vx));
      pos[i].y += Math.max(-26, Math.min(26, pos[i].vy));
      pos[i].vx *= 0.84; pos[i].vy *= 0.84;
    }
  }
  return pos;
}

const W = 1600;
const H = 1100;

export default function Constellation() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['constellation'],
    queryFn: () => fetchConnections({ limit: 200 }),
    refetchInterval: 20000,
  });
  const { data: mems } = useQuery({
    queryKey: ['constellation-mems'],
    queryFn: () => fetchMemories({ limit: 100 }),
    refetchInterval: 30000,
  });

  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [view, setView] = useState({ x: 0, y: 0, scale: 1 });
  const [animTick, setAnimTick] = useState(0);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);
  const [time, setTime] = useState(0);

  // Animation loop for node pulsing
  useEffect(() => {
    let raf = 0;
    const tick = (t: number) => {
      setTime(t / 1000);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  const positions = useMemo(() => (data ? forceLayout(data.nodes, data.edges, W, H) : []), [data, animTick]);
  const posById = useMemo(() => {
    const m = new Map<string, P>();
    if (data) data.nodes.forEach((nd, i) => m.set(nd.id, positions[i]));
    return m;
  }, [data, positions]);
  const nodeById = useMemo(() => new Map((data?.nodes ?? []).map((n) => [n.id, n])), [data]);
  const memsById = useMemo(() => new Map((mems?.memories ?? []).map((m) => [m.id, m])), [mems]);

  const selectedNode = selected ? nodeById.get(selected) : null;
  const selectedMem = selectedNode?.type === 'memory' ? memsById.get(selectedNode.id) : null;
  const neighbors = useMemo(() => {
    if (!selected || !data) return [];
    const out: { node: ConnNode; kind: string; dir: 'out' | 'in'; label?: string }[] = [];
    for (const e of data.edges) {
      if (e.from === selected) {
        const nb = nodeById.get(e.to);
        if (nb) out.push({ node: nb, kind: e.kind, dir: 'out', label: e.label });
      } else if (e.to === selected) {
        const nb = nodeById.get(e.from);
        if (nb) out.push({ node: nb, kind: e.kind, dir: 'in', label: e.label });
      }
    }
    return out;
  }, [selected, data, nodeById]);

  const connectedIds = useMemo(() => {
    const s = new Set<string>();
    if (selected && data) {
      s.add(selected);
      for (const e of data.edges) {
        if (e.from === selected) s.add(e.to);
        if (e.to === selected) s.add(e.from);
      }
    }
    return s;
  }, [selected, data]);

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.12 : 0.89;
    setView((v) => ({ ...v, scale: Math.max(0.18, Math.min(4, v.scale * factor)) }));
  };
  const onDown = (e: React.MouseEvent) => {
    drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
  };
  const onMove = (e: React.MouseEvent) => {
    if (!drag.current) return;
    setView((v) => ({
      ...v,
      x: drag.current!.vx + (e.clientX - drag.current!.x),
      y: drag.current!.vy + (e.clientY - drag.current!.y),
    }));
  };
  const onUp = () => { drag.current = null; };

  const recompute = () => setAnimTick((t) => t + 1);

  // Count edge types
  const edgeCounts = useMemo(() => {
    const m: Record<string, number> = {};
    for (const e of data?.edges ?? []) m[e.kind] = (m[e.kind] ?? 0) + 1;
    return m;
  }, [data]);

  // Cluster by node type for filter
  const [filter, setFilter] = useState<Set<ConnNodeType>>(new Set(['memory', 'entity', 'opinion', 'mind', 'agent']));
  const visibleNodes = useMemo(() => (data?.nodes ?? []).filter((n) => filter.has(n.type)), [data, filter]);
  const visibleNodeIds = useMemo(() => new Set(visibleNodes.map((n) => n.id)), [visibleNodes]);
  const visibleEdges = useMemo(() => (data?.edges ?? []).filter((e) => visibleNodeIds.has(e.from) && visibleNodeIds.has(e.to)), [data, visibleNodeIds]);

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* Title bar */}
      <div className="flex items-end gap-3">
        <div>
          <div className="text-[.62rem] text-[var(--color-cyan)] uppercase tracking-[.34em]">Synaptic Map</div>
          <h2 className="text-3xl m-0 mt-1 nx-glow" style={{ color: 'var(--color-violet)' }}>
            NEURAL CONSTELLATION
          </h2>
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          {(['memory', 'entity', 'opinion', 'mind', 'agent'] as ConnNodeType[]).map((t) => (
            <button
              key={t}
              onClick={() => {
                const next = new Set(filter);
                next.has(t) ? next.delete(t) : next.add(t);
                setFilter(next);
              }}
              className={`px-2 py-1 text-[.62rem] uppercase tracking-[.14em] border transition-all ${filter.has(t) ? 'border-[var(--color-line)] bg-[rgba(102,252,241,.08)] text-[var(--color-text)]' : 'border-[rgba(102,252,241,.15)] text-[var(--color-dim)]'}`}
            >
              <span className="inline-block w-2 h-2 rounded-full mr-1" style={{ background: TYPE_COLOR[t], boxShadow: `0 0 6px ${TYPE_COLOR[t]}` }} />
              {t}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-[1fr_340px] gap-3 flex-1 min-h-0">
        {/* Graph canvas */}
        <div className="nx-card overflow-hidden relative">
          {/* Top overlay info */}
          <div className="absolute top-2 left-3 z-10 flex items-center gap-3 text-[.6rem] text-[var(--color-dim)] uppercase tracking-[.16em]">
            <span>{visibleNodes.length}/{data?.node_count ?? 0} nodes</span>
            <span>·</span>
            <span>{visibleEdges.length} edges</span>
            <span>·</span>
            <span>scale {view.scale.toFixed(2)}x</span>
            <span>·</span>
            <span className="text-[var(--color-cyan)]">drag to pan · scroll to zoom</span>
            <button onClick={recompute} className="ml-2 px-1.5 py-0.5 border border-[var(--color-line)] hover:border-[var(--color-cyan)] text-[var(--color-cyan)]">↻</button>
          </div>

          {/* Bottom legend */}
          <div className="absolute bottom-2 left-3 z-10 flex items-center gap-3 text-[.55rem] uppercase tracking-[.14em] text-[var(--color-dim)]">
            {Object.entries(edgeCounts).map(([k, n]) => (
              <span key={k} className="flex items-center gap-1">
                <span className="w-3 h-0.5" style={{ background: EDGE_KIND[k]?.color ?? '#fff' }} />
                <span>{k} {n}</span>
              </span>
            ))}
          </div>

          {isLoading && <div className="absolute inset-0 flex items-center justify-center text-[var(--color-dim)] text-sm">Mapping synaptic graph…</div>}
          {error && <div className="absolute inset-0 flex items-center justify-center text-[var(--color-red)] text-sm">Failed: {String(error)}</div>}

          {data && (
            <svg
              width="100%" height="100%" viewBox={`0 0 ${W} ${H}`}
              onWheel={onWheel} onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp}
              style={{ cursor: drag.current ? 'grabbing' : 'grab' }}>
              {/* Background grid */}
              <defs>
                <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
                  <path d="M 40 0 L 0 0 0 40" fill="none" stroke="rgba(102,252,241,0.04)" strokeWidth={0.5} />
                </pattern>
                <radialGradient id="nodeGlow">
                  <stop offset="0%" stopColor="currentColor" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="currentColor" stopOpacity={0} />
                </radialGradient>
                <marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="5" markerHeight="5" orient="auto">
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
                </marker>
              </defs>
              <rect width={W} height={H} fill="url(#grid)" />

              <g transform={`translate(${view.x},${view.y}) scale(${view.scale})`}>
                {/* Edges */}
                {visibleEdges.map((e, i) => {
                  const a = posById.get(e.from);
                  const b = posById.get(e.to);
                  if (!a || !b) return null;
                  const dim = (selected && !(connectedIds.has(e.from) && connectedIds.has(e.to))) ||
                              (hovered && !(hovered === e.from || hovered === e.to));
                  const isHighlighted = selected && connectedIds.has(e.from) && connectedIds.has(e.to);
                  const eStyle = EDGE_KIND[e.kind] || { color: 'rgba(255,255,255,.18)', width: 1 };
                  return (
                    <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                      stroke={eStyle.color}
                      strokeWidth={(isHighlighted ? 1.6 : 0.7) * (eStyle.width || 1)}
                      strokeDasharray={eStyle.pattern}
                      opacity={dim ? 0.06 : (isHighlighted ? 0.9 : 0.5)}
                      className={isHighlighted ? 'nx-flow' : ''}
                    />
                  );
                })}

                {/* Nodes */}
                {visibleNodes.map((nd) => {
                  const p = posById.get(nd.id);
                  if (!p) return null;
                  const r = nd.type === 'mind' ? 16 : nd.type === 'agent' ? 11 : nd.type === 'opinion' ? 10 : 5 + Math.min(7, (Number(nd.meta.importance) || 0) * 7);
                  const dim = (selected && !connectedIds.has(nd.id)) || (hovered && hovered !== nd.id);
                  const isSel = selected === nd.id;
                  const isHov = hovered === nd.id;
                  const importance = Number(nd.meta.importance) || 0.3;
                  const pulse = 1 + Math.sin(time * 2 + p.pulse) * 0.1 * importance;
                  const r2 = r * pulse;

                  return (
                    <g key={nd.id} transform={`translate(${p.x},${p.y})`}
                      style={{ cursor: 'pointer', color: TYPE_COLOR[nd.type] }}
                      opacity={dim ? 0.18 : 1}
                      onClick={(ev) => { ev.stopPropagation(); setSelected(isSel ? null : nd.id); }}
                      onMouseEnter={() => setHovered(nd.id)}
                      onMouseLeave={() => setHovered(null)}>
                      {/* Glow halo */}
                      <circle r={r2 * 2.4} fill="url(#nodeGlow)" opacity={isSel || isHov ? 0.8 : 0.3} />
                      {/* Outer ring (rotates via CSS) */}
                      {(isSel || isHov || nd.type === 'mind' || nd.type === 'agent') && (
                        <g style={{ animation: 'spin 22s linear infinite', transformOrigin: 'center' }}>
                          <circle r={r2 + 8} fill="none" stroke="currentColor" strokeWidth={0.4} strokeDasharray="2 4" opacity={0.6} />
                        </g>
                      )}
                      {/* Core */}
                      <circle r={r2} fill={TYPE_COLOR[nd.type]} stroke={isSel ? '#fff' : 'rgba(0,0,0,.5)'} strokeWidth={isSel ? 2.5 : 0.6} />
                      {/* Glyph for special types */}
                      {(nd.type === 'mind' || nd.type === 'agent' || nd.type === 'opinion') && (
                        <text x={0} y={3} textAnchor="middle" fontSize={r} fill="#000" fontWeight="bold">
                          {TYPE_GLYPH[nd.type]}
                        </text>
                      )}
                      {/* Label */}
                      {(isSel || isHov || nd.type === 'mind' || nd.type === 'agent' || nd.type === 'opinion') && (
                        <g transform={`translate(${r2 + 6}, -2)`}>
                          <rect x={-2} y={-9} width={Math.min(nd.label.length * 5.6 + 8, 220)} height={14} fill="rgba(2,4,12,.85)" stroke="currentColor" strokeWidth={0.4} rx={2} />
                          <text x={2} y={2} fontSize={9} fill="currentColor" style={{ pointerEvents: 'none' }}>
                            {nd.label.length > 36 ? nd.label.slice(0, 36) + '…' : nd.label}
                          </text>
                        </g>
                      )}
                    </g>
                  );
                })}
              </g>
            </svg>
          )}
        </div>

        {/* Inspector */}
        <div className="nx-card flex flex-col overflow-hidden">
          {!selectedNode && (
            <div className="flex-1 flex flex-col items-center justify-center text-center text-[var(--color-dim)] text-sm p-6">
              <div className="text-3xl mb-3" style={{ color: 'var(--color-cyan)' }}>✦</div>
              <div className="text-[var(--color-text)] text-base mb-1">Inspect a node</div>
              <div className="text-[.8rem]">Click any node to see what it is, who created it, and what it connects to.</div>
            </div>
          )}
          {selectedNode && (
            <div className="flex-1 overflow-auto space-y-3 text-sm">
              <div className="flex items-center gap-2 pb-2 border-b border-[var(--color-line)]">
                <span className="text-2xl" style={{ color: TYPE_COLOR[selectedNode.type] }}>{TYPE_GLYPH[selectedNode.type]}</span>
                <span className="uppercase text-xs tracking-[.2em] font-bold" style={{ color: TYPE_COLOR[selectedNode.type] }}>
                  {selectedNode.type}
                </span>
                <button onClick={() => setSelected(null)} className="ml-auto text-[var(--color-dim)] hover:text-[var(--color-text)]">×</button>
              </div>

              <div className="text-[var(--color-text)] break-words text-[.85rem] leading-relaxed">{selectedNode.label}</div>

              {selectedMem && (
                <div className="border border-[var(--color-line)] bg-[rgba(102,252,241,.04)] p-2 space-y-1.5 text-[.7rem]">
                  <div className="text-[.55rem] text-[var(--color-cyan)] uppercase tracking-[.18em]">Memory Details</div>
                  <div className="flex justify-between"><span className="text-[var(--color-muted)]">type</span><span className="text-[var(--color-cyan)]">{selectedMem.memory_type}</span></div>
                  <div className="flex justify-between"><span className="text-[var(--color-muted)]">agent</span><span>{selectedMem.agent_name ?? '—'}</span></div>
                  <div className="flex justify-between"><span className="text-[var(--color-muted)]">importance</span><span className="tabular-nums">{(selectedMem.importance * 100).toFixed(0)}%</span></div>
                  <div className="flex justify-between"><span className="text-[var(--color-muted)]">confidence</span><span className="tabular-nums">{(selectedMem as any).confidence?.toFixed(2) ?? '—'}</span></div>
                  <div className="flex justify-between"><span className="text-[var(--color-muted)]">accessed</span><span className="tabular-nums">{(selectedMem as any).access_count ?? 0}x</span></div>
                  <div className="flex justify-between"><span className="text-[var(--color-muted)]">confirmed</span><span className="text-[var(--color-green)] tabular-nums">{selectedMem.confirmed_count ?? 0}</span></div>
                  <div className="flex justify-between"><span className="text-[var(--color-muted)]">created</span><span className="text-[var(--color-text)]">{selectedMem.created_at ? new Date(selectedMem.created_at).toLocaleString() : '—'}</span></div>
                </div>
              )}

              <div className="border-t border-[var(--color-line)] pt-2">
                <div className="text-[var(--color-muted)] text-[.6rem] uppercase tracking-[.18em] mb-1.5">Metadata</div>
                <div className="space-y-1 text-[.7rem]">
                  {Object.entries(selectedNode.meta).map(([k, v]) => (
                    <div key={k} className="flex gap-2 border-b border-[rgba(102,252,241,.05)] pb-1">
                      <span className="text-[var(--color-dim)] min-w-[88px]">{k}</span>
                      <span className="break-words flex-1">{typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(3)) : String(v ?? '—')}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="border-t border-[var(--color-line)] pt-2">
                <div className="text-[var(--color-cyan)] text-[.6rem] uppercase tracking-[.2em] mb-1.5 flex items-center gap-2">
                  <span>Synaptic Connections</span>
                  <span className="text-[var(--color-text)]">{neighbors.length}</span>
                </div>
                <div className="space-y-1 max-h-64 overflow-auto">
                  {neighbors.map((nb, i) => (
                    <button key={i} type="button"
                      className="w-full text-left text-[.7rem] flex items-center gap-2 hover:bg-[rgba(102,252,241,.06)] px-1.5 py-1 border border-transparent hover:border-[var(--color-line)] transition-colors"
                      onClick={() => setSelected(nb.node.id)}>
                      <span className="text-[var(--color-dim)] w-8">{nb.dir === 'out' ? '→' : '←'}</span>
                      <span className="text-[var(--color-magenta)] text-[.55rem] uppercase w-14">{nb.kind}</span>
                      <span className="text-base" style={{ color: TYPE_COLOR[nb.node.type] }}>{TYPE_GLYPH[nb.node.type]}</span>
                      <span className="text-[var(--color-muted)] truncate flex-1">{nb.node.label}{nb.label ? ` · ${nb.label}` : ''}</span>
                    </button>
                  ))}
                  {neighbors.length === 0 && <div className="text-[var(--color-dim)] text-[.7rem]">No connections.</div>}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
