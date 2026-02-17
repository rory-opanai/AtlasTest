from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .action_engine import ActionEngine
from .config import FlightDeckConfig
from .dashboard_services import ACTION_TYPE_LABELS, build_source_panels, group_tasks
from .skill_runner import SkillRunner
from .snapshot_producer import SnapshotProducer
from .storage import Storage


@dataclass
class DashboardContext:
    config: FlightDeckConfig
    storage: Storage
    snapshot_producer: SnapshotProducer
    action_engine: ActionEngine
    skill_runner: SkillRunner
    templates: Jinja2Templates


class ManualTaskCreateRequest(BaseModel):
    title: str
    action_hint: str = ""
    priority_bucket: str = "next"
    due_at: str | None = None
    project: str | None = None
    notes: str | None = None


class UpdateTaskStatusRequest(BaseModel):
    status: str


class RunActionRequest(BaseModel):
    action_type: str
    task_id: int | None = None
    context: str = ""


class RunSkillRequest(BaseModel):
    skill_name: str
    context: str = ""


def build_router(ctx: DashboardContext) -> APIRouter:
    router = APIRouter()

    @router.get("/")
    def dashboard_home(request: Request) -> Any:
        data = _dashboard_data(ctx)
        return ctx.templates.TemplateResponse(
            request=request,
            name="index.html",
            context=data,
        )

    @router.get("/partials/top-strip")
    def top_strip_partial(request: Request) -> Any:
        data = _dashboard_data(ctx)
        return ctx.templates.TemplateResponse(
            request=request,
            name="partials/top_strip.html",
            context=data,
        )

    @router.get("/partials/board")
    def board_partial(request: Request) -> Any:
        data = _dashboard_data(ctx)
        return ctx.templates.TemplateResponse(
            request=request,
            name="partials/board.html",
            context=data,
        )

    @router.get("/partials/panels")
    def panels_partial(request: Request) -> Any:
        data = _dashboard_data(ctx)
        return ctx.templates.TemplateResponse(
            request=request,
            name="partials/panels.html",
            context=data,
        )

    @router.get("/partials/runs")
    def runs_partial(request: Request) -> Any:
        data = _dashboard_data(ctx)
        return ctx.templates.TemplateResponse(
            request=request,
            name="partials/runs.html",
            context=data,
        )

    @router.post("/ui/refresh")
    def ui_refresh(background_tasks: BackgroundTasks) -> PlainTextResponse:
        try:
            _enqueue_refresh(ctx, background_tasks)
        except HTTPException as exc:
            return PlainTextResponse(str(exc.detail), status_code=exc.status_code)
        return _hx_no_content()

    @router.post("/ui/tasks/manual")
    def ui_create_manual_task(
        title: str = Form(...),
        action_hint: str = Form(""),
        due_at: str = Form(""),
        priority_bucket: str = Form("next"),
    ) -> PlainTextResponse:
        metadata = {}
        if due_at.strip():
            metadata["notes"] = "Manual task with due date"
        ctx.storage.create_manual_task(
            title=title.strip(),
            action_hint=action_hint.strip(),
            priority_bucket=priority_bucket,
            due_at=due_at.strip() or None,
            metadata=metadata,
        )
        return _hx_no_content()

    @router.post("/ui/tasks/{task_id}/status")
    def ui_update_task_status(task_id: int, status: str = Form(...)) -> PlainTextResponse:
        ctx.storage.update_task_status(task_id=task_id, status=status)
        return _hx_no_content()

    @router.post("/ui/actions/run")
    def ui_run_action(
        action_type: str = Form(...),
        task_id: str = Form(""),
        context: str = Form(""),
    ) -> PlainTextResponse:
        parsed_task_id = int(task_id) if task_id.strip() else None
        ctx.action_engine.enqueue(task_id=parsed_task_id, action_type=action_type, context=context)
        return _hx_no_content()

    @router.post("/ui/skills/run")
    def ui_run_skill(skill_name: str = Form(...), context: str = Form("")) -> PlainTextResponse:
        ctx.skill_runner.enqueue(skill_name=skill_name, context=context)
        return _hx_no_content()

    @router.get("/api/snapshot/latest")
    def api_latest_snapshot() -> JSONResponse:
        snapshot = ctx.storage.get_latest_snapshot()
        if snapshot is None:
            return JSONResponse({"snapshot": None})
        snapshot_metadata = getattr(snapshot, "metadata", {}) or {}
        return JSONResponse(
            {
                "snapshot": {
                    "id": snapshot.id,
                    "created_at": snapshot.created_at.isoformat(),
                    "source_counts": snapshot.source_counts,
                    "source": snapshot.source,
                    "status": snapshot.status,
                    "metadata": snapshot_metadata,
                    "signals": [
                        {
                            "source": item.source,
                            "title": item.title,
                            "url": item.url,
                            "score": item.score,
                            "action_hint": item.recommended_action,
                            "timestamp": item.timestamp.isoformat(),
                        }
                        for item in snapshot.signals
                    ],
                }
            }
        )

    @router.post("/api/refresh")
    def api_refresh(background_tasks: BackgroundTasks) -> JSONResponse:
        _enqueue_refresh(ctx, background_tasks)
        return JSONResponse({"status": "queued"})

    @router.post("/api/tasks/manual")
    def api_create_manual_task(payload: ManualTaskCreateRequest) -> JSONResponse:
        task_id = ctx.storage.create_manual_task(
            title=payload.title.strip(),
            action_hint=payload.action_hint.strip(),
            priority_bucket=payload.priority_bucket,
            due_at=payload.due_at,
            metadata={
                "project": payload.project or "",
                "notes": payload.notes or "",
            },
        )
        return JSONResponse({"task_id": task_id})

    @router.post("/api/tasks/{task_id}/status")
    def api_update_task_status(task_id: int, payload: UpdateTaskStatusRequest) -> JSONResponse:
        ctx.storage.update_task_status(task_id=task_id, status=payload.status)
        return JSONResponse({"task_id": task_id, "status": payload.status})

    @router.post("/api/actions/run")
    def api_run_action(payload: RunActionRequest) -> JSONResponse:
        run_id = ctx.action_engine.enqueue(
            task_id=payload.task_id,
            action_type=payload.action_type,
            context=payload.context,
        )
        return JSONResponse({"run_id": run_id, "status": "queued"})

    @router.get("/api/actions/{run_id}")
    def api_get_action_run(run_id: str) -> JSONResponse:
        record = ctx.storage.get_action_run(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Action run not found")
        return JSONResponse(
            {
                "run_id": record.run_id,
                "task_id": record.task_id,
                "action_type": record.action_type,
                "status": record.status,
                "started_at": record.started_at.isoformat(),
                "finished_at": record.finished_at.isoformat() if record.finished_at else None,
                "request_payload": record.request_payload,
                "result_payload": record.result_payload,
                "error": record.error,
            }
        )

    @router.post("/api/skills/run")
    def api_run_skill(payload: RunSkillRequest) -> JSONResponse:
        run_id = ctx.skill_runner.enqueue(skill_name=payload.skill_name, context=payload.context)
        return JSONResponse({"run_id": run_id, "status": "queued"})

    @router.get("/api/skills/{run_id}")
    def api_get_skill_run(run_id: str) -> JSONResponse:
        record = ctx.storage.get_skill_run(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Skill run not found")
        return JSONResponse(
            {
                "run_id": record.run_id,
                "skill_name": record.skill_name,
                "status": record.status,
                "started_at": record.started_at.isoformat(),
                "finished_at": record.finished_at.isoformat() if record.finished_at else None,
                "request_payload": record.request_payload,
                "output_payload": record.output_payload,
                "error": record.error,
            }
        )

    return router


def _enqueue_refresh(ctx: DashboardContext, background_tasks: BackgroundTasks) -> None:
    can_refresh, next_allowed = ctx.storage.can_refresh_now(ctx.config.dashboard.refresh_cooldown_minutes)
    if not can_refresh:
        when = next_allowed.isoformat() if next_allowed else "unknown"
        raise HTTPException(status_code=429, detail=f"Refresh cooldown active until {when}")
    ctx.storage.record_refresh_event(kind="manual", status="queued", message="refresh requested")
    background_tasks.add_task(_run_refresh_job, ctx, "manual")


def _run_refresh_job(ctx: DashboardContext, source: str) -> None:
    # Keep HTTP response stable; producer records success/failure events for UI visibility.
    try:
        ctx.snapshot_producer.safe_produce(source=source)
    except Exception:
        return


def _hx_no_content() -> PlainTextResponse:
    return PlainTextResponse("", headers={"HX-Trigger": "refresh"})


def _dashboard_data(ctx: DashboardContext) -> dict[str, Any]:
    snapshot = ctx.storage.get_latest_snapshot()
    snapshot_metadata = (getattr(snapshot, "metadata", {}) or {}) if snapshot else {}
    latest_snapshot_id = snapshot.id if snapshot else None
    tasks = ctx.storage.list_board_tasks(latest_snapshot_id)
    grouped_tasks = group_tasks(tasks)
    signals = snapshot.signals if snapshot else []
    panels = build_source_panels(signals)
    action_runs = ctx.storage.list_recent_action_runs(limit=10)
    skill_runs = ctx.storage.list_recent_skill_runs(limit=10)
    can_refresh, next_allowed = ctx.storage.can_refresh_now(ctx.config.dashboard.refresh_cooldown_minutes)

    return {
        "snapshot": snapshot,
        "snapshot_metadata": snapshot_metadata,
        "snapshot_warning": _detect_snapshot_warning(snapshot),
        "tasks_grouped": grouped_tasks,
        "panels": panels,
        "source_health": _build_source_health(snapshot, snapshot_metadata),
        "action_types": ACTION_TYPE_LABELS,
        "allowlisted_skills": sorted(ctx.skill_runner.allowlisted_skills),
        "action_runs": action_runs,
        "skill_runs": skill_runs,
        "last_refresh_event": ctx.storage.get_last_refresh_event(),
        "can_refresh": can_refresh,
        "next_refresh_allowed": next_allowed,
        "schedule_time": ctx.config.run_time,
        "schedule_days": ctx.config.run_days,
    }


def _build_source_health(snapshot: Any, snapshot_metadata: dict[str, Any]) -> list[dict[str, Any]]:
    sources = ["slack", "gmail", "calendar"]
    if snapshot is None:
        return [
            {"source": source, "raw_count": 0, "actionable_count": 0, "status": "No snapshot yet"}
            for source in sources
        ]

    raw_counts = snapshot_metadata.get("raw_counts", {})
    in_scope_raw_counts = snapshot_metadata.get("in_scope_raw_counts", {})
    actionable_counts = snapshot.source_counts or {}
    fetch_mode = snapshot_metadata.get("fetch_mode", "unknown")
    rows: list[dict[str, Any]] = []
    for source in sources:
        raw = int(raw_counts.get(source, actionable_counts.get(source, 0)))
        in_scope_raw = int(in_scope_raw_counts.get(source, raw))
        actionable = int(actionable_counts.get(source, 0))
        if raw == 0:
            status = "No raw items fetched"
        elif in_scope_raw == 0 and source == "slack":
            status = "Fetched, but none from allowlisted channels"
        elif actionable == 0:
            status = "Fetched, but none actionable in current window"
        else:
            status = "Healthy"
        rows.append(
            {
                "source": source,
                "raw_count": raw,
                "in_scope_raw_count": in_scope_raw,
                "actionable_count": actionable,
                "status": status,
                "fetch_mode": fetch_mode,
            }
        )
    return rows


def _detect_snapshot_warning(snapshot: Any) -> str | None:
    if snapshot is None:
        return None
    for item in snapshot.signals:
        url = (item.url or "").lower()
        if ".example/" in url or ".example.com" in url or "slack.example" in url or "mail.example" in url:
            return (
                "Current snapshot appears synthetic (example-domain URLs). "
                "Refresh failed or connector config is incomplete."
            )
    return None
