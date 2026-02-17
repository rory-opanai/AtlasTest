from __future__ import annotations

import json
import os
import queue
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from .dashboard_services import ACTION_TYPE_LABELS
from .storage import Storage, TaskRecord

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None


@dataclass(frozen=True)
class ActionRequest:
    run_id: str
    task_id: int | None
    action_type: str
    context: str


class ActionEngine:
    def __init__(self, storage: Storage, model: str, *, start_worker: bool = True):
        self.storage = storage
        self.model = model
        self._queue: queue.Queue[ActionRequest | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._tool_registry: dict[str, Callable[[TaskRecord | None, str], Any]] = {
            "task_context_digest": self._task_context_digest,
            "checklist_seed": self._checklist_seed,
            "execution_first_step": self._execution_first_step,
        }
        if start_worker:
            self.start()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._worker_loop, name="action-engine", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=2)

    def enqueue(self, task_id: int | None, action_type: str, context: str) -> str:
        if action_type not in ACTION_TYPE_LABELS:
            raise ValueError(f"Unsupported action type: {action_type}")
        payload = {"context": context, "enqueued_at": datetime.now(tz=timezone.utc).isoformat()}
        run_id = self.storage.create_action_run(task_id=task_id, action_type=action_type, request_payload=payload)
        self._queue.put(ActionRequest(run_id=run_id, task_id=task_id, action_type=action_type, context=context))
        return run_id

    def _worker_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                self._queue.task_done()
                return
            try:
                self.storage.update_action_run(item.run_id, status="running")
                task = self.storage.get_task(item.task_id) if item.task_id else None
                result = self._run_action(item.action_type, task, item.context)
                self.storage.update_action_run(item.run_id, status="completed", result_payload=result)
            except Exception as exc:  # pragma: no cover
                self.storage.update_action_run(item.run_id, status="failed", error=str(exc))
            finally:
                self._queue.task_done()

    def _run_action(self, action_type: str, task: TaskRecord | None, context: str) -> dict[str, Any]:
        local_tool_context = self._build_tool_context(task=task, action_type=action_type, context=context)
        if OpenAI is None or not os.getenv("OPENAI_API_KEY"):
            return self._fallback_response(action_type=action_type, task=task, context=context, tools=local_tool_context)
        return self._openai_response(action_type=action_type, task=task, context=context, tools=local_tool_context)

    def _build_tool_context(self, task: TaskRecord | None, action_type: str, context: str) -> dict[str, Any]:
        _ = action_type
        return {
            "task_context_digest": self._tool_registry["task_context_digest"](task, context),
            "checklist_seed": self._tool_registry["checklist_seed"](task, context),
            "execution_first_step": self._tool_registry["execution_first_step"](task, context),
        }

    def _task_context_digest(self, task: TaskRecord | None, context: str) -> str:
        if task is None:
            return f"General action request. Context: {context[:1000]}"
        return (
            f"Task: {task.title}\n"
            f"Source: {task.source}\n"
            f"Priority: {task.priority_bucket}\n"
            f"Action hint: {task.action_hint}\n"
            f"Status: {task.status}\n"
            f"Context: {context[:1000]}"
        )

    def _checklist_seed(self, task: TaskRecord | None, context: str) -> list[str]:
        checklist = [
            "Clarify desired outcome and success signal.",
            "Draft response or execution notes.",
            "Define owner and ETA.",
        ]
        if task and task.url:
            checklist.append(f"Review source link: {task.url}")
        if context:
            checklist.append("Incorporate user-provided context constraints.")
        return checklist

    def _execution_first_step(self, task: TaskRecord | None, context: str) -> str:
        if task is None:
            return f"Start by framing the immediate next action from context: {context[:180]}"
        return f"Start by executing: {task.action_hint}"

    def _openai_response(
        self,
        *,
        action_type: str,
        task: TaskRecord | None,
        context: str,
        tools: dict[str, Any],
    ) -> dict[str, Any]:
        client = OpenAI()
        action_label = ACTION_TYPE_LABELS[action_type]
        system = (
            "You are a productivity copilot for a Solution Engineer dashboard. "
            "No external side effects are allowed. Produce JSON only."
        )
        user = (
            f"Action type: {action_label}\n"
            f"Task title: {task.title if task else 'N/A'}\n"
            f"Task source: {task.source if task else 'N/A'}\n"
            f"User context: {context}\n"
            f"Local tools context:\n{json.dumps(tools, ensure_ascii=False)}\n\n"
            "Return valid JSON with keys: headline (string), draft (string), "
            "checklist (array of strings), next_steps (array of strings)."
        )
        response = client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        text = getattr(response, "output_text", "") or ""
        payload = _parse_json_object(text)
        if payload is None:
            payload = {
                "headline": action_label,
                "draft": text.strip() or "No model output.",
                "checklist": tools.get("checklist_seed", []),
                "next_steps": [tools.get("execution_first_step", "Start with the top priority item.")],
            }
        payload["local_tool_context"] = tools
        payload["action_type"] = action_type
        return payload

    def _fallback_response(
        self,
        *,
        action_type: str,
        task: TaskRecord | None,
        context: str,
        tools: dict[str, Any],
    ) -> dict[str, Any]:
        action_label = ACTION_TYPE_LABELS[action_type]
        title = task.title if task else "General Execution"
        focus = context if context else "Drive today's highest-leverage outcome."
        draft = (
            f"{action_label} draft for '{title}'.\n"
            f"Focus: {focus}\n"
            f"Recommended first step: {tools['execution_first_step']}"
        )
        return {
            "headline": action_label,
            "draft": draft,
            "checklist": tools.get("checklist_seed", []),
            "next_steps": [tools.get("execution_first_step", "Start with top priority task.")],
            "local_tool_context": tools,
            "action_type": action_type,
            "fallback": True,
        }


def _parse_json_object(text: str) -> dict[str, Any] | None:
    raw = text.strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = raw[start : end + 1]
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return None
    return None
