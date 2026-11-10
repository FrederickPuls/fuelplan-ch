"""LLM-Client: OpenRouter über den Anthropic-kompatiblen Endpunkt (oder direkte Anthropic-API).

- Prompt Caching: System-Prompt als Block mit cache_control (ephemeral).
- Strukturierte Ausgabe: JSON-Schema über output_config.format (native "structured outputs"); OpenRouter reicht
  es durch. Antwort wird mit pydantic validiert, bei JSON-/Schema-Fehler genau ein Wiederholungsversuch mit
  Fehlermeldung. (Erzwungener Tool-Aufruf via tool_choice "tool"/"any" wird von Sonnet 5.5 nicht mehr unterstützt.)
- Abgeschnittene Antwort (stop_reason == "max_tokens"): einmal frisch mit doppeltem max_tokens (höchstens
  config.MAX_TOKENS_CAP) neu anfragen, ohne den abgeschnittenen Text; vermerkt in usage.notes (Schritt 10).
- Pro Aufruf: Tokens (Input, Output, Cache-Read/-Write), Kosten (von OpenRouter gemeldet, sonst geschätzt).
- Verständliche Fehler: Guthaben leer / Key-Limit (402), Rate Limit (429), Anbieter nicht verfügbar (502/503/529).
- Keine Keys in Logs oder Rückgabewerten.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from fuelplan import config

T = TypeVar("T", bound=BaseModel)


# --- Fehler ---------------------------------------------------------------------------------------

class LLMError(RuntimeError):
    """Basisklasse; Meldung ist für den Nutzer verständlich formuliert."""


class CreditsExhausted(LLMError):
    pass


class RateLimited(LLMError):
    pass


class ProviderUnavailable(LLMError):
    pass


class SchemaError(LLMError):
    pass


class TruncatedResponse(LLMError):
    """Antwort auch nach dem frischen Versuch mit höherem max_tokens abgeschnitten."""


def _translate(e: anthropic.APIStatusError) -> LLMError:
    code = e.status_code
    detail = ""
    try:
        body = e.body if isinstance(e.body, dict) else json.loads(e.body or "{}")
        detail = (body.get("error") or {}).get("message") or ""
    except Exception:  # noqa: BLE001
        detail = str(e)[:200]
    if code == 402:
        return CreditsExhausted(f"OpenRouter: Guthaben leer oder Key-Limit erreicht (402). {detail}".strip())
    if code == 429:
        return RateLimited(f"Rate Limit erreicht (429), später erneut versuchen. {detail}".strip())
    if code in (502, 503, 529):
        return ProviderUnavailable(f"Anbieter nicht verfügbar ({code}), später erneut versuchen. {detail}".strip())
    if code in (401, 403):
        return LLMError(f"Zugriff verweigert ({code}): API-Key in .env prüfen. {detail}".strip())
    return LLMError(f"LLM-Fehler {code}: {detail or str(e)[:200]}")


# --- Usage ----------------------------------------------------------------------------------------

@dataclass
class Usage:
    model: str
    label: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    cost_source: str = "estimate"  # "openrouter" | "estimate"
    provider: str | None = None
    latency_s: float = 0.0
    attempts: int = 1
    timestamp: str = ""
    thinking_tokens: int = 0  # in output_tokens enthalten (Sonnet 5.5 denkt ggf. vor der Antwort)
    stop_reason: str | None = None
    notes: list[str] = field(default_factory=list)  # z. B. Grund für einen Wiederholungsversuch

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_write_tokens

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["total_tokens"] = self.total_tokens
        return d


def estimate_cost(model: str, inp: int, out: int, cache_read: int, cache_write: int) -> float | None:
    prices = config.MODEL_PRICES_USD_PER_M.get(model)
    if not prices:
        return None
    p_in, p_out, p_cr, p_cw = prices
    return (inp * p_in + out * p_out + cache_read * p_cr + cache_write * p_cw) / 1_000_000


def usage_from_response(msg: anthropic.types.Message, label: str, latency_s: float, attempts: int) -> Usage:
    u = msg.usage
    raw = u.model_dump()
    cache_read = raw.get("cache_read_input_tokens") or 0
    cache_write = raw.get("cache_creation_input_tokens") or 0
    cost = raw.get("cost")
    usage = Usage(
        model=msg.model, label=label,
        input_tokens=raw.get("input_tokens") or 0, output_tokens=raw.get("output_tokens") or 0,
        cache_read_tokens=cache_read, cache_write_tokens=cache_write,
        provider=getattr(msg, "provider", None) or msg.model_dump().get("provider"),
        latency_s=round(latency_s, 2), attempts=attempts,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        thinking_tokens=((raw.get("output_tokens_details") or {}).get("thinking_tokens") or 0),
        stop_reason=msg.stop_reason,
    )
    if isinstance(cost, (int, float)):
        usage.cost_usd, usage.cost_source = float(cost), "openrouter"
    else:
        est = estimate_cost(msg.model, usage.input_tokens, usage.output_tokens, cache_read, cache_write)
        usage.cost_usd, usage.cost_source = (est or 0.0), f"estimate ({config.MODEL_PRICES_DATE})"
    return usage


# --- Client ----------------------------------------------------------------------------------------

@dataclass
class LLMResult:
    data: BaseModel
    usage: Usage
    raw: dict = field(default_factory=dict)  # Tool-Input, wie vom Modell geliefert


class LLMClient:
    def __init__(self, provider: str = config.LLM_PROVIDER, http_client: Any = None, max_retries: int = config.LLM_MAX_RETRIES) -> None:
        self.provider = provider
        if provider == "openrouter":
            self._client = anthropic.Anthropic(
                base_url=config.OPENROUTER_BASE_URL, api_key=config.require_env("OPENROUTER_API_KEY"),
                max_retries=max_retries, timeout=config.LLM_TIMEOUT_S,
                default_headers=config.OPENROUTER_APP_HEADERS, http_client=http_client,
            )
            self._extra_body: dict = {"provider": {"only": list(config.OPENROUTER_PROVIDERS)}}
        elif provider == "anthropic":
            self._client = anthropic.Anthropic(
                api_key=config.require_env("ANTHROPIC_API_KEY"), max_retries=max_retries,
                timeout=config.LLM_TIMEOUT_S, http_client=http_client,
            )
            self._extra_body = {}
        else:
            raise ValueError(f"LLM_PROVIDER unbekannt: {provider!r} (openrouter | anthropic)")

    @staticmethod
    def _system_blocks(system: str) -> list[dict]:
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    def _create(self, **kwargs) -> anthropic.types.Message:
        try:
            return self._client.messages.create(extra_body=self._extra_body or None, **kwargs)
        except anthropic.APIStatusError as e:
            raise _translate(e) from e
        except anthropic.APIConnectionError as e:
            raise ProviderUnavailable(f"Keine Verbindung zum LLM-Endpunkt: {e.__class__.__name__}.") from e

    def complete_text(self, *, model: str, system: str, user: str, max_tokens: int, label: str = "text",
                      effort: str | None = None) -> tuple[str, Usage]:
        t0 = time.time()
        kwargs = {"output_config": {"effort": effort}} if effort else {}
        msg = self._create(model=model, max_tokens=max_tokens, system=self._system_blocks(system),
                           messages=[{"role": "user", "content": user}], **kwargs)
        text = "".join(getattr(b, "text", "") for b in msg.content)
        return text, usage_from_response(msg, label, time.time() - t0, 1)

    def complete_json(self, *, model: str, system: str, user: str, schema: type[T], max_tokens: int,
                      label: str = "json", effort: str | None = None, hints: dict | None = None) -> LLMResult:
        """Strukturierte Antwort: JSON-Schema als output_config.format, pydantic-validiert.

        - stop_reason == "max_tokens": einmal **frisch** (nur die ursprüngliche User-Message) mit doppeltem
          max_tokens, höchstens config.MAX_TOKENS_CAP; Vermerk in usage.notes. Bleibt die Antwort abgeschnitten
          oder ist die Obergrenze schon erreicht: TruncatedResponse.
        - JSON- oder Schema-Fehler: einmal mit der Fehlermeldung um Korrektur bitten, danach SchemaError.
        effort: "low" | "medium" | "high" – steuert das Denken (Sonnet 5.5 denkt immer, Haiku bei "low" nicht).
        hints: nur für den Dry-Run-Ersatz (llm/dryrun.py), hier ignoriert.
        """
        output_config: dict = {"format": {"type": "json_schema", "schema": schema.model_json_schema()}}
        if effort:
            output_config["effort"] = effort
        first: dict = {"role": "user", "content": user}
        messages: list[dict] = [first]
        limit = max_tokens
        grown = corrected = False
        t0 = time.time()
        total: Usage | None = None
        attempt = 0
        while True:
            attempt += 1
            msg = self._create(model=model, max_tokens=limit, system=self._system_blocks(system),
                               messages=messages, output_config=output_config)
            usage = usage_from_response(msg, label, time.time() - t0, attempt)
            total = usage if total is None else _add(total, usage, attempt)
            text = "".join(getattr(b, "text", "") for b in msg.content)
            if msg.stop_reason == "max_tokens":
                new_limit = min(limit * 2, config.MAX_TOKENS_CAP)
                if not grown and new_limit > limit:
                    total.notes.append(f"Versuch {attempt}: abgeschnitten bei max_tokens={limit} ({usage.output_tokens} Output-Tokens, "
                                       f"davon {usage.thinking_tokens} Denk-Tokens) – frisch mit max_tokens={new_limit}")
                    grown, limit, messages = True, new_limit, [first]
                    continue
                total.notes.append(f"Versuch {attempt}: abgeschnitten bei max_tokens={limit} (Obergrenze {config.MAX_TOKENS_CAP})")
                raise TruncatedResponse(f"Antwort auch bei max_tokens={limit} abgeschnitten ({usage.output_tokens} Output-Tokens, "
                                        f"davon {usage.thinking_tokens} Denk-Tokens). MAX_TOKENS_* und MAX_TOKENS_CAP in config.py prüfen.")
            raw: dict = {}
            try:
                raw = json.loads(text) if text.strip() else {}
                if not isinstance(raw, dict):
                    raise ValueError("kein JSON-Objekt")
                data = schema.model_validate(raw)
                return LLMResult(data=data, usage=total, raw=raw)
            except (json.JSONDecodeError, ValueError) as e:
                last_error = f"Antwort ist kein gültiges JSON ({str(e)[:80]}); stop_reason={msg.stop_reason}, {len(text)} Zeichen"
            except ValidationError as e:
                last_error = f"JSON entspricht nicht dem Schema: {e.errors()[:3]}"
            total.notes.append(f"Versuch {attempt}: {last_error}")
            if not corrected:
                corrected = True
                messages = messages + [
                    {"role": "assistant", "content": text or "{}"},
                    {"role": "user", "content": f"Ungültig: {last_error}. Bitte korrigiert erneut liefern, nur JSON nach Schema."},
                ]
                continue
            raise SchemaError(f"Antwort auch nach Wiederholung ungültig: {last_error}")


def _add(a: Usage, b: Usage, attempts: int) -> Usage:
    return Usage(
        model=a.model, label=a.label,
        input_tokens=a.input_tokens + b.input_tokens, output_tokens=a.output_tokens + b.output_tokens,
        cache_read_tokens=a.cache_read_tokens + b.cache_read_tokens, cache_write_tokens=a.cache_write_tokens + b.cache_write_tokens,
        cost_usd=round(a.cost_usd + b.cost_usd, 8), cost_source=a.cost_source, provider=a.provider,
        latency_s=b.latency_s, attempts=attempts, timestamp=b.timestamp,
        thinking_tokens=a.thinking_tokens + b.thinking_tokens, stop_reason=b.stop_reason, notes=list(a.notes),
    )
