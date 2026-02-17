from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .action_engine import ActionEngine
from .config import load_config
from .dashboard_routes import DashboardContext, build_router
from .skill_runner import SkillRunner
from .snapshot_producer import SnapshotProducer
from .storage import Storage


def create_app(
    *,
    config_path: str = "config/daily_flight_deck.yaml",
    start_workers: bool = True,
) -> FastAPI:
    config_file = Path(config_path).resolve()
    if config_file.parent.name == "config":
        project_root = config_file.parent.parent
    else:
        project_root = Path.cwd()
    config = load_config(config_path)
    config = _with_runtime_overrides(config)

    storage = Storage(project_root / config.dashboard.db_path)
    storage.init_db()

    snapshot_producer = SnapshotProducer(config=config, storage=storage, project_root=project_root)
    action_engine = ActionEngine(
        storage=storage,
        model=os.getenv("OPENAI_MODEL", config.runtime.openai_model),
        start_worker=start_workers,
    )
    skill_runner = SkillRunner(
        storage=storage,
        project_root=project_root,
        allowlisted_skills=config.runtime.allowlisted_skills,
        codex_bin=config.runtime.codex_bin,
        timeout_seconds=config.runtime.skill_execution_timeout_seconds,
        start_worker=start_workers,
    )

    templates = Jinja2Templates(directory=str(project_root / "templates"))
    context = DashboardContext(
        config=config,
        storage=storage,
        snapshot_producer=snapshot_producer,
        action_engine=action_engine,
        skill_runner=skill_runner,
        templates=templates,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        action_engine.shutdown()
        skill_runner.shutdown()

    app = FastAPI(title="SE Daily Command Center", version="0.1.0", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(project_root / "static")), name="static")
    app.include_router(build_router(context))
    app.state.dashboard_context = context

    return app


def _with_runtime_overrides(config):
    db_path = os.getenv("FLIGHT_DECK_DB_PATH", "").strip()
    snapshot_path = os.getenv("FLIGHT_DECK_SNAPSHOT_PATH", "").strip()
    if not db_path and not snapshot_path:
        return config

    dashboard = replace(
        config.dashboard,
        db_path=db_path or config.dashboard.db_path,
        snapshot_path=snapshot_path or config.dashboard.snapshot_path,
    )
    return replace(config, dashboard=dashboard)


app = create_app()
