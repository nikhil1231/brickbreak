import React, { useState } from 'react';
import { AppShell, Box } from '@mantine/core';
import { Header, TabType } from './components/common/Header';
import { ScreenerView } from './components/screener/ScreenerView';
import { ExploreConsole } from './components/alpha/ExploreConsole';
import { HypothesesLedger } from './components/alpha/HypothesesLedger';
import { ReplaysView } from './components/alpha/ReplaysView';
import { IdeaGraphView } from './components/alpha/IdeaGraphView';
import { SignalCompare } from './components/alpha/SignalCompare';
import { BudgetLedgerView } from './components/alpha/BudgetLedgerView';
import { CatalogueView } from './components/alpha/CatalogueView';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabType>('explore');
  const [statusText, setStatusText] = useState<string>('');
  const [metaText, setMetaText] = useState<string>('');

  return (
    <AppShell header={{ height: 56 }} bg="#0d1117">
      <AppShell.Header bg="transparent" style={{ border: 'none' }}>
        <Header
          activeTab={activeTab}
          onTabChange={setActiveTab}
          statusText={statusText}
          metaText={metaText}
        />
      </AppShell.Header>

      <AppShell.Main>
        <Box style={{ minHeight: 'calc(100vh - 56px)' }}>
          {activeTab === 'explore' && <ExploreConsole />}
          {activeTab === 'replays' && <ReplaysView />}
          {activeTab === 'hypotheses' && <HypothesesLedger />}
          {activeTab === 'graph' && <IdeaGraphView />}
          {activeTab === 'compare' && <SignalCompare />}
          {activeTab === 'ledger' && <BudgetLedgerView />}
          {activeTab === 'catalogue' && <CatalogueView />}
          {activeTab === 'screener' && (
            <ScreenerView
              onStatusChange={setStatusText}
              onMetaLoaded={setMetaText}
            />
          )}
        </Box>
      </AppShell.Main>
    </AppShell>
  );
};

export default App;
