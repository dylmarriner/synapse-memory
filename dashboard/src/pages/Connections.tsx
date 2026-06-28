import { useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchConnections } from '../api/nexus';
import type { ConnNode, ConnNodeType } from '../types/nexus';

const TYPE_COLOR: Record<ConnNodeType, string> = {
  memory: '#66fcf1',
  entity: '#b967ff',
  opinion: '#ff3cac',
  mind: '#ffd166',
  agent: '#63ff9f',
};

const EDGE_COLOR: Record<string, string> = {
  saved: 'rgba(99,255,159,.35)',
  mentions: 'rgba(102,252,241,.28)',
  relation: 'rgba(185,103,255,.35)',
  evidence: 'rgba(255,60,172,.45)',
  holds: 'rgba(255,209,102,.5)',
  knows: 'rgba(255,209,102,.3)',
};

interface P { x: number; y: number; vx: number; vy: number }

function layout(nodes: ConnNode[], edges: { from: string; to: string }[], w: number, h: number): P[] {
  const n = nodes.length;
  if (!n) return [];
  const pos: P[] = nodes.map((_, i) => {
    const a = (i / n) * Math.PI * 2;
    const r = Math.min(w, h) * 0.36;
    return { x: w / 2 + Math.cos(a) * r, y: h / 2 + Math.sin(a) * r, vx: 0, vy: 0 };
  });
  const idx = new Map(nodes.map((nd, i) => [nd.id, i]));
  const links = edges
    .map((e) => [idx.get(e.from), idx.get(e.to)] as [number | undefined, number | undefined])
    .filter((l): l is [number, number] => l[0] != null && l[1] != null);
  const REST = 95;
  for (let iter = 0; iter < 320; iter++) {
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let dx = pos[i].x - pos[j].x;
        let dy = pos[i].y - pos[j].y;
        const d2 = dx * dx + dy * dy + 0.01;
        const d = Math.sqrt(d2);
        const f = 1400 / d2;
        dx /= d; dy /= d;
        pos[i].vx += f * dx; pos[i].vy += f * dy;
        pos[j].vx -= f * dx; pos[j].vy -= f * dy;
      }
    }
    for (const [a, b] of links) {
      let dx = pos[b].x - pos[a].x;
      let dy = pos[b].y - pos[a].y;
      const d = Math.sqrt(dx * dx + dy * dy) + 0.01;
      const f = 0.018 * (d - REST);
      dx /= d; dy /= d;
      pos[a].vx += f * dx; pos[a].vy += f * dy;
      pos[b].vx -= f * dx; pos[b].vy -= f * dy;
    }
    for (let i = 0; i < n; i++) {
      pos[i].vx += (w / 2 - pos[i].x) * 0.0012;
      pos[i].vy += (h / 2 - pos[i].y) * 0.0012;
      pos[i].x += Math.max(-22, Math.min(22, pos[i].vx));
      pos[i].y += Math.max(-22, Math.min(22, pos[i].vy));
      pos[i].vx *= 0.86; pos[i].vy *= 0.86;
    }
  }
  return pos;
}

function nodeRadius(node: ConnNode): number {
  if (node.type === 'mind') return 14;
  if (node.type === 'agent') return 10;
  if (node.type === 'opinion') return 9;
  if (node.type === 'memory') return 5 + Math.min(5, (Number(node.meta.importance) || 0) * 5);
  return 7;
}

const W = 1600;
const H = 1100;

export default function Connections() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['connections'],
    queryFn: () => fetchConnections({ limit: 120 }),
    refetchInterval: 30000,
  });

  const [selected, setSelected] = useState<string | null>(null);
  const [view, setView] = useState({ x: 0, y: 0, scale: 1 });
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);

  const positions = useMemo(() => {
    if (!data) return [];
    return layout(data.nodes, data.edges, W, H);
  }, [data]);

  const posById = useMemo(() => {
    const m = new Map<string, P>();
    if (data) data.nodes.forEach((nd, i) => m.set(nd.id, positions[i]));
    return m;
  }, [data, positions]);

  const nodeById = useMemo(() => new Map((data?.nodes ?? []).map((n) => [n.id, n])), [data]);

  const selectedNode = selected ? nodeById.get(selected) : null;
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
    setView((v) => ({ ...v, scale: Math.max(0.25, Math.min(4, v.scale * factor)) }));
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

  return (
    <>
      <div className="flex items-center gap-4 mb-3">
        <div>
          <div className="text-[.72rem] text-[var(--color-cyan)] uppercase tracking-[.22em]">Connections</div>
          <h2 className="text-3xl m-0 mt-1">How Everything Connects</h2>
        </div>
        <div className="ml-auto flex gap-3 text-[.62rem] uppercase tracking-[.12em] items-center flex-wrap">
          {(Object.keys(TYPE_COLOR) as ConnNodeType[]).map((t) => (
            <span key={t} className="flex items-center gap-1">
              <span className="inline-block w-[10px] h-[10px] rounded-full" style={{ background: TYPE_COLOR[t] }} />
              <span className="text-[var(--color-muted)]">{t}{data?.counts?.[t] ? ` ${data.counts[t]}` : ''}</span>
            </span>
          ))}
        </div>
      </div>

      {isLoading && <div className="text-[var(--color-dim)] text-sm">Mapping connections…</div>}
      {error && <div className="text-[var(--color-red)] text-sm">Failed to load graph: {String(error)}</div>}

      {data && (
        <div className="grid grid-cols-[1fr_300px] gap-3 flex-1 min-h-0">
          {/* Graph canvas */}
          <div className="border border-[rgba(102,252,241,.2)] bg-[var(--color-panel2)] overflow-hidden relative">
            <div className="absolute top-2 left-3 z-10 text-[.6rem] text-[var(--color-dim)] uppercase tracking-[.14em]">
              {data.node_count} nodes · {data.edge_count} edges · scroll to zoom · drag to pan
            </div>
            <svg
              width="100%" height="100%" viewBox={`0 0 ${W} ${H}`}
              onWheel={onWheel} onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp}
              style={{ cursor: drag.current ? 'grabbing' : 'grab' }}>
              <g transform={`translate(${view.x},${view.y}) scale(${view.scale})`}>
                {data.edges.map((e, i) => {
                  const a = posById.get(e.from);
                  const b = posById.get(e.to);
                  if (!a || !b) return null;
                  const dim = selected && !(connectedIds.has(e.from) && connectedIds.has(e.to));
                  return (
                    <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                      stroke={EDGE_COLOR[e.kind] || 'rgba(255,255,255,.15)'}
                      strokeWidth={e.kind === 'evidence' ? 1.6 : 1}
                      opacity={dim ? 0.06 : 1} />
                  );
                })}
                {data.nodes.map((nd) => {
                  const p = posById.get(nd.id);
                  if (!p) return null;
                  const r = nodeRadius(nd);
                  const dim = selected && !connectedIds.has(nd.id);
                  const isSel = selected === nd.id;
                  return (
                    <g key={nd.id} transform={`translate(${p.x},${p.y})`}
                      style={{ cursor: 'pointer' }}
                      opacity={dim ? 0.2 : 1}
                      onClick={(ev) => { ev.stopPropagation(); setSelected(isSel ? null : nd.id); }}>
                      <circle r={r} fill={TYPE_COLOR[nd.type]}
                        stroke={isSel ? '#fff' : 'rgba(0,0,0,.4)'} strokeWidth={isSel ? 2 : 0.5} />
                      {(nd.type === 'mind' || nd.type === 'agent' || nd.type === 'opinion' || isSel) && (
                        <text x={r + 3} y={3} fontSize={9} fill="var(--color-text)"
                          style={{ pointerEvents: 'none' }}>{nd.label.slice(0, 28)}</text>
                      )}
                    </g>
                  );
                })}
              </g>
            </svg>
          </div>

          {/* Inspector */}
          <div className="border border-[rgba(102,252,241,.2)] bg-[var(--color-panel)] p-3 overflow-auto">
            {!selectedNode && (
              <div className="text-[var(--color-dim)] text-sm">
                Click any node to inspect what it is and what it connects to.
              </div>
            )}
            {selectedNode && (
              <div className="space-y-3 text-sm">
                <div className="flex items-center gap-2">
                  <span className="inline-block w-[12px] h-[12px] rounded-full" style={{ background: TYPE_COLOR[selectedNode.type] }} />
                  <span className="uppercase text-xs tracking-[.16em]" style={{ color: TYPE_COLOR[selectedNode.type] }}>
                    {selectedNode.type}
                  </span>
                </div>
                <div className="text-[var(--color-text)] break-words">{selectedNode.label}</div>
                <div className="text-xs text-[var(--color-muted)] space-y-1 border-t border-[rgba(102,252,241,.1)] pt-2">
                  {Object.entries(selectedNode.meta).map(([k, v]) => (
                    <div key={k} className="flex gap-2">
                      <span className="text-[var(--color-dim)] min-w-[88px]">{k}</span>
                      <span className="break-words">{typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(2)) : String(v ?? '—')}</span>
                    </div>
                  ))}
                </div>
                <div className="border-t border-[rgba(102,252,241,.1)] pt-2">
                  <div className="text-[var(--color-cyan)] uppercase text-xs tracking-[.16em] mb-1">
                    Connections ({neighbors.length})
                  </div>
                  <div className="space-y-1">
                    {neighbors.map((nb, i) => (
                      <button key={i} type="button"
                        className="w-full text-left text-xs flex items-center gap-2 hover:bg-[rgba(102,252,241,.06)] p-1"
                        onClick={() => setSelected(nb.node.id)}>
                        <span className="text-[var(--color-dim)] w-[64px]">{nb.dir === 'out' ? '→' : '←'} {nb.kind}</span>
                        <span className="inline-block w-[8px] h-[8px] rounded-full shrink-0" style={{ background: TYPE_COLOR[nb.node.type] }} />
                        <span className="text-[var(--color-muted)] truncate">{nb.node.label}{nb.label ? ` · ${nb.label}` : ''}</span>
                      </button>
                    ))}
                    {neighbors.length === 0 && <div className="text-[var(--color-dim)] text-xs">No connections.</div>}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
