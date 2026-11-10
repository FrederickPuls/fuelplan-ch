// Drei Tabs (Heute · Einkauf · Verlauf) über den URL-Hash; Tabs navigieren nur. Rezept und Kosten kommen als Sheets.
import { useEffect, useState } from "react";
import { TabBar, type Tab } from "./components/TabBar";
import { History } from "./screens/History";
import { Shopping } from "./screens/Shopping";
import { Today } from "./screens/Today";

const TABS: readonly Tab[] = ["heute", "einkauf", "verlauf"] as const;

function tabFromHash(): Tab {
  const raw = window.location.hash.replace(/^#\/?/, "").split(/[/?]/)[0];
  return (TABS as readonly string[]).includes(raw ?? "") ? (raw as Tab) : "heute";
}

export function useTab(): [Tab, (t: Tab) => void] {
  const [tab, setTab] = useState<Tab>(tabFromHash);
  useEffect(() => {
    const onHash = () => setTab(tabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const go = (t: Tab) => {
    window.location.hash = `/${t}`;
  };
  return [tab, go];
}

export default function App() {
  const [tab, go] = useTab();
  return (
    <div className="app">
      <main className="screen" id="main">
        {tab === "heute" && <Today onChosen={() => go("einkauf")} />}
        {tab === "einkauf" && <Shopping goToday={() => go("heute")} />}
        {tab === "verlauf" && <History />}
      </main>
      <TabBar active={tab} onSelect={go} />
    </div>
  );
}
