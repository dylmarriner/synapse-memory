import { lazy, Suspense, useMemo, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Layout from './components/Layout';

const HUD = lazy(() => import('./pages/HUD'));
const Constellation = lazy(() => import('./pages/Constellation'));
const Timeline = lazy(() => import('./pages/Timeline'));
const Observatory = lazy(() => import('./pages/Observatory'));
const Lattice = lazy(() => import('./pages/Lattice'));
const Pulse = lazy(() => import('./pages/Pulse'));
const Conversations = lazy(() => import('./pages/Conversations'));
const RecallLab = lazy(() => import('./pages/RecallLab'));
const Agents = lazy(() => import('./pages/Agents'));
const Sessions = lazy(() => import('./pages/Sessions'));
const Operations = lazy(() => import('./pages/Operations'));
const Console = lazy(() => import('./pages/Console'));

const PAGES = {
  hud: HUD,
  constellation: Constellation,
  timeline: Timeline,
  observatory: Observatory,
  lattice: Lattice,
  pulse: Pulse,
  conversations: Conversations,
  recalllab: RecallLab,
  agents: Agents,
  sessions: Sessions,
  ops: Operations,
  console: Console,
} satisfies Record<string, React.LazyExoticComponent<React.FC>>;

type PageId = keyof typeof PAGES;

const FALLBACK_PAGE = HUD;

function isPageId(value: string): value is PageId {
  return value in PAGES;
}

function PageLoading() {
  return (
    <div className="flex flex-1 items-center justify-center nx-mono text-[.7rem] uppercase tracking-[.32em]" style={{ color: 'var(--color-cyan)' }}>
      <div className="flex flex-col items-center gap-2">
        <div className="text-2xl" style={{ animation: 'pulse 1.4s infinite' }}>◈</div>
        <div>NEXUS:// loading module…</div>
      </div>
    </div>
  );
}

export default function App() {
  const [activeTab, setActiveTab] = useState<PageId>('hud');
  const queryClient = useMemo(
    () => new QueryClient({ defaultOptions: { queries: { retry: 2, staleTime: 5000 } } }),
    [],
  );
  const Page = isPageId(activeTab) ? PAGES[activeTab] : FALLBACK_PAGE;

  return (
    <QueryClientProvider client={queryClient}>
      <Layout activeTab={activeTab} onTabChange={(t) => setActiveTab(t as PageId)}>
        <Suspense fallback={<PageLoading />}>
          <Page />
        </Suspense>
      </Layout>
    </QueryClientProvider>
  );
}
