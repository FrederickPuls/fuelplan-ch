// Sheet auf Basis von <dialog>: Fokus bleibt drin, Esc schliesst, Tippen auf den Hintergrund schliesst, „Schliessen“
// links oben (sheets.md › Mobile: Cancel/Close auf der führenden Seite). Auf dem Telefon von unten, auf breiten Fenstern zentriert.
import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

export function Sheet({
  titleId,
  onClose,
  head,
  children,
  foot,
  testId,
}: {
  titleId: string;
  onClose: () => void;
  /** Mitte der Kopfzeile (z. B. Eyebrow) */
  head?: ReactNode;
  children: ReactNode;
  foot?: ReactNode;
  testId?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dlg = ref.current;
    if (!dlg) return;
    if (!dlg.open) dlg.showModal();
    const onCancel = (e: Event) => {
      e.preventDefault();
      onClose();
    };
    dlg.addEventListener("cancel", onCancel);
    return () => dlg.removeEventListener("cancel", onCancel);
  }, [onClose]);

  return (
    <dialog
      ref={ref}
      className="sheet"
      aria-labelledby={titleId}
      data-testid={testId}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
    >
      <div className="sheet-body">
        <header className="sheet-head">
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Schliessen">
            <X aria-hidden="true" />
          </button>
          <div className="sheet-head-mid">{head}</div>
          <span className="sheet-head-spacer" aria-hidden="true" />
        </header>
        <div className="sheet-scroll">{children}</div>
        {foot && <footer className="sheet-foot">{foot}</footer>}
      </div>
    </dialog>
  );
}
