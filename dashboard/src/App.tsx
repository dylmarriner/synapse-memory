import { lazy, Suspense, useMemo, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Layout from './components/Layout';

const Overview = lazy(() => import('./pages/Overview'));
const Vault = lazy(() => import('./pages/Vault'));
const Agents = lazy(() => import('./pages/Agents'));
const Sessions = lazy(() => import('./pages/Sessions'));
const RecallLab = lazy(() => import('./pages/RecallLab'));
const Operations = lazy(() => import('./pages/Operations'));
const Console = lazy(() => import('./pages/Console'));

const PAGES = {
  overview: Overview,
  vault: Vault,
  agents: Agents,
  sessions: Sessions,
  recalllab: RecallLab,
  ops: Operations,
  console: Console,
} satisfies Record<string, React.LazyExoticComponent<React.FC>>;

type PageId = keyof typeof PAGES;

const FALLBACK_PAGE = Overview;

function isPageId(value: string): value is PageId {
  return value in PAGES;
}

function PageLoading() {
  return (
    <div className="flex flex-1 items-center justify-center text-sm uppercase tracking-[.18em] text-[var(--color-dim)]">
      NEXUS:// loading module…
    </div>
  );
}

export default function App() {
  const [activeTab, setActiveTab] = useState('overview');
  const queryClient = useMemo(
    () => new QueryClient({ defaultOptions: { queries: { retry: 2, staleTime: 5000 } } }),
    [],
  );
  const Page = isPageId(activeTab) ? PAGES[activeTab] : FALLBACK_PAGE;

  return (
    <QueryClientProvider client={queryClient}>
      <Layout activeTab={activeTab} onTabChange={setActiveTab}>
        <Suspense fallback={<PageLoading />}>
          <Page />
        </Suspense>
      </Layout>
    </QueryClientProvider>
  );
}
