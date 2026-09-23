# Quality Gate

**Quality Gate** turns formatting, static checks, tests, security checks and
build validation into one machine-readable contract before a Git checkpoint.

It is the **Quality** phase of the JamPeter Ops Stack:

```text
Execute
  -> Quality
  -> Preserve
  -> Deploy
  -> Verify
```

> Status: `v0.1-beta` candidate.

## Why

"Looks clean" and "tests passed" are not durable evidence.

Quality Gate makes a repository declare exactly which checks define quality,
runs them in a fixed phase order, and writes a report bound to the current Git
HEAD and working-tree fingerprint.

A changed worktree makes the report stale.

## Phases

```text
format
clean
lint
type
test
security
build
```

A project may omit phases it does not need. Gates marked `required=true`
fail closed.

## Configuration

Create:

```text
.jampeter/quality-gate.toml
```

Example:

```toml
version = 1
profile = "python-standard"

[report]
path = ".quality-gate/report.json"

[[gate]]
id = "format"
phase = "format"
command = "ruff format --check ."
required = true
safe_fix = "ruff format ."

[[gate]]
id = "lint"
phase = "lint"
command = "ruff check ."
required = true

[[gate]]
id = "tests"
phase = "test"
command = "python3 -m unittest discover -s tests -v"
required = true
```

Run:

```bash
quality-gate run
```

Explicitly allow only declared safe fixes:

```bash
quality-gate run --fix-safe
```

A failed test or security gate is **not** auto-fixed unless the repository
explicitly declared a `safe_fix` command for that gate. Do not declare semantic
repairs as safe fixes.

## GitHub Action

Consumer repositories can run the same contract in CI with:

```yaml
- uses: actions/checkout@v4

- uses: jam2peter/quality-gate@v0
  with:
    config: .jampeter/quality-gate.toml
    install-tools: ruff
```

The action:

1. installs the Quality Gate CLI from the pinned action reference;
2. optionally installs declared Python gate tools;
3. runs the repository contract;
4. verifies the generated report against the current Git state.

Safe fixes are **off by default**. To enable only repository-declared safe fixes:

```yaml
- uses: jam2peter/quality-gate@v0
  with:
    config: .jampeter/quality-gate.toml
    install-tools: ruff
    fix-safe: "true"
```

Do not enable `fix-safe` in protected CI unless the workflow is intentionally
allowed to modify its ephemeral checkout.

## Verify a report

```bash
quality-gate verify-report \
  --report .quality-gate/report.json \
  --config .jampeter/quality-gate.toml
```

Verification fails when:

- the report result is not PASS;
- HEAD changed;
- the working tree changed;
- the quality config changed.

## Report

The report stores:

- tool/config version;
- ordered gate results;
- required failure/warning counts;
- whether safe fixes ran;
- Git HEAD;
- status/index hashes;
- changed-file hashes;
- Git-state fingerprint.

Command stdout/stderr is **not persisted in the report**.

See [Report contract](docs/REPORT.md).

## Clean Code

Quality Gate deliberately does not pretend that a generic tool can fully judge
semantic code quality.

Machine-verifiable Clean Code rules belong in project commands: linters,
complexity checks, type checkers, architecture tests and duplication checks.

The baseline policy is documented in [Quality policy](docs/QUALITY-POLICY.md).

## Comments

Comments should normally explain:

```text
WHY
INVARIANT
WORKAROUND
```

Avoid comments that merely narrate the next line of code.

Comment policy may be enforced by a repository-specific `clean` or `lint`
gate when appropriate.

## Auto Checkpoint integration

The intended chain is:

```text
Quality Gate
  -> PASS report + Git fingerprint
  -> Auto Checkpoint verifies report is still current
  -> private SHA-256 checkpoint
  -> commit/push
```

This prevents a report generated for an older working-tree state from being
used as evidence for a changed checkpoint.

## Install

Requires Python 3.11+ and Git.

```bash
python3 -m pip install .
```

No mandatory third-party runtime dependency is required. The checks you declare
(Ruff, pytest, mypy, ShellCheck, etc.) remain project dependencies.

## Security

Configuration is trusted repository/operator input. Gate commands execute via
the shell. Never place secrets in commands or config files.

See [Security](docs/SECURITY.md).

## License

MIT
