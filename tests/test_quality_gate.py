from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from quality_gate import cli


def command(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


class RepoFixture:
    def __init__(self, root: Path):
        self.repo = root / "repo"
        self.repo.mkdir()
        command("git", "init", "-b", "main", str(self.repo))
        command("git", "-C", str(self.repo), "config", "user.name", "Test")
        command(
            "git",
            "-C",
            str(self.repo),
            "config",
            "user.email",
            "test@example.invalid",
        )
        (self.repo / "base.txt").write_text("base\n", encoding="utf-8")
        command("git", "-C", str(self.repo), "add", "base.txt")
        command("git", "-C", str(self.repo), "commit", "-m", "initial")

    def write_config(self, body: str) -> Path:
        config_dir = self.repo / ".jampeter"
        config_dir.mkdir(exist_ok=True)
        path = config_dir / "quality-gate.toml"
        path.write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")
        return path


class QualityGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fixture = RepoFixture(self.root)
        self.report = self.fixture.repo / ".quality-gate" / "report.json"

    def tearDown(self):
        self.temp.cleanup()

    def run_gate(self, config: Path, fix_safe: bool = False):
        return cli.run_quality_gate(
            repo=self.fixture.repo,
            config_path=config,
            report_path=self.report,
            fix_safe=fix_safe,
        )

    def test_phase_order_is_canonical(self):
        config = self.fixture.write_config(
            """
            version = 1

            [[gate]]
            id = "tests"
            phase = "test"
            command = "true"

            [[gate]]
            id = "format"
            phase = "format"
            command = "true"

            [[gate]]
            id = "lint"
            phase = "lint"
            command = "true"
            """
        )
        _, gates, _ = cli.load_config(config)
        self.assertEqual([g.gate_id for g in gates], ["format", "lint", "tests"])

    def test_required_failure_is_fail_closed(self):
        config = self.fixture.write_config(
            """
            version = 1

            [[gate]]
            id = "tests"
            phase = "test"
            command = "false"
            required = true
            """
        )
        code, report = self.run_gate(config)
        self.assertEqual(code, 2)
        self.assertEqual(report["result"], "FAIL")
        self.assertEqual(report["required_failures"], 1)

    def test_optional_failure_is_warning(self):
        config = self.fixture.write_config(
            """
            version = 1

            [[gate]]
            id = "advisory"
            phase = "clean"
            command = "false"
            required = false
            """
        )
        code, report = self.run_gate(config)
        self.assertEqual(code, 0)
        self.assertEqual(report["result"], "PASS")
        self.assertEqual(report["warnings"], 1)
        self.assertEqual(report["gates"][0]["status"], "WARN")

    def test_safe_fix_requires_explicit_operator_flag(self):
        config = self.fixture.write_config(
            """
            version = 1

            [[gate]]
            id = "format"
            phase = "format"
            command = "test -f fixed.txt"
            required = true
            safe_fix = "printf 'fixed\\n' > fixed.txt"
            """
        )
        code, _ = self.run_gate(config, fix_safe=False)
        self.assertEqual(code, 2)
        self.assertFalse((self.fixture.repo / "fixed.txt").exists())

        code, report = self.run_gate(config, fix_safe=True)
        self.assertEqual(code, 0)
        self.assertTrue((self.fixture.repo / "fixed.txt").exists())
        self.assertEqual(report["gates"][0]["status"], "PASS_AFTER_FIX")
        self.assertTrue(report["gates"][0]["safe_fix_executed"])

    def test_report_verifies_while_git_state_is_unchanged(self):
        config = self.fixture.write_config(
            """
            version = 1

            [[gate]]
            id = "tests"
            phase = "test"
            command = "true"
            """
        )
        code, report = self.run_gate(config)
        self.assertEqual(code, 0)
        self.assertEqual(
            cli.verify_report(self.fixture.repo, self.report, config),
            0,
        )
        loaded = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(
            loaded["git_state"]["fingerprint"],
            report["git_state"]["fingerprint"],
        )

    def test_report_becomes_stale_after_worktree_change(self):
        config = self.fixture.write_config(
            """
            version = 1

            [[gate]]
            id = "tests"
            phase = "test"
            command = "true"
            """
        )
        code, _ = self.run_gate(config)
        self.assertEqual(code, 0)

        (self.fixture.repo / "changed.txt").write_text(
            "changed after validation\n",
            encoding="utf-8",
        )
        self.assertEqual(
            cli.verify_report(self.fixture.repo, self.report, config),
            2,
        )

    def test_config_change_invalidates_report_when_checked(self):
        config = self.fixture.write_config(
            """
            version = 1

            [[gate]]
            id = "tests"
            phase = "test"
            command = "true"
            """
        )
        code, _ = self.run_gate(config)
        self.assertEqual(code, 0)

        config.write_text(
            config.read_text(encoding="utf-8") + "\n# changed\n",
            encoding="utf-8",
        )
        self.assertEqual(
            cli.verify_report(self.fixture.repo, self.report, config),
            2,
        )

    def test_fingerprint_changes_with_file_content(self):
        before = cli.git_state(self.fixture.repo)
        (self.fixture.repo / "base.txt").write_text("new content\n", encoding="utf-8")
        after = cli.git_state(self.fixture.repo)
        self.assertNotEqual(before["fingerprint"], after["fingerprint"])

    def test_command_output_is_not_persisted_in_report(self):
        config = self.fixture.write_config(
            """
            version = 1

            [[gate]]
            id = "tests"
            phase = "test"
            command = "printf 'SENSITIVE_OUTPUT_SHOULD_NOT_PERSIST\\n'"
            """
        )
        code, _ = self.run_gate(config)
        self.assertEqual(code, 0)
        self.assertNotIn(
            "SENSITIVE_OUTPUT_SHOULD_NOT_PERSIST",
            self.report.read_text(encoding="utf-8"),
        )

    def test_duplicate_gate_id_is_rejected(self):
        config = self.fixture.write_config(
            """
            version = 1

            [[gate]]
            id = "same"
            phase = "lint"
            command = "true"

            [[gate]]
            id = "same"
            phase = "test"
            command = "true"
            """
        )
        with self.assertRaises(cli.ConfigError):
            cli.load_config(config)


if __name__ == "__main__":
    unittest.main()
