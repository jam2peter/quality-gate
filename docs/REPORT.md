# Report contract

Schema version: **1**

Example:

```json
{
  "schema_version": 1,
  "tool": "JamPeter Quality Gate",
  "tool_version": "0.1.0",
  "profile": "python-standard",
  "result": "PASS",
  "warnings": 0,
  "required_failures": 0,
  "config_sha256": "...",
  "git_state": {
    "head": "...",
    "working_diff_sha256": "...",
    "index_sha256": "...",
    "fingerprint": "...",
    "paths": [
      {
        "path": "src/example.py",
        "kind": "file",
        "sha256": "..."
      }
    ]
  },
  "gates": [
    {
      "id": "tests",
      "phase": "test",
      "required": true,
      "status": "PASS",
      "exit_code": 0,
      "duration_ms": 123,
      "safe_fix_declared": false,
      "safe_fix_executed": false
    }
  ]
}
```

## Overall result

`PASS` means every enabled required gate passed.

An optional gate may be `WARN` while the overall result remains `PASS`.

`FAIL` means at least one enabled required gate failed.

## Stale report

`verify-report` recomputes the current Git state and compares:

- HEAD;
- fingerprint;
- optionally the config SHA-256.

Any mismatch fails closed.
