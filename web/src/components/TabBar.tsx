// Tab-Bar unten (Telefon) bzw. Seitenleiste links (ab Laptop-Breite, per CSS); gleiche drei Ziele, Tabs navigieren nur.
import { Flame, History, ShoppingBasket } from "lucide-react";

export type Tab = "heute" | "einkauf" | "verlauf";

const ITEMS: { id: Tab; label: string; Icon: typeof Flame }[] = [
  { id: "heute", label: "Heute", Icon: Flame },
  { id: "einkauf", label: "Einkauf", Icon: ShoppingBasket },
  { id: "verlauf", label: "Verlauf", Icon: History },
];

export function TabBar({ active, onSelect }: { active: Tab; onSelect: (t: Tab) => void }) {
  return (
    <nav className="tabbar" aria-label="Bereiche">
      <p className="brand" aria-hidden="true">
        <Flame className="brand-icon" strokeWidth={2.2} />
        FuelPlan
      </p>
      <ul className="tabbar-list">
        {ITEMS.map(({ id, label, Icon }) => {
          const current = id === active;
          return (
            <li key={id}>
              <a
                href={`#/${id}`}
                className={current ? "tab is-active" : "tab"}
                aria-current={current ? "page" : undefined}
                onClick={(e) => {
                  e.preventDefault();
                  onSelect(id);
                }}
              >
                <Icon className="tab-icon" aria-hidden="true" strokeWidth={current ? 2.4 : 1.8} />
                <span className="tab-label">{label}</span>
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
