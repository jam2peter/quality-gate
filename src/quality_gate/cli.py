from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__

PHASES = ("format", "clean", "lint", "type", "test", "security", "build")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Gate:
    gate_id: str
    phase: str
    command: str
    required: bool
    safe_fix: str | None
    enabled: bool
    order: int


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def repository_root(path: Path) -> Path:
    result = git(path.resolve(), "rev-parse", "--show-toplevel")
    return Path(os.fsdecode(result.stdout).strip()).resolve()


def report_relpath(repo: Path, report: Path) -> str | None:
    try:
        return report.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return None


def git_state(repo: Path, exclude: set[str] | None = None) -> dict[str, Any]:
    exclude = exclude or set()
    root = repository_root(repo)

    head = os.fsdecode(git(root, "rev-parse", "HEAD").stdout).strip()
    status = git(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    ).stdout
    index_diff = git(
        root,
        "diff",
        "--cached",
        "--binary",
        "--no-ext-diff",
        "--full-index",
    ).stdout
    paths_raw = git(
        root,
        "ls-files",
        "-m",
        "-o",
        "--exclude-standard",
        "-d",
        "-z",
    ).stdout

    paths: list[dict[str, str]] = []
    names = sorted({
        os.fsdecode(item)
        for item in paths_raw.split(b"\0")
        if item
    })
    for rel in names:
        rel_posix = Path(rel).as_posix()
        if rel_posix in exclude:
            continue

        path = root / rel
        if path.is_symlink():
            kind = "symlink"
            digest = sha256_bytes(os.readlink(path).encode("utf-8", "surrogateescape"))
        elif path.is_file():
            kind = "file"
            digest = sha256_file(path)
        elif path.exists():
            kind = "other"
            digest = sha256_bytes(kind.encode())
        else:
            kind = "missing"
            digest = sha256_bytes(kind.encode())

        paths.append({"path": rel_posix, "kind": kind, "sha256": digest})

    state = {
        "head": head,
        "status_sha256": sha256_bytes(status),
        "index_sha256": sha256_bytes(index_diff),
        "paths": paths,
    }
    canonical = json.dumps(
        state,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    state["fingerprint"] = sha256_bytes(canonical)
    return state


def load_config(path: Path) -> tuple[dict[str, Any], list[Gate], str]:
    raw = path.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))

    if data.get("version") != 1:
        raise ConfigError("version must be 1")

    gates_raw = data.get("gate")
    if not isinstance(gates_raw, list) or not gates_raw:
        raise ConfigError("at least one [[gate]] is required")

    seen: set[str] = set()
    gates: list[Gate] = []

    for index, item in enumerate(gates_raw):
        if not isinstance(item, dict):
            raise ConfigError("gate must be a TOML table")

        gate_id = item.get("id")
        phase = item.get("phase")
        command = item.get("command")

        if not isinstance(gate_id, str) or not ID_RE.fullmatch(gate_id):
            raise ConfigError(f"invalid gate id: {gate_id!r}")
        if gate_id in seen:
            raise ConfigError(f"duplicate gate id: {gate_id}")
        seen.add(gate_id)

        if phase not in PHASES:
            raise ConfigError(f"invalid phase for {gate_id}: {phase!r}")
        if not isinstance(command, str) or not command.strip():
            raise ConfigError(f"command missing for {gate_id}")

        required = item.get("required", True)
        enabled = item.get("enabled", True)
        safe_fix = item.get("safe_fix")

        if not isinstance(required, bool) or not isinstance(enabled, bool):
            raise ConfigError(f"required/enabled must be bool for {gate_id}")
        if safe_fix is not None and (
            not isinstance(safe_fix, str) or not safe_fix.strip()
        ):
            raise ConfigError(f"safe_fix invalid for {gate_id}")

        gates.append(
            Gate(
                gate_id=gate_id,
                phase=phase,
                command=command,
                required=required,
                safe_fix=safe_fix,
                enabled=enabled,
                order=index,
            )
        )

    phase_order = {name: i for i, name in enumerate(PHASES)}
    gates.sort(key=lambda gate: (phase_order[gate.phase], gate.order))
    return data, gates, sha256_bytes(raw)


def run_command(command: str, repo: Path) -> tuple[int, int]:
    started = time.monotonic()
    proc = subprocess.run(command, cwd=repo, shell=True)
    duration_ms = int((time.monotonic() - started) * 1000)
    return proc.returncode, duration_ms


def run_quality_gate(
    *,
    repo: Path,
    config_path: Path,
    report_path: Path,
    fix_safe: bool,
) -> tuple[int, dict[str, Any]]:
    root = repository_root(repo)
    config, gates, config_sha = load_config(config_path)

    results: list[dict[str, Any]] = []
    warnings = 0
    required_failures = 0
    fixes_executed = 0

    for gate in gates:
        if not gate.enabled:
            results.append(
                {
                    "id": gate.gate_id,
                    "phase": gate.phase,
                    "required": gate.required,
                    "status": "SKIPPED",
                    "exit_code": None,
                    "duration_ms": 0,
                    "safe_fix_declared": gate.safe_fix is not None,
                    "safe_fix_executed": False,
                }
            )
            continue

        print(f"QUALITY_GATE gate={gate.gate_id} phase={gate.phase} action=check")
        code, duration = run_command(gate.command, root)
        status = "PASS" if code == 0 else "FAIL"
        fix_executed = False

        if code != 0 and fix_safe and gate.safe_fix:
            print(f"QUALITY_GATE gate={gate.gate_id} action=safe_fix")
            fix_code, fix_duration = run_command(gate.safe_fix, root)
            duration += fix_duration
            fix_executed = True
            fixes_executed += 1

            if fix_code == 0:
                print(f"QUALITY_GATE gate={gate.gate_id} action=recheck")
                code, recheck_duration = run_command(gate.command, root)
                duration += recheck_duration
                status = "PASS_AFTER_FIX" if code == 0 else "FAIL"

        if code != 0:
            if gate.required:
                required_failures += 1
            else:
                warnings += 1
                status = "WARN"

        results.append(
            {
                "id": gate.gate_id,
                "phase": gate.phase,
                "required": gate.required,
                "status": status,
                "exit_code": code,
                "duration_ms": duration,
                "safe_fix_declared": gate.safe_fix is not None,
                "safe_fix_executed": fix_executed,
            }
        )

    excluded: set[str] = set()
    rel = report_relpath(root, report_path)
    if rel:
        excluded.add(rel)

    state = git_state(root, excluded)
    result = "PASS" if required_failures == 0 else "FAIL"

    report = {
        "schema_version": 1,
        "tool": "JamPeter Quality Gate",
        "tool_version": __version__,
        "profile": config.get("profile", "custom"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "result": result,
        "warnings": warnings,
        "required_failures": required_failures,
        "safe_fix_requested": fix_safe,
        "safe_fixes_executed": fixes_executed,
        "config_sha256": config_sha,
        "git_state": state,
        "gates": results,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    temp = report_path.with_suffix(report_path.suffix + ".tmp")
    temp.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(report_path)

    print(f"QUALITY_GATE_RESULT={result}")
    print(f"QUALITY_REPORT={report_path}")
    print(f"GIT_STATE_FINGERPRINT={state['fingerprint']}")
    print(f"REQUIRED_FAILURES={required_failures}")
    print(f"WARNINGS={warnings}")

    return (0 if result == "PASS" else 2), report


def verify_report(repo: Path, report_path: Path, config_path: Path | None) -> int:
    root = repository_root(repo)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    if report.get("schema_version") != 1:
        print("QUALITY_REPORT_VERIFY=FAIL reason=schema", file=sys.stderr)
        return 2
    if report.get("result") != "PASS":
        print("QUALITY_REPORT_VERIFY=FAIL reason=result_not_pass", file=sys.stderr)
        return 2

    if config_path is not None:
        _, _, config_sha = load_config(config_path)
        if report.get("config_sha256") != config_sha:
            print("QUALITY_REPORT_VERIFY=FAIL reason=config_changed", file=sys.stderr)
            return 2

    excluded: set[str] = set()
    rel = report_relpath(root, report_path)
    if rel:
        excluded.add(rel)

    current = git_state(root, excluded)
    expected = report.get("git_state", {})

    if current.get("head") != expected.get("head"):
        print("QUALITY_REPORT_VERIFY=FAIL reason=head_changed", file=sys.stderr)
        return 2
    if current.get("fingerprint") != expected.get("fingerprint"):
        print("QUALITY_REPORT_VERIFY=FAIL reason=worktree_changed", file=sys.stderr)
        return 2

    print("QUALITY_REPORT_VERIFY=PASS")
    print(f"GIT_STATE_FINGERPRINT={current['fingerprint']}")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="quality-gate")
    sub = root.add_subparsers(dest="cmd", required=True)

    run_parser = sub.add_parser("run")
    run_parser.add_argument("--repo", default=".")
    run_parser.add_argument("--config", default=".jampeter/quality-gate.toml")
    run_parser.add_argument("--report")
    run_parser.add_argument("--fix-safe", action="store_true")

    verify = sub.add_parser("verify-report")
    verify.add_argument("--repo", default=".")
    verify.add_argument("--report", required=True)
    verify.add_argument("--config")

    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)

    try:
        repo = repository_root(Path(args.repo))

        if args.cmd == "run":
            config_path = Path(args.config)
            if not config_path.is_absolute():
                config_path = repo / config_path

            config, _, _ = load_config(config_path)
            configured_report = (
                config.get("report", {}).get("path")
                if isinstance(config.get("report"), dict)
                else None
            )
            report_value = args.report or configured_report or ".quality-gate/report.json"
            report_path = Path(report_value)
            if not report_path.is_absolute():
                report_path = repo / report_path

            code, _ = run_quality_gate(
                repo=repo,
                config_path=config_path,
                report_path=report_path,
                fix_safe=args.fix_safe,
            )
            return code

        report_path = Path(args.report)
        if not report_path.is_absolute():
            report_path = repo / report_path

        config_path = None
        if args.config:
            config_path = Path(args.config)
            if not config_path.is_absolute():
                config_path = repo / config_path

        return verify_report(repo, report_path, config_path)

    except (
        ConfigError,
        OSError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
    ) as exc:
        print(f"QUALITY_GATE=BLOCKED\nCAUSE={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
