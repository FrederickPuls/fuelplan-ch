"""Hintergrund-Job für Teil A (Phase 2, Schritt 2).

- Höchstens ein Job zur Zeit; zweiter Start während eines laufenden → JobRunning(run_id).
- Der Lauf läuft in einem eigenen Thread (nicht im Event-Loop von uvicorn). Die swissgroceries-Bridge startet ihren
  eigenen asyncio-Loop ohnehin in einem weiteren Thread (asyncio.run), das verträgt sich mit dem Job-Thread.
- Events (step, log, done, error) werden mit fortlaufender ID gepuffert: ein SSE-Client, der später verbindet oder
  mit Last-Event-ID neu verbindet, bekommt alles Fehlende nachgeliefert.
- Der Run-Ordner wird vor dem Start angelegt (run_id = Ordnername). Fehler landen zusätzlich als error.json im
  Ordner, damit GET /api/runs/{id} auch nach einem Neustart den Zustand kennt (dann ohne Event-Puffer).
"""

from __future__ import annotations

import sys
import threading
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from fuelplan import config
from fuelplan.api.dto import ErrorInfo, translate_exception
from fuelplan.pipeline import PartAResult, Pipeline
from fuelplan.runlog import RunDir

ERROR_FILE = "error.json"
PipelineFactory = Callable[..., Pipeline]  # nimmt on_step= und log= entgegen


class JobRunning(Exception):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"Es läuft bereits ein Lauf: {run_id}")
        self.run_id = run_id


@dataclass
class Event:
    id: int
    event: str  # step | log | done | error
    data: dict

    def sse(self) -> str:
        import json
        return f"id: {self.id}\nevent: {self.event}\ndata: {json.dumps(self.data, ensure_ascii=False)}\n\n"


@dataclass
class Job:
    run: RunDir
    day: date
    status: str = "running"  # running | done | error
    step: str | None = None
    events: list[Event] = field(default_factory=list)
    result: PartAResult | None = None
    error: ErrorInfo | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(config.TZ))
    finished_at: datetime | None = None
    _cond: threading.Condition = field(default_factory=threading.Condition, repr=False)

    @property
    def run_id(self) -> str:
        return self.run.name

    @property
    def finished(self) -> bool:
        return self.status != "running"

    def emit(self, event: str, data: dict) -> Event:
        with self._cond:
            ev = Event(id=len(self.events) + 1, event=event, data=data)
            self.events.append(ev)
            self._cond.notify_all()
            return ev

    def events_since(self, last_id: int) -> list[Event]:
        with self._cond:
            return [e for e in self.events if e.id > last_id]

    def wait(self, last_id: int, timeout: float) -> list[Event]:
        """Blockiert bis neue Events nach last_id da sind oder der Job fertig ist (höchstens timeout Sekunden)."""
        with self._cond:
            if not any(e.id > last_id for e in self.events) and not self.finished:
                self._cond.wait(timeout)
            return [e for e in self.events if e.id > last_id]

    def _finish(self, status: str) -> None:
        with self._cond:
            self.status = status
            self.finished_at = datetime.now(config.TZ)
            self._cond.notify_all()


class JobManager:
    def __init__(self, pipeline_factory: PipelineFactory, runs_dir: Path | None = None,
                 stderr=None) -> None:
        self._factory = pipeline_factory
        self.runs_dir = runs_dir or config.RUNS_DIR
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}  # run_id → Job (alle dieser Server-Instanz)
        self.current: Job | None = None
        self._stderr = stderr or sys.stderr

    def get(self, run_id: str) -> Job | None:
        return self._jobs.get(run_id)

    def start(self, day: date) -> Job:
        with self._lock:
            if self.current is not None and not self.current.finished:
                raise JobRunning(self.current.run_id)
            run = RunDir.create(self.runs_dir)
            job = Job(run=run, day=day)
            self._jobs[job.run_id] = job
            self.current = job
        thread = threading.Thread(target=self._run, args=(job,), name=f"fuelplan-job-{job.run_id}", daemon=True)
        thread.start()
        return job

    def _run(self, job: Job) -> None:
        def on_step(step: str, detail: str) -> None:
            job.step = step
            job.emit("step", {"step": step, "detail": detail})

        def log(text: str) -> None:
            job.emit("log", {"text": text})

        try:
            pipe = self._factory(on_step=on_step, log=log)
            job.result = pipe.part_a(job.day, run=job.run)
            job.emit("done", {"run_id": job.run_id, "price_per_portion_chf": {v: sl.price_per_portion_chf for v, sl in job.result.shopping.items()}})
            job._finish("done")  # nach dem letzten Event, damit kein Client das done-Event verpasst
        except BaseException as e:  # noqa: BLE001 – jeder Fehler wird zum error-Event, der Server läuft weiter
            api_err = translate_exception(e)
            if api_err.info.code == "internal_error":
                print(f"[job {job.run_id}] unerwarteter Fehler:", file=self._stderr)
                traceback.print_exception(e, file=self._stderr)
            else:
                print(f"[job {job.run_id}] Abbruch: {api_err.info.message}", file=self._stderr)
            job.error = api_err.info
            try:
                job.run.write_json(ERROR_FILE, {"status": api_err.status, **api_err.info.model_dump()})
            except OSError:
                pass
            job.emit("error", {"status": api_err.status, **api_err.info.model_dump()})
            job._finish("error")
