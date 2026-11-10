// Rezept-Detail als Sheet. Hauptaktion unten: „Diese Variante kochen“ → POST /shop → Tab „Einkauf“.
// Aus dem Verlauf geöffnet (readOnly) gibt es keine Aktion, nur das Rezept.
import { ChefHat, PiggyBank, Timer } from "lucide-react";
import { useState } from "react";
import { api, describeError } from "../api";
import { fmtChf, fmtInt, fmtMinutes, VARIANT_LABELS, warningsFor } from "../format";
import type { Recipe, RunResult, Variant } from "../types";
import { Notice } from "./Notice";
import { Sheet } from "./Sheet";

const ICONS: Record<Variant, typeof PiggyBank> = { budget: PiggyBank, schnell: Timer, aufwendig: ChefHat };

export function RecipeSheet({
  run,
  recipe,
  onClose,
  onChosen,
  readOnly = false,
}: {
  run: RunResult;
  recipe: Recipe;
  onClose: () => void;
  onChosen?: (variant: Variant) => void;
  readOnly?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ReturnType<typeof describeError> | null>(null);
  const shopping = run.shopping[recipe.variant];
  const Icon = ICONS[recipe.variant];
  const titleId = `sheet-${recipe.variant}`;
  const warnings = warningsFor(recipe.variant, run.warnings);
  const macros = shopping?.macros_per_portion ?? recipe.estimated_macros_per_portion;

  const choose = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.shop(run.run_id, recipe.variant);
      onChosen?.(recipe.variant);
    } catch (e) {
      setError(describeError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet
      titleId={titleId}
      onClose={onClose}
      testId="recipe-sheet"
      head={
        <p className="eyebrow">
          <Icon className="eyebrow-icon" aria-hidden="true" strokeWidth={2} />
          {VARIANT_LABELS[recipe.variant]}
        </p>
      }
      foot={
        readOnly ? undefined : (
          <>
            <button type="button" className="btn btn-primary" onClick={() => void choose()} disabled={busy}>
              {busy ? "Einkaufsliste wird erstellt …" : "Diese Variante kochen"}
            </button>
            <p className="cta-note">Erstellt die Einkaufsliste und den Archiv-Eintrag, ohne neue Abfragen und ohne Modellaufruf.</p>
          </>
        )
      }
    >
      <h2 id={titleId} className="sheet-title">
        {recipe.name}
      </h2>
      <p className="variant-desc">{recipe.description}</p>

      <dl className="facts">
        <div>
          <dt>Preis pro Portion</dt>
          <dd>
            {shopping ? `${fmtChf(shopping.price_per_portion_chf)} CHF` : `${fmtChf(recipe.estimated_price_chf_per_portion)} CHF (geschätzt)`}
            {shopping && <span className="muted"> · Einkauf {fmtChf(shopping.total_chf)} CHF</span>}
          </dd>
        </div>
        <div>
          <dt>Kochzeit</dt>
          <dd>{fmtMinutes(recipe.cooking_minutes)}</dd>
        </div>
        <div>
          <dt>Portionen</dt>
          <dd>{recipe.portions}</dd>
        </div>
        <div>
          <dt>Geräte</dt>
          <dd>{recipe.equipment.join(", ")}</dd>
        </div>
        <div>
          <dt>Makros pro Portion{(shopping?.macros_estimated ?? true) && " (geschätzt)"}</dt>
          <dd>
            {fmtInt(macros.kcal)} kcal · KH {fmtInt(macros.carbs_g)} g · Protein {fmtInt(macros.protein_g)} g · Fett {fmtInt(macros.fat_g)} g
          </dd>
        </div>
      </dl>

      <h3 className="sheet-section">Zutaten{recipe.portions > 1 ? ` für ${recipe.portions} Portionen` : ""}</h3>
      <ul className="ingredients">
        {recipe.ingredients.map((ing) => (
          <li key={ing.name}>
            <span className="ingredient-name">{ing.name}</span>
            <span className="ingredient-grams">
              {fmtInt(ing.grams)} g{ing.base_ingredient && <span className="muted"> · Vorrat</span>}
            </span>
          </li>
        ))}
      </ul>

      <h3 className="sheet-section">Zubereitung</h3>
      <ol className="steps-list">
        {recipe.steps.map((s, i) => (
          <li key={i}>
            <span className="step-no" aria-hidden="true">
              {i + 1}
            </span>
            <span>{s}</span>
          </li>
        ))}
      </ol>

      {warnings.length > 0 && (
        <>
          <h3 className="sheet-section">Hinweise</h3>
          <ul className="plain-list muted">
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </>
      )}

      {error && (
        <Notice kind="error" title={error.title}>
          <p>{error.hint}</p>
        </Notice>
      )}
    </Sheet>
  );
}
