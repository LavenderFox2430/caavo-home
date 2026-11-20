"""Audit runtime import symbols against exact public Home Assistant source tags.

This is source inspection, not an import of Home Assistant or a runtime test.
Only public source files are fetched; credentials and the Caavo are not involved.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ("2026.11.2",)
METHOD_ARGUMENTS = {
    "homeassistant.config_entries": {
        "async_show_form": {"step_id", "data_schema", "errors", "description_placeholders"},
        "async_update_reload_and_abort": {"entry", "data_updates", "reason"},
        "_get_reconfigure_entry": set(),
        "_get_reauth_entry": set(),
        "async_set_unique_id": {"unique_id"},
        "_abort_if_unique_id_configured": {"updates"},
        "async_forward_entry_setups": {"entry", "platforms"},
        "async_unload_platforms": {"entry", "platforms"},
    },
    "homeassistant.helpers.update_coordinator": {
        "__init__": {"config_entry", "name", "update_interval", "always_update"},
        "async_config_entry_first_refresh": set(),
        "async_request_refresh": set(),
        "async_add_listener": {"update_callback"},
        "async_update_listeners": set(),
    },
    "homeassistant.helpers.device_registry": {
        "async_get_device": {"identifiers"},
        "async_update_device": {"configuration_url", "sw_version", "merge_connections"},
    },
    "homeassistant.helpers.entity_registry": {
        "async_update_entity": {"original_name"},
    },
}
ENUM_MEMBERS = {
    "homeassistant.components.media_player.const": {
        "MediaPlayerEntityFeature": {"SELECT_SOURCE", "TURN_ON", "TURN_OFF", "VOLUME_STEP"},
        "MediaPlayerState": {"ON", "OFF"},
    },
    "homeassistant.components.sensor.const": {
        "SensorDeviceClass": {"ENUM", "TEMPERATURE"},
        "SensorStateClass": {"MEASUREMENT"},
    },
    "homeassistant.const": {
        "EntityCategory": {"DIAGNOSTIC", "CONFIG"},
        "UnitOfTemperature": {"CELSIUS"},
    },
    "homeassistant.helpers.selector": {"TextSelectorType": {"PASSWORD"}},
}


def runtime_nodes(nodes):
    for node in nodes:
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "TYPE_CHECKING"
        ):
            yield from runtime_nodes(node.orelse)
        else:
            yield node
            if isinstance(node, ast.If):
                yield from runtime_nodes(node.body)
                yield from runtime_nodes(node.orelse)
            elif isinstance(node, ast.Try):
                yield from runtime_nodes(node.body)
                yield from runtime_nodes(node.orelse)
                yield from runtime_nodes(node.finalbody)
                for handler in node.handlers:
                    yield from runtime_nodes(handler.body)


def requested_imports():
    imports = {}
    for path in (ROOT / "custom_components/caavo_home").glob("*.py"):
        for node in runtime_nodes(ast.parse(path.read_text(encoding="utf-8")).body):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("homeassistant")
            ):
                imports.setdefault(node.module, set()).update(alias.name for alias in node.names)
    for module, enums in ENUM_MEMBERS.items():
        imports.setdefault(module, set()).update(enums)
    return imports


def source_path(module):
    path = module.replace(".", "/")
    if module == "homeassistant" or (
        module.startswith("homeassistant.components.") and module.count(".") == 2
    ):
        return path + "/__init__.py"
    return path + ".py"


def audit(item):
    version, module, requested = item
    # `from homeassistant import config_entries` loads a submodule directly.
    if module == "homeassistant":
        module = "homeassistant.config_entries"
        requested = {"ConfigEntry"}
    url = f"https://raw.githubusercontent.com/home-assistant/core/{version}/{source_path(module)}"
    with urllib.request.urlopen(url, timeout=20) as response:
        content = response.read()
    # Python 3.14 permits an unparenthesized tuple in except clauses. Normalize
    # only that spelling for this read-only AST audit on our Python 3.13 host.
    source = re.sub(
        r"^(\s*except\*?\s+)([A-Za-z_][\w.]*(?:,\s*[A-Za-z_][\w.]*)+)(\s*:)",
        r"\1(\2)\3",
        content.decode("utf-8"),
        flags=re.MULTILINE,
    )
    tree = ast.parse(source, filename=url)
    bindings = set()
    for node in runtime_nodes(tree.body):
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            bindings.add(node.name)
        elif isinstance(node, ast.ImportFrom | ast.Import):
            bindings.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                bindings.update(
                    child.id for child in ast.walk(target) if isinstance(child, ast.Name)
                )
        elif isinstance(node, ast.TypeAlias):
            bindings.add(node.name.id)
    missing_members = []
    for name, arguments in METHOD_ARGUMENTS.get(module, {}).items():
        candidates = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name
        ]
        if not any(
            arguments <= {arg.arg for arg in [*node.args.args, *node.args.kwonlyargs]}
            for node in candidates
        ):
            missing_members.append(name + "(" + ",".join(sorted(arguments)) + ")")
    for name, members in ENUM_MEMBERS.get(module, {}).items():
        classes = [
            node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name
        ]
        defined = {
            node.id
            for cls in classes
            for item in cls.body
            if isinstance(item, ast.Assign | ast.AnnAssign)
            for node in ast.walk(item)
            if isinstance(node, ast.Name)
        }
        missing_members.extend(name + "." + member for member in sorted(members - defined))
    return {
        "version": version,
        "module": module,
        "url": url,
        "source_sha256": hashlib.sha256(content).hexdigest(),
        "requested": sorted(requested),
        "missing_runtime_bindings": sorted(requested - bindings),
        "missing_methods_or_constants": missing_members,
    }


def main():
    requests = [
        (version, module, names)
        for version in VERSIONS
        for module, names in requested_imports().items()
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        checks = list(pool.map(audit, requests))
    checks.sort(key=lambda item: (item["version"], item["module"]))
    result = {
        "method": "Static runtime-binding inspection of exact official source tags; not a Home Assistant runtime test",
        "passed": all(
            not check["missing_runtime_bindings"] and not check["missing_methods_or_constants"]
            for check in checks
        ),
        "checks": checks,
    }
    requirements_url = (
        "https://raw.githubusercontent.com/home-assistant/core/2026.11.2/pyproject.toml"
    )
    with urllib.request.urlopen(requirements_url, timeout=20) as response:
        requirements = response.read().decode("utf-8")
    result["schema_dependency"] = re.findall(r"probatio==[0-9.]+", requirements)
    destination = ROOT / "tests/evidence/ha-import-audit.json"
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "checks": len(checks),
                "schema_dependency": result["schema_dependency"],
                "missing": [
                    check
                    for check in checks
                    if check["missing_runtime_bindings"] or check["missing_methods_or_constants"]
                ],
            },
            indent=2,
        )
    )
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
