import { ChefHat, ChevronRight, Info, PiggyBank, Tag, Timer } from "lucide-react";
import { fmtChf, fmtInt, fmtMinutes, VARIANT_LABELS } from "../format";
import type { DinnerTarget, Recipe, ShoppingList, Variant } from "../types";
import { FuelBar } from "./FuelBar";

const ICONS: Record<Variant, typeof PiggyBank> = { budget: PiggyBank, schnell: Timer, aufwendig: ChefHat };

export function VariantCard({
  recipe,
  shopping,
  target,
  warnings,
  chosen = false,
  onOpen,
}: {
  recipe: Recipe;
  shopping?: ShoppingList;
  target: Partial<DinnerTarget>;
  warnings: string[];
  chosen?: boolean;
  onOpen?: (variant: Variant) => void;
}) {
  const v = recipe.variant;
  const Icon = ICONS[v];
  const macros = shopping?.macros_per_portion ?? recipe.estimated_macros_per_portion;
  const estimated = shopping ? shopping.macros_estimated : true;
  const price = shopping?.price_per_portion_chf;
  const titleId = `variant-${v}-title`;

  return (
    <article className={chosen ? "card variant is-chosen" : "card variant"} aria-labelledby={titleId}>
      <p className="eyebrow variant-eyebrow">
        <Icon className="eyebrow-icon" aria-hidden="true" strokeWidth={2} />
        {VARIANT_LABELS[v]}
        {chosen && <span className="chosen-badge">gewählt</span>}
      </p>
      <h3 id={titleId} className="variant-title">
        {recipe.name}
      </h3>
      <p className="variant-desc">{recipe.description}</p>

      <div className="variant-price">
        {price != null ? (
          <>
            <span className="price-number">{fmtChf(price)}</span>
            <span className="price-unit"> CHF pro Portion</span>
            <span className="price-note">
              {shopping?.has_estimates ? "teils geschätzt · " : ""}
              Schätzung {fmtChf(recipe.estimated_price_chf_per_portion)}
            </span>
          </>
        ) : (
          <>
            <span className="price-number">{fmtChf(recipe.estimated_price_chf_per_portion)}</span>
            <span className="price-unit"> CHF pro Portion</span>
            <span className="price-note">geschätzt, keine Produkte</span>
          </>
        )}
      </div>

      <p className="variant-meta">
        <span>{fmtMinutes(recipe.cooking_minutes)}</span>
        {recipe.portions > 1 && <span> · {recipe.portions} Portionen</span>}
        <span> · {recipe.equipment.join(", ")}</span>
        {shopping && shopping.promotions > 0 && (
          <span className="promo">
            {" · "}
            <Tag className="inline-icon" aria-hidden="true" />
            {shopping.promotions === 1 ? "1 Aktion" : `${shopping.promotions} Aktionen`}
          </span>
        )}
      </p>

      <div className="variant-bars">
        <p className="variant-bars-head">
          <strong>{fmtInt(macros.kcal)} kcal</strong>
          {target.kcal != null && <span className="muted"> · Ziel {fmtInt(target.kcal)}</span>}
          {estimated && <span className="muted"> · Makros geschätzt</span>}
        </p>
        <FuelBar small label="KH" value={macros.carbs_g} max={target.carbs_g ?? 0} unit="g" maxLabel={target.carbs_g != null ? `Ziel ${fmtInt(target.carbs_g)} g` : ""} />
        <FuelBar small label="Protein" value={macros.protein_g} max={target.protein_g ?? 0} unit="g" maxLabel={target.protein_g != null ? `Ziel ${fmtInt(target.protein_g)} g` : ""} />
        <FuelBar small label="Fett" value={macros.fat_g} max={target.fat_g ?? 0} unit="g" maxLabel={target.fat_g != null ? `Ziel ${fmtInt(target.fat_g)} g` : ""} />
      </div>

      {warnings.length > 0 && (
        <ul className="hints" aria-label="Hinweise">
          {warnings.map((w) => (
            <li key={w}>
              <Info className="inline-icon" aria-hidden="true" />
              <span>{w}</span>
            </li>
          ))}
        </ul>
      )}

      {onOpen && (
        <button type="button" className="card-link" onClick={() => onOpen(v)} aria-describedby={titleId}>
          <span>Rezept und Zutaten</span>
          <ChevronRight aria-hidden="true" />
        </button>
      )}
    </article>
  );
}
