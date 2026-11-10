// TypeScript-Typen der API-Antworten – Spiegel von fuelplan/api/dto.py (und der pydantic-Modelle dahinter).
// Das Frontend rechnet nichts: alle Zahlen kommen fertig von hier.

export type Variant = "budget" | "schnell" | "aufwendig";
export const VARIANTS: readonly Variant[] = ["budget", "schnell", "aufwendig"] as const;

export type RunStatus = "running" | "done" | "error" | "incomplete";
export type Step = "collect" | "plan" | "retrieve" | "execute" | "compute" | "done";
export const STEPS: readonly Step[] = ["collect", "plan", "retrieve", "execute", "compute"] as const;

export type Chain = "migros" | "denner" | "coop";

export interface ErrorInfo {
  code: string;
  message: string;
  detail?: string | null;
  run_id?: string | null;
}

export interface ErrorResponse {
  error: ErrorInfo;
}

// --- Tagesanalyse -------------------------------------------------------------------------------

export interface Activity {
  date: string;
  time?: string | null;
  type: string; // running | strength_training | cycling | hiking | other | unknown
  name: string;
  duration_min: number;
  distance_km: number;
  avg_hr?: number | null;
  max_hr?: number | null;
  kcal?: number | null;
  training_load?: number | null;
  aerobic_te?: number | null;
  anaerobic_te?: number | null;
  te_label?: string | null;
  source: string;
  external_id?: string | null;
}

export interface DailySummary {
  date: string;
  total_kcal?: number | null;
  active_kcal?: number | null;
  bmr_kcal?: number | null;
  steps?: number | null;
  resting_hr?: number | null;
  avg_stress?: number | null;
}

export interface Needs {
  kcal: number;
  carbs_g: number;
  protein_g: number;
  fat_g: number;
  kcal_range: [number, number];
  carbs_g_range: [number, number];
  protein_g_range: [number, number];
}

export interface DayClassification {
  day_type: string;
  components: string[];
  reason: string;
  macro_source?: string | null;
  surf: boolean;
}

export interface DayContext {
  date: string;
  activities: Activity[];
  daily?: DailySummary | null;
  week_load_avg_7d?: number | null;
  classification?: DayClassification | null;
  needs?: Needs | null;
}

export interface DinnerTarget {
  kcal: number;
  carbs_g: number;
  protein_g: number;
  fat_g: number;
  share_pct: number;
}

export interface DayDTO {
  date: string;
  context: DayContext;
  day_type_label?: string | null;
  dinner_target: Partial<DinnerTarget>;
  meal_split: Record<string, number>;
  source: string; // "Garmin-CSV" | "intervals.icu"
}

// --- Rezepte ------------------------------------------------------------------------------------

export interface Macros {
  kcal: number;
  carbs_g: number;
  protein_g: number;
  fat_g: number;
}

export interface Ingredient {
  name: string;
  grams: number;
  search_term: string;
  base_ingredient: boolean;
}

export interface Recipe {
  variant: Variant;
  name: string;
  description: string;
  portions: number;
  cooking_minutes: number;
  equipment: string[];
  ingredients: Ingredient[];
  steps: string[];
  estimated_price_chf_per_portion: number;
  estimated_macros_per_portion: Macros;
}

// --- Einkauf ------------------------------------------------------------------------------------

export interface Nutrition100g {
  kcal?: number | null;
  carbs_g?: number | null;
  protein_g?: number | null;
  fat_g?: number | null;
}

export interface Product {
  chain: Chain;
  product_id: string;
  name: string;
  brand?: string | null;
  size_value?: number | null;
  size_unit?: string | null;
  price_chf: number;
  regular_price_chf?: number | null;
  unit_price_chf?: number | null;
  unit_price_per?: string | null;
  promotion: boolean;
  promotion_until?: string | null;
  promotion_text?: string | null;
  nutrition?: Nutrition100g | null;
  estimated: boolean;
  note?: string | null;
  price_date?: string | null;
}

export interface ShoppingLine {
  ingredient: string;
  grams: number;
  product?: Product | null;
  packs: number;
  price_each_chf: number;
  total_chf: number;
  proportional_chf: number;
  estimated: boolean;
  promotion: boolean;
  note?: string | null;
  reason: string;
}

export interface ShoppingList {
  variant: Variant;
  recipe_name: string;
  portions: number;
  lines: ShoppingLine[];
  total_chf: number;
  proportional_total_chf: number;
  price_per_portion_chf: number;
  estimated_price_per_portion_chf: number;
  estimated_share_chf: number;
  has_estimates: boolean;
  macros_per_portion: Macros;
  macros_estimated: boolean;
  promotions: number;
  warnings: string[];
  store_totals: Record<string, number>; // Laden → Einkaufssumme (API, Abweichung 3.1)
  store_has_estimates: Record<string, boolean>;
}

// --- Läufe --------------------------------------------------------------------------------------

export interface UsageSummary {
  calls: number;
  total_cost_usd: number;
  total_tokens: number;
  dry_run: boolean;
}

export interface RunStarted {
  run_id: string;
  status: RunStatus;
}

export interface RunResult {
  run_id: string;
  status: RunStatus;
  step?: Step | null;
  error?: ErrorInfo | null;
  day?: DayDTO | null;
  recipes: Recipe[]; // Reihenfolge budget, schnell, aufwendig
  shopping: Partial<Record<Variant, ShoppingList>>;
  warnings: string[];
  queries: number;
  usage?: UsageSummary | null;
  chosen_variant?: Variant | null;
  mock: boolean;
  dry_run: boolean;
}

export interface ShopResponse {
  run_id: string;
  variant: Variant;
  shopping: ShoppingList;
  warnings: string[];
  history_key: string;
}

// --- Checkliste ---------------------------------------------------------------------------------

export interface ChecklistItem {
  ingredient: string;
  checked: boolean;
  changed_at?: string | null;
}

export interface Checklist {
  run_id: string;
  variant: Variant;
  items: ChecklistItem[];
  checked_count: number;
  total: number;
}

// --- Archiv -------------------------------------------------------------------------------------

export interface RecipeRecord {
  date: string;
  variant: Variant;
  name: string;
  main_ingredients: string[];
  price_chf_per_portion?: number | null;
  run_dir?: string | null;
  cooked?: boolean | null;
  rating?: number | null;
  dry_run: boolean;
}

export interface HistoryEntry {
  key: string;
  record: RecipeRecord;
}

// --- Kosten -------------------------------------------------------------------------------------

export interface UsageResponse {
  month: string;
  summary: Record<string, unknown>;
  credits?: Record<string, unknown> | null;
  credits_note?: string | null;
}
