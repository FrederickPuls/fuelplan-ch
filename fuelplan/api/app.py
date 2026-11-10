"""FastAPI-App (Phase 2, Schritt 2): Routen gemäss „API (Entwurf)“ in ../Phase2_Plan.md.

Die App reicht nur durch: jede Route ruft `fuelplan/` auf (Pipeline, history, checklist, runlog) und verpackt das
Ergebnis in die Modelle aus dto.py. Die App schickt nie ein Datum – der Server nimmt heute (Europe/Zurich) über die
Dependency `get_today`; Tests überschreiben sie mit `app.dependency_overrides`, einen öffentlichen Parameter gibt es nicht.
Server bindet nur an config.API_HOST (127.0.0.1); Zugriff vom iPhone erst in Schritt 6 über `tailscale serve`.
"""

from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from fuelplan import checklist as checklist_store
from fuelplan import config, history
from fuelplan.api.dto import (APIError, Checklist, ChecklistPatch, DayDTO, ErrorInfo, ErrorResponse, HistoryEntry,
                              HistoryPatch, RunResult, RunStarted, ShopRequest, ShopResponse, ShoppingListDTO,
                              UsageResponse, translate_exception)
from fuelplan.api.jobs import ERROR_FILE, Event, Job, JobManager, JobRunning
from fuelplan.llm.schemas import VARIANTS
from fuelplan.pipeline import Pipeline
from fuelplan.runlog import RunDir, month_summary


def get_today() -> date:
    """„Heute“ in Europe/Zurich. Tests überschreiben diese Dependency; die App kann kein Datum schicken."""
    return config.today()


@dataclass
class Settings:
    mock: bool
    dry_run: bool
    runs_dir: Path
    history_path: Path
    pipeline_factory: Callable[..., Pipeline]
    credits_fetcher: Callable[[], dict | None] | None


def _default_credits(dry_run: bool) -> Callable[[], dict | None] | None:
    if dry_run:
        return None  # kein Netz im Dry-Run, auch nicht für das Restguthaben
    from fuelplan.llm.openrouter import credits
    return credits


def create_app(*, mock: bool = False, dry_run: bool = False, pipeline_factory: Callable[..., Pipeline] | None = None,
               runs_dir: Path | None = None, history_path: Path | None = None, web_dist: Path | None = None,
               credits_fetcher: Callable[[], dict | None] | None = None, stderr=None) -> FastAPI:
    runs_dir = runs_dir or config.RUNS_DIR
    history_path = history_path or config.HISTORY_FILE
    if pipeline_factory is None:
        def pipeline_factory(**kw) -> Pipeline:  # noqa: E306
            return Pipeline(mock=mock, dry_run=dry_run, runs_dir=runs_dir, history_path=history_path, **kw)
    settings = Settings(mock=mock, dry_run=dry_run, runs_dir=runs_dir, history_path=history_path,
                        pipeline_factory=pipeline_factory, credits_fetcher=credits_fetcher or _default_credits(dry_run))
    stderr = stderr or sys.stderr
    app = FastAPI(title="FuelPlan CH", version="2.0", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.jobs = JobManager(pipeline_factory, runs_dir=runs_dir, stderr=stderr)

    def pipeline() -> Pipeline:
        return settings.pipeline_factory(log=lambda s: print(s, file=stderr))

    # --- Fehler als JSON -----------------------------------------------------------------------
    @app.exception_handler(APIError)
    async def _api_error(_: Request, e: APIError) -> JSONResponse:
        return JSONResponse(status_code=e.status, content=ErrorResponse(error=e.info).model_dump(mode="json", exclude_none=True))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, e: StarletteHTTPException) -> JSONResponse:
        """Auch die 404/405 des Routers im selben Format wie alle anderen Fehler."""
        code = {404: "not_found", 405: "method_not_allowed"}.get(e.status_code, "http_error")
        message = {404: "Diese Adresse gibt es nicht.", 405: "Diese Methode ist hier nicht erlaubt."}.get(e.status_code, str(e.detail))
        return JSONResponse(status_code=e.status_code, content=ErrorResponse(error=ErrorInfo(code=code, message=message)).model_dump(mode="json", exclude_none=True), headers=getattr(e, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, e: RequestValidationError) -> JSONResponse:
        first = e.errors()[0] if e.errors() else {}
        where = ".".join(str(x) for x in first.get("loc", []) if x != "body")
        info = ErrorInfo(code="validation_error", message="Ungültige Eingabe." + (f" Feld: {where}." if where else ""),
                         detail=str(first.get("msg", ""))[:200] or None)
        return JSONResponse(status_code=422, content=ErrorResponse(error=info).model_dump(mode="json", exclude_none=True))

    def guard(fn: Callable, *args, **kwargs):
        """Pipeline-Aufruf ausführen; Phase-1-Fehler werden zu APIError, Unerwartetes landet im Terminal, nie in der Antwort."""
        try:
            return fn(*args, **kwargs)
        except APIError:
            raise
        except Exception as e:  # noqa: BLE001
            api_err = translate_exception(e)
            if api_err.info.code == "internal_error":
                traceback.print_exception(e, file=stderr)
            raise api_err from e

    def find_run(run_id: str) -> RunDir:
        run = RunDir.find(run_id, settings.runs_dir)
        if run is None:
            raise APIError(404, "run_not_found", "Diesen Lauf gibt es nicht.", run_id=run_id)
        return run

    def run_result(run_id: str) -> RunResult:
        job: Job | None = app.state.jobs.get(run_id)
        if job is not None and job.status == "running":
            return RunResult(run_id=run_id, status="running", step=job.step, mock=settings.mock, dry_run=settings.dry_run)
        if job is not None and job.status == "error":
            return RunResult(run_id=run_id, status="error", step=job.step, error=job.error, mock=settings.mock, dry_run=settings.dry_run)
        run = find_run(run_id)
        if run.has(ERROR_FILE):  # Fehler aus einer früheren Server-Instanz
            data = run.read_json(ERROR_FILE)
            data.pop("status", None)
            return RunResult(run_id=run_id, status="error", error=ErrorInfo(**data), mock=settings.mock, dry_run=settings.dry_run)
        try:
            a = pipeline().load_part_a(run)
        except RuntimeError as e:
            api_err = translate_exception(e)
            if api_err.info.code == "run_outdated":
                raise api_err from e
            return RunResult(run_id=run_id, status="incomplete", mock=settings.mock, dry_run=settings.dry_run,
                             error=ErrorInfo(code="incomplete", message="Dieser Lauf ist unvollständig (der Server wurde wohl währenddessen beendet). Bitte einen neuen Lauf starten.",
                                             detail=str(e)))
        return RunResult.from_part_a(a, mock=settings.mock, dry_run=settings.dry_run)

    # --- Tagesanalyse ---------------------------------------------------------------------------
    @app.get("/api/day", response_model=DayDTO)
    def api_day(today: date = Depends(get_today)) -> DayDTO:
        return DayDTO.from_context(guard(pipeline().day_context, today))

    # --- Läufe ----------------------------------------------------------------------------------
    @app.post("/api/runs", response_model=RunStarted, status_code=202)
    def api_start_run(today: date = Depends(get_today)) -> RunStarted:
        try:
            job = app.state.jobs.start(today)
        except JobRunning as e:
            raise APIError(409, "job_running", "Es läuft bereits ein Lauf. Bitte warten, bis er fertig ist.", run_id=e.run_id) from e
        return RunStarted(run_id=job.run_id)

    @app.get("/api/runs/latest", response_model=RunResult, response_model_exclude_none=True)
    def api_latest_run(today: date = Depends(get_today)) -> RunResult:
        job: Job | None = app.state.jobs.current
        if job is not None and job.day == today and job.status in ("running", "error"):
            return run_result(job.run_id)
        run = RunDir.latest_with_plan(settings.runs_dir, day=today)
        if run is None:
            raise APIError(404, "no_run_today", "Heute gibt es noch keinen Lauf. Zuerst Vorschläge erstellen.")
        return run_result(run.name)

    @app.get("/api/runs/{run_id}", response_model=RunResult, response_model_exclude_none=True)
    def api_run(run_id: str) -> RunResult:
        return run_result(run_id)

    @app.get("/api/runs/{run_id}/events")
    async def api_run_events(run_id: str, request: Request) -> StreamingResponse:
        """SSE: step, log, done, error. Nachliefern ab `Last-Event-ID` (Header oder ?lastEventId=); alle Events bleiben
        gepuffert, solange der Server läuft. Nach einem Neustart gibt es nur noch den Endzustand aus dem Run-Ordner."""
        raw = request.headers.get("last-event-id") or request.query_params.get("lastEventId") or "0"
        try:
            last_id = max(0, int(raw))
        except ValueError:
            last_id = 0
        job: Job | None = app.state.jobs.get(run_id)
        if job is None:
            result = run_result(run_id)  # 404, wenn es den Ordner nicht gibt
            if result.status == "done":
                final = Event(1, "done", {"run_id": run_id, "replayed": True})
            else:
                final = Event(1, result.status, {"run_id": run_id, "replayed": True, **(result.error.model_dump(exclude_none=True) if result.error else {})})

            async def replay():
                if last_id < 1:
                    yield final.sse()
            return StreamingResponse(replay(), media_type="text/event-stream", headers=_sse_headers())

        async def stream():
            cursor = last_id
            while True:
                if await request.is_disconnected():
                    return
                events = await run_in_threadpool(job.wait, cursor, config.SSE_KEEPALIVE_S)
                for ev in events:
                    yield ev.sse()
                    cursor = ev.id
                if job.finished and not job.events_since(cursor):
                    return
                if not events:
                    yield ": keepalive\n\n"
        return StreamingResponse(stream(), media_type="text/event-stream", headers=_sse_headers())

    # --- Teil B ---------------------------------------------------------------------------------
    @app.post("/api/runs/{run_id}/shop", response_model=ShopResponse)
    def api_shop(run_id: str, body: ShopRequest) -> ShopResponse:
        job: Job | None = app.state.jobs.get(run_id)
        if job is not None and job.status == "running":
            raise APIError(409, "job_running", "Der Lauf ist noch nicht fertig.", run_id=run_id)
        run = find_run(run_id)
        pipe = pipeline()
        previous = pipe.chosen_variant(run)
        b = guard(pipe.part_b, body.variant, run)
        if previous != body.variant:
            checklist_store.reset(run)  # andere Variante → Abhak-Zustand beginnt leer
        return ShopResponse(run_id=run_id, variant=body.variant, shopping=ShoppingListDTO.wrap(b.shopping), warnings=b.warnings,
                            history_key=run.read_json("shop.json")["history_key"])

    # --- Checkliste -----------------------------------------------------------------------------
    def _checklist_context(run_id: str):
        run = find_run(run_id)
        a = guard(pipeline().load_part_a, run)
        if not a.chosen_variant:
            raise APIError(404, "no_variant", "Noch keine Variante gewählt. Zuerst im Tab „Heute“ eine Variante wählen.", run_id=run_id)
        return run, a.chosen_variant, a.shopping[a.chosen_variant]

    def _checklist_response(run_id: str, variant: str, shopping, state) -> Checklist:
        items = checklist_store.items_for(shopping, state)
        return Checklist(run_id=run_id, variant=variant, items=items, checked_count=sum(1 for i in items if i.checked), total=len(items))

    @app.get("/api/runs/{run_id}/checklist", response_model=Checklist)
    def api_checklist(run_id: str) -> Checklist:
        run, variant, shopping = _checklist_context(run_id)
        return _checklist_response(run_id, variant, shopping, checklist_store.load(run, variant))

    @app.patch("/api/runs/{run_id}/checklist", response_model=Checklist)
    def api_checklist_patch(run_id: str, body: ChecklistPatch) -> Checklist:
        run, variant, shopping = _checklist_context(run_id)
        known = {line.ingredient for line in shopping.lines}
        unknown = sorted({i.ingredient for i in body.items} - known)
        if unknown:
            raise APIError(422, "unknown_item", f"Diese Positionen stehen nicht auf der Einkaufsliste: {', '.join(unknown)}.", run_id=run_id)
        state = checklist_store.merge(checklist_store.load(run, variant), body.items)
        checklist_store.save(run, state)
        return _checklist_response(run_id, variant, shopping, state)

    # --- Archiv ---------------------------------------------------------------------------------
    @app.get("/api/history", response_model=list[HistoryEntry])
    def api_history() -> list[HistoryEntry]:
        records = history.read_all(settings.history_path)
        if not settings.dry_run:
            records = [r for r in records if not r.dry_run]  # Dry-Run-Einträge nur im Dry-Run-Server sichtbar
        return [HistoryEntry.from_record(r) for r in sorted(records, key=lambda r: r.date, reverse=True)]

    @app.patch("/api/history/{key}", response_model=HistoryEntry)
    def api_history_patch(key: str, body: HistoryPatch) -> HistoryEntry:
        if body.cooked is None and body.rating is None:
            raise APIError(422, "validation_error", "Nichts zu ändern: cooked oder rating angeben.")
        try:
            changed = history.update(key, cooked=body.cooked, rating=body.rating, path=settings.history_path)
        except KeyError:
            raise APIError(404, "history_not_found", "Diesen Archiv-Eintrag gibt es nicht.", detail=key) from None
        except ValueError as e:
            raise APIError(422, "validation_error", str(e)) from e
        return HistoryEntry.from_record(changed[-1])

    # --- Kosten ---------------------------------------------------------------------------------
    @app.get("/api/usage", response_model=UsageResponse)
    def api_usage(today: date = Depends(get_today)) -> UsageResponse:
        summary = month_summary(today.year, today.month, settings.runs_dir / "llm_usage.jsonl")
        credits, note = None, None
        if settings.credits_fetcher is None:
            note = "Restguthaben nicht abgefragt (Dry-Run)." if settings.dry_run else "Restguthaben nicht abgefragt."
        else:
            try:
                credits = settings.credits_fetcher()
            except Exception as e:  # noqa: BLE001 – Übersicht soll auch ohne Netz gehen
                note = f"Restguthaben nicht abrufbar ({e.__class__.__name__})."
        return UsageResponse(month=f"{today.year:04d}-{today.month:02d}", summary=summary, credits=credits, credits_note=note)

    # --- Frontend (web/dist, nur wenn vorhanden) ------------------------------------------------
    dist = web_dist or config.WEB_DIST_DIR
    if dist.is_dir() and (dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    else:
        @app.get("/", include_in_schema=False)
        def no_frontend():
            raise APIError(404, "no_frontend", "Kein Frontend gebaut (web/dist fehlt). Die API läuft unter /api/…")
    return app


def _sse_headers() -> dict[str, str]:
    return {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
