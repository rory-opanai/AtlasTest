from __future__ import annotations

import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from typing import Any

from .storage import Storage


@dataclass(frozen=True)
class SkillRequest:
    run_id: str
    skill_name: str
    context: str


class SkillRunner:
    def __init__(
        self,
        storage: Storage,
        *,
        project_root: Path,
        allowlisted_skills: tuple[str, ...],
        codex_bin: str,
        timeout_seconds: int,
        start_worker: bool = True,
    ):
        self.storage = storage
        self.project_root = project_root
        self.allowlisted_skills = set(allowlisted_skills)
        self.codex_bin = codex_bin
        self.timeout_seconds = timeout_seconds
        self._queue: Queue[SkillRequest | None] = Queue()
        self._thread: threading.Thread | None = None
        if start_worker:
            self.start()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._worker_loop, name="skill-runner", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=2)

    def enqueue(self, skill_name: str, context: str) -> str:
        if skill_name not in self.allowlisted_skills:
            raise ValueError(f"Skill '{skill_name}' is not allowlisted")
        payload = {"context": context[:2000]}
        run_id = self.storage.create_skill_run(skill_name=skill_name, request_payload=payload)
        self._queue.put(SkillRequest(run_id=run_id, skill_name=skill_name, context=context[:2000]))
        return run_id

    def _worker_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                self._queue.task_done()
                return
            try:
                self.storage.update_skill_run(item.run_id, status="running")
                output = self._run_skill(item.skill_name, item.context)
                self.storage.update_skill_run(item.run_id, status="completed", output_payload=output)
            except Exception as exc:  # pragma: no cover
                self.storage.update_skill_run(item.run_id, status="failed", error=str(exc))
            finally:
                self._queue.task_done()

    def _run_skill(self, skill_name: str, context: str) -> dict[str, Any]:
        skill_path = self._resolve_skill_path(skill_name)
        prompt = (
            f"Use the skill at {skill_path}.\n"
            f"Context:\n{context[:2000]}\n\n"
            "Return a concise execution draft with:\n"
            "1) immediate actions\n2) draft response artifacts\n3) risks/open questions\n"
            "Do not perform external side effects."
        )

        with tempfile.NamedTemporaryFile(mode="w+", suffix=".txt", delete=True) as out_file:
            command = [
                self.codex_bin,
                "exec",
                "--skip-git-repo-check",
                "-C",
                str(self.project_root),
                "--output-last-message",
                out_file.name,
                prompt,
            ]
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            out_file.seek(0)
            agent_output = out_file.read().strip()

        if proc.returncode != 0:
            raise RuntimeError(
                f"Skill execution failed (exit {proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"
            )
        return {
            "skill_name": skill_name,
            "skill_path": str(skill_path),
            "output": agent_output,
            "command": command,
        }

    def _resolve_skill_path(self, skill_name: str) -> Path:
        local_skill = self.project_root / "skills" / skill_name / "SKILL.md"
        if local_skill.exists():
            return local_skill
        home_skill = Path.home() / ".codex" / "skills" / skill_name / "SKILL.md"
        if home_skill.exists():
            return home_skill
        raise FileNotFoundError(f"Skill file not found for {skill_name}")
