import { AlertTriangle, Info } from "lucide-react";
import type { ReactNode } from "react";

/** Meldung im Interface (kein alert()): Titel, Text und optional eine Aktion. Rolle "alert" nur für Fehler. */
export function Notice({
  kind = "info",
  title,
  children,
  action,
}: {
  kind?: "info" | "error";
  title: string;
  children?: ReactNode;
  action?: { label: string; onClick: () => void; busy?: boolean };
}) {
  const Icon = kind === "error" ? AlertTriangle : Info;
  return (
    <div className={`notice notice-${kind}`} role={kind === "error" ? "alert" : "status"}>
      <Icon className="notice-icon" aria-hidden="true" />
      <div className="notice-body">
        <p className="notice-title">{title}</p>
        {children && <div className="notice-text">{children}</div>}
        {action && (
          <button type="button" className="btn btn-secondary" onClick={action.onClick} disabled={action.busy}>
            {action.label}
          </button>
        )}
      </div>
    </div>
  );
}
