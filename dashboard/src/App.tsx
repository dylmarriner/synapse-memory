import { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Layout from './components/Layout';
import Overview from './pages/Overview';
import Vault from './pages/Vault';
import Agents from './pages/Agents';
import Sessions from './pages/Sessions';
import RecallLab from './pages/RecallLab';
import Operations from './pages/Operations';
import Console from './pages/Console';

const qc = new QueryClient({
  defaultOptions: { queries: { retry: 2, staleTime: 5000 } },
});

const PAGES: Record<string, React.FC> = {
  overview: Overview,
  vault: Vault,
  agents: Agents,
  sessions: Sessions,
  recalllab: RecallLab,
  ops: Operations,
  console: Console,
};

export default function App() {
  const [activeTab, setActiveTab] = useState('overview');
  const Page = PAGES[activeTab] || Overview;

  return (
    <QueryClientProvider client={qc}>
      <Layout activeTab={activeTab} onTabChange={setActiveTab}>
        <Page />
      </Layout>
    </QueryClientProvider>
  );
}
