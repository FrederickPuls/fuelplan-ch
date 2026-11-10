"""Bedarf aus Tag-Typ + Gewicht: Mitte des Bereichs, Fett = Rest ≥ Minimum, Kombinationen, Surf."""

from __future__ import annotations

import pytest

from fuelplan.models import DayClassification, DayType
from fuelplan.nutrition import rules as R
from fuelplan.nutrition.needs import compute_needs

W = R.BODY_WEIGHT_KG  # in Tests immer 70 kg (tests/conftest.py)


def cls(*types: DayType, macro_source=None, surf=False) -> DayClassification:
    return DayClassification(day_type=types[0], components=list(types), reason="Test.", macro_source=macro_source, surf=surf)


def _consistent(n):
    assert n.kcal == n.carbs_g * 4 + n.protein_g * 4 + n.fat_g * 9 or abs(n.kcal - (n.carbs_g * 4 + n.protein_g * 4 + n.fat_g * 9)) <= 9
    assert n.fat_g >= round(R.FAT_MIN_G_PER_KG * W)
    assert n.carbs_g_range[0] <= n.carbs_g <= n.carbs_g_range[1]
    assert n.protein_g_range[0] <= n.protein_g <= n.protein_g_range[1]


@pytest.mark.parametrize("t", list(DayType))
def test_single_type_uses_table_midpoints(t):
    n = compute_needs(cls(t))
    r = R.RULES[t]
    assert n.kcal_range == r.kcal
    assert n.kcal == round(sum(r.kcal) / 2)
    assert n.carbs_g_range == r.carbs_g(W)
    assert n.carbs_g == round(sum(r.carbs_g(W)) / 2)
    assert n.protein_g == round(sum(r.protein_g(W)) / 2)
    _consistent(n)


def test_rest_day_numbers():
    n = compute_needs(cls(DayType.RUHETAG))
    assert n.kcal == 2450 and n.carbs_g == 245 and n.protein_g == 133  # Beispielgewicht 70 kg (conftest): Mitte von 126–140
    assert n.fat_g == round((2450 - 245 * 4 - 133 * 4) / 9) == 104


def test_long_run_numbers():
    n = compute_needs(cls(DayType.LONG_RUN))
    assert n.kcal == 3350 and n.carbs_g == 490 and n.protein_g == 133 and n.fat_g == 95


def test_combination_easy_run_plus_strength():
    n = compute_needs(cls(DayType.EASY_RUN, DayType.KRAFT))
    rest = R.RULES[DayType.RUHETAG].kcal
    k = R.RULES[DayType.KRAFT].kcal
    e = R.RULES[DayType.EASY_RUN].kcal
    assert n.kcal_range == (e[0] + k[0] - rest[0], e[1] + k[1] - rest[1]) == (3000, 3300)
    assert n.carbs_g_range == R.RULES[DayType.EASY_RUN].carbs_g(W)  # gleich wie Kraft
    assert n.protein_g_range == R.RULES[DayType.KRAFT].protein_g(W)  # höherer Protein-Wert von Kraft
    _consistent(n)


def test_interval_long_uses_long_run_kcal_and_carbs_but_intensive_protein():
    n = compute_needs(cls(DayType.INTENSIV, macro_source=DayType.LONG_RUN))
    assert n.kcal_range == R.RULES[DayType.LONG_RUN].kcal
    assert n.carbs_g_range == R.RULES[DayType.LONG_RUN].carbs_g(W)
    assert n.protein_g_range == R.RULES[DayType.INTENSIV].protein_g(W)


def test_surf_alone_is_locker_with_protein_upper_end():
    n = compute_needs(cls(DayType.LOCKER, surf=True))
    assert n.kcal_range == R.RULES[DayType.LOCKER].kcal
    assert n.protein_g == R.RULES[DayType.LOCKER].protein_g(W)[1]


def test_surf_plus_strength_uses_combination_rule():
    base = compute_needs(cls(DayType.KRAFT))
    n = compute_needs(cls(DayType.KRAFT, DayType.LOCKER, surf=True))
    rest = R.RULES[DayType.RUHETAG].kcal
    lk = R.RULES[DayType.LOCKER].kcal
    assert n.kcal_range == (base.kcal_range[0] + lk[0] - rest[0], base.kcal_range[1] + lk[1] - rest[1]) == (3000, 3300)
    assert n.protein_g == R.RULES[DayType.KRAFT].protein_g(W)[1]  # Kraft-Bereich, oberer Rand wegen Surf
    assert n.carbs_g_range == R.RULES[DayType.KRAFT].carbs_g(W)
    _consistent(n)


def test_fat_minimum_raises_kcal_when_rest_too_small():
    # extrem hohe KH + Protein erzwingen, über ein leichteres Gewicht und Long Run geht Fett sonst nicht unter das Minimum;
    # deshalb direkt prüfen, dass die Untergrenze greift, wenn der Rest negativ wäre
    n = compute_needs(cls(DayType.LONG_RUN), weight_kg=120)  # 120 kg: KH-Mitte 840 g, Protein 228 g → 4272 kcal > 3350
    assert n.fat_g == round(R.FAT_MIN_G_PER_KG * 120)
    assert n.kcal == n.carbs_g * 4 + n.protein_g * 4 + n.fat_g * 9


def test_weight_scales_grams():
    a = compute_needs(cls(DayType.EASY_RUN), weight_kg=70)
    b = compute_needs(cls(DayType.EASY_RUN), weight_kg=80)
    assert b.carbs_g > a.carbs_g and b.protein_g > a.protein_g


def test_body_weight_comes_from_env_with_example_default():
    """FUELPLAN_WEIGHT_KG überschreibt den Beispielwert; ohne Variable gilt DEFAULT_BODY_WEIGHT_KG."""
    import os
    import subprocess
    import sys

    from fuelplan import config

    def weight(value: str) -> str:
        env = {**os.environ, "FUELPLAN_WEIGHT_KG": value}
        code = "from fuelplan.nutrition import rules as R; print(R.BODY_WEIGHT_KG)"
        return subprocess.run([sys.executable, "-c", code], cwd=config.ROOT, env=env, capture_output=True, text=True, check=True).stdout.strip()

    assert weight("81.5") == "81.5"
    assert R.DEFAULT_BODY_WEIGHT_KG == 70.0 and W == 70.0
