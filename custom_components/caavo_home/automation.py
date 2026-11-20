"""Small, validated automation summaries; raw IR and macro bodies stay on Caavo."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

TERMINAL = {"completed", "cancelled", "failed", "interrupted"}
JOB_STATES = TERMINAL | {"queued", "running"}


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
        raise ValueError("Invalid automation ID")
    return value


def named_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("Invalid automation library")
    seen = set()
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("Invalid automation item")
        key = identifier(row.get("id"))
        name = row.get("name")
        if key in seen or not isinstance(name, str) or not name or len(name) > 128:
            raise ValueError("Invalid automation name or duplicate ID")
        seen.add(key)
    return value


def job_summary(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or value.get("status") not in JOB_STATES:
        raise ValueError("Invalid automation job")
    identifier(value.get("requestId"))
    result = {key: value[key] for key in ("requestId", "status")}
    for key in ("nextStep", "stepCount"):
        number = value.get(key, 0)
        if type(number) is not int or number < 0:
            raise ValueError("Invalid job progress")
        result[key] = number
    return result


def summarize(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Invalid automation state")
    library, runtime, learning = (value.get(k) for k in ("library", "runtime", "learning"))
    if not all(isinstance(v, dict) for v in (library, runtime, learning)):
        raise ValueError("Missing automation state")
    if library.get("schema") != 1 or type(library.get("revision")) is not int:
        raise ValueError("Unsupported automation library")
    buttons = {}
    devices = {}
    for device in named_rows(library.get("devices")):
        commands = named_rows(device.get("commands"))
        devices[device["id"]] = {
            "name": device["name"],
            "commands": {command["id"]: command["name"] for command in commands},
        }
        for command in commands:
            key = ("command", device["id"], command["id"])
            buttons[key] = {
                "name": f"{device['name']} · {command['name']}",
                "request": {"kind": "command", "device": device["id"], "command": command["id"]},
            }
    for kind, collection, prefix in (
        ("macro", "macros", "Macro"),
        ("activity.start", "activities", "Start"),
    ):
        for row in named_rows(library.get(collection)):
            buttons[(kind, row["id"])] = {
                "name": f"{prefix} · {row['name']}",
                "request": {"kind": kind, "id": row["id"]},
            }
    activities = {row["id"]: row["name"] for row in library["activities"]}
    active = runtime.get("activity") or None
    if active is not None and active not in activities:
        raise ValueError("Unknown current activity")
    current_job = job_summary(value.get("job"))
    # The backend can restart and leave its current-job slot empty. Durable
    # recent receipts still show the interrupted job and must remain observable.
    recent = value.get("recentJobs", [])
    if current_job is None and isinstance(recent, list) and recent:
        current_job = job_summary(max(recent, key=lambda item: item.get("createdAt", 0)))
    if not isinstance(learning.get("active"), bool):
        raise ValueError("Invalid learning state")
    return {
        "revision": library["revision"],
        "buttons": buttons,
        "devices": devices,
        "macros": {row["id"]: row["name"] for row in library["macros"]},
        "activities": activities,
        "activity": active,
        "activityState": runtime.get("activityState", "unknown"),
        "busy": bool(runtime.get("job")),
        "learning": learning["active"],
        "job": current_job,
    }


def entity_key(key: tuple[str, ...]) -> str:
    # Delimited serialization avoids collisions between IDs containing underscores.
    return "automation_" + hashlib.sha256(json.dumps(key).encode()).hexdigest()


def activity_options(state: dict[str, Any]) -> dict[str, str | None]:
    return {
        "Off": None,
        **{f"{name} ({key})": key for key, name in state.get("activities", {}).items()},
    }
