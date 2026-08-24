import React, { useEffect, useState } from 'react';
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
import { SettingsView } from './components/settings/SettingsView';
import { SetupReviewView } from './components/setups/SetupReviewView';

const TABS: TabType[] = ['explore', 'setups', 'replays', 'hypotheses', 'graph', 'compare', 'ledger', 'catalogue', 'screener', 'settings'];

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabType>(() => {
    const requested = new URLSearchParams(window.location.search).get('tab');
    return TABS.includes(requested as TabType) ? requested as TabType : 'explore';
  });
  const [statusText, setStatusText] = useState<string>('');
  const [metaText, setMetaText] = useState<string>('');

  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set('tab', activeTab);
    window.history.replaceState(null, '', url);
  }, [activeTab]);

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
          {activeTab === 'setups' && <SetupReviewView />}
          {activeTab === 'replays' && <ReplaysView />}
          {activeTab === 'hypotheses' && <HypothesesLedger />}
          {activeTab === 'graph' && <IdeaGraphView />}
          {activeTab === 'compare' && <SignalCompare />}
          {activeTab === 'ledger' && <BudgetLedgerView />}
          {activeTab === 'catalogue' && <CatalogueView />}
          {activeTab === 'settings' && <SettingsView />}
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
