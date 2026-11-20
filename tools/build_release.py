"""Build a reproducible manual-install ZIP from public source files only."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/caavo_home"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-url",
        help="Explicit https://github.com/owner/repository URL; updates the local manifest only",
    )
    parser.add_argument(
        "--codeowner", help="GitHub handle, with or without @; updates local publication metadata"
    )
    args = parser.parse_args()
    manifest_path = COMPONENT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if args.repository_url:
        url = args.repository_url.rstrip("/").removesuffix(".git")
        if not re.fullmatch(r"https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", url):
            parser.error(
                "Use an explicit GitHub repository URL without query, fragment, or credentials"
            )
        manifest["documentation"] = url + "/blob/main/README.md"
        manifest["issue_tracker"] = url + "/issues"
    if args.codeowner:
        owner = args.codeowner.removeprefix("@")
        if not re.fullmatch(r"[A-Za-z0-9-]+", owner):
            parser.error("Invalid GitHub code owner")
        manifest["codeowners"] = ["@" + owner]
    if args.repository_url or args.codeowner:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    assert manifest["domain"] == "caavo_home" and manifest["config_flow"] is True
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])
    if "OWNER/REPOSITORY" in manifest["documentation"] or not manifest["codeowners"]:
        parser.error("Set the repository URL and code owner before building a release")
    files = sorted(
        path
        for path in COMPONENT.rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".json", ".png", ".svg"}
        and "__pycache__" not in path.parts
    )
    for path in files:
        if path.suffix == ".py":
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        elif path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
    assert json.loads((COMPONENT / "strings.json").read_text()) == json.loads(
        (COMPONENT / "translations/en.json").read_text()
    )
    destination = ROOT / "dist"
    destination.mkdir(exist_ok=True)
    archive = destination / f"caavo_home-{manifest['version']}.zip"
    # Live captures belong to the owner's private workspace, never a public release.
    # A clean source checkout must build without access to those files.
    entries = [(path.relative_to(ROOT).as_posix(), path.read_bytes()) for path in files]
    entries += [
        ("INSTALL_CAAVO_HOME.md", (ROOT / "README.md").read_bytes()),
        ("LICENSE_CAAVO_HOME.txt", (ROOT / "LICENSE").read_bytes()),
        ("examples/caavo-dashboard.yaml", (ROOT / "examples/caavo-dashboard.yaml").read_bytes()),
    ]
    with zipfile.ZipFile(
        archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as package:
        for name, data in entries:
            item = zipfile.ZipInfo(name, date_time=(2026, 11, 19, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            package.writestr(item, data)
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None
        assert set(package.namelist()) == {name for name, _ in entries}
        for name, data in entries:
            assert package.read(name) == data
            assert not name.startswith("/") and ".." not in Path(name).parts
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (destination / (archive.name + ".sha256")).write_text(digest + "  " + archive.name + "\n")
    receipt = {
        "version": manifest["version"],
        "file": archive.name,
        "bytes": archive.stat().st_size,
        "sha256": digest,
        "entries": len(entries),
        "verified": True,
        "repository": manifest["documentation"].removesuffix("/blob/main/README.md"),
        "published_by_this_command": False,
        "home_assistant_runtime_tested": False,
        "home_assistant_minimum": json.loads((ROOT / "hacs.json").read_text())["homeassistant"],
        "includes_device_captures": False,
    }
    (destination / "release.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
