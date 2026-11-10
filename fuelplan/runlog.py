"""Run-Ordner und Kostenlog.

runs/YYYY-MM-DD_HHMM/ enthält nach Teil A: day_context.json, plan_request.json, plan_response.json,
products.json (Treffer je Suchbegriff + Zuordnung Variante → Zutat → Suchbegriff), execute_request.json,
execute_response.json (alle drei Varianten), usage.json (beide Aufrufe), output_a.md, output.md; nach Teil B
zusätzlich output_b.md und shop.json (gewählte Variante, Phase 2). Dazu runs/llm_usage.jsonl mit einer Zeile pro
LLM-Aufruf. Keine Keys oder Auth-Header.
Phase 2, Schritt 1: `RunDir.find` (ohne Anlegen, nur gültige Ordnernamen), `latest_with_plan(day=…)`, `usage()`, `day()`.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fuelplan import config
from fuelplan.llm.client import Usage

USAGE_LOG_NAME = "llm_usage.jsonl"
RUN_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}(_\d+)?$")  # YYYY-MM-DD_HHMM[_n]


def usage_log_path(runs_dir: Path | None = None) -> Path:
    return (runs_dir or config.RUNS_DIR) / USAGE_LOG_NAME


def record_usage(usage: Usage, path: Path | None = None, run_dir: str | None = None) -> None:
    path = path or usage_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = usage.to_dict()
    if run_dir:
        rec["run_dir"] = run_dir
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_usage(path: Path | None = None) -> list[dict]:
    path = path or usage_log_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class RunDir:
    """Ein Ordner pro Lauf. Teil B liest den Plan aus dem letzten Ordner, der plan_response.json enthält."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    @classmethod
    def create(cls, runs_dir: Path | None = None, now: datetime | None = None) -> "RunDir":
        runs_dir = runs_dir or config.RUNS_DIR
        now = now or datetime.now(config.TZ)
        base = now.strftime("%Y-%m-%d_%H%M")
        path = runs_dir / base
        n = 1
        while path.exists():  # zwei Läufe in derselben Minute
            n += 1
            path = runs_dir / f"{base}_{n}"
        return cls(path)

    @classmethod
    def list_with_plan(cls, runs_dir: Path | None = None) -> list["RunDir"]:
        """Alle Run-Ordner mit plan_response.json, nach Name (= Zeit) aufsteigend; legt nichts an."""
        runs_dir = runs_dir or config.RUNS_DIR
        if not runs_dir.exists():
            return []
        return [cls(p) for p in sorted((p for p in runs_dir.iterdir() if p.is_dir() and (p / "plan_response.json").exists()), key=lambda p: p.name)]

    @classmethod
    def latest_with_plan(cls, runs_dir: Path | None = None, day: date | None = None) -> "RunDir | None":
        """Letzter Lauf mit Plan; mit `day` nur Läufe, deren day_context.json dieses Datum trägt (API: heute)."""
        for run in reversed(cls.list_with_plan(runs_dir)):
            if day is None or run.day() == day:
                return run
        return None

    @classmethod
    def find(cls, name: str, runs_dir: Path | None = None) -> "RunDir | None":
        """Run-Ordner per Name (z. B. aus einer URL), ohne ihn anzulegen; None bei ungültigem Namen oder fehlendem Ordner."""
        runs_dir = runs_dir or config.RUNS_DIR
        if not RUN_NAME_RE.match(name or ""):
            return None
        path = runs_dir / name
        return cls(path) if path.is_dir() else None

    @property
    def name(self) -> str:
        return self.path.name

    def write_json(self, name: str, data: Any) -> Path:
        p = self.path / name
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return p

    def read_json(self, name: str) -> Any:
        return json.loads((self.path / name).read_text(encoding="utf-8"))

    def has(self, name: str) -> bool:
        return (self.path / name).exists()

    def day(self) -> date | None:
        """Datum der Tagesanalyse aus day_context.json (nicht das Datum im Ordnernamen, das ist die Startzeit)."""
        if not self.has("day_context.json"):
            return None
        try:
            return date.fromisoformat(self.read_json("day_context.json")["date"])
        except (KeyError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def usage(self) -> dict:
        """usage.json (Aufrufe, Summe Kosten und Tokens) oder leer."""
        return self.read_json("usage.json") if self.has("usage.json") else {"calls": [], "total_cost_usd": 0.0, "total_tokens": 0}

    def write_text(self, name: str, text: str) -> Path:
        p = self.path / name
        p.write_text(text, encoding="utf-8")
        return p

    def add_usage(self, usage: Usage) -> None:
        """usage.json: Liste aller Aufrufe des Laufs plus Summe; echte Aufrufe zusätzlich ins Kostenlog."""
        data = self.read_json("usage.json") if self.has("usage.json") else {"calls": []}
        data["calls"].append(usage.to_dict())
        data["total_cost_usd"] = round(sum(c["cost_usd"] for c in data["calls"]), 6)
        data["total_tokens"] = sum(c["total_tokens"] for c in data["calls"])
        self.write_json("usage.json", data)
        if usage.cost_source != "dry-run":
            record_usage(usage, path=usage_log_path(self.path.parent), run_dir=self.name)


# --- Schritt 8: Monatsübersicht ---------------------------------------------------------------------

def month_summary(year: int, month: int, path: Path | None = None) -> dict:
    """Summe aller geloggten Aufrufe des Monats (nach Zeitstempel), gruppiert nach Run-Ordner."""
    rows = [r for r in read_usage(path) if r.get("timestamp", "").startswith(f"{year:04d}-{month:02d}")]
    runs: dict[str, dict] = {}
    for r in rows:
        key = r.get("run_dir") or "(ohne Run-Ordner)"
        d = runs.setdefault(key, {"calls": 0, "cost_usd": 0.0, "tokens": 0, "labels": []})
        d["calls"] += 1
        d["cost_usd"] = round(d["cost_usd"] + r.get("cost_usd", 0.0), 6)
        d["tokens"] += r.get("total_tokens", 0)
        d["labels"].append(r.get("label", ""))
    total = round(sum(r.get("cost_usd", 0.0) for r in rows), 6)
    estimated = sum(1 for r in rows if not str(r.get("cost_source", "")).startswith("openrouter"))
    return {
        "year": year, "month": month, "calls": len(rows), "runs": runs, "total_cost_usd": total,
        "estimated_calls": estimated, "budget_usd": config.MONTHLY_BUDGET_USD,
        "budget_left_usd": round(config.MONTHLY_BUDGET_USD - total, 6),
        "budget_pct": round(100 * total / config.MONTHLY_BUDGET_USD, 1) if config.MONTHLY_BUDGET_USD else None,
    }


def render_month_summary(summary: dict, credits: dict | None) -> str:
    y, m = summary["year"], summary["month"]
    lines = [f"## Kosten {m:02d}/{y}", ""]
    lines.append(f"Aufrufe: {summary['calls']} in {len(summary['runs'])} Läufen · Summe {summary['total_cost_usd']:.4f} USD "
                 f"von {summary['budget_usd']:.2f} USD Monatsbudget ({summary['budget_pct']:.1f} %) · Rest {summary['budget_left_usd']:.4f} USD")
    if summary["estimated_calls"]:
        lines.append(f"Davon {summary['estimated_calls']} Aufruf(e) mit geschätzten Kosten (keine OpenRouter-Angabe).")
    if summary["runs"]:
        lines.append("")
        lines.append("| Lauf | Aufrufe | Tokens | Kosten USD |")
        lines.append("|---|---|---|---|")
        for name, d in sorted(summary["runs"].items()):
            tokens = f"{d['tokens']:,}".replace(",", "'")
            lines.append(f"| {name} | {d['calls']} ({', '.join(d['labels'])}) | {tokens} | {d['cost_usd']:.4f} |")
    lines.append("")
    if credits:
        lines.append(f"OpenRouter: Key-Limit {credits['limit']:.2f} USD, verbraucht {credits['usage']:.4f} USD, "
                     f"Rest {credits['limit_remaining']:.4f} USD · Guthaben total {credits['total_credits']:.2f} USD, "
                     f"davon verbraucht {credits['total_usage']:.4f} USD")
    else:
        lines.append("OpenRouter: Restguthaben nicht abgefragt.")
    return "\n".join(lines) + "\n"
