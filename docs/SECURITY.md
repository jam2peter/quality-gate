# Security

## Trusted configuration

`.jampeter/quality-gate.toml` is trusted repository/operator configuration.

Gate commands and `safe_fix` commands execute through the shell.

Do not generate this configuration from untrusted user input.

## No implicit fixes

Quality Gate never decides how to repair a failure.

A safe fix must be explicitly declared in the repository and explicitly enabled
by the operator with:

```text
--fix-safe
```

Use safe fixes for deterministic transformations such as formatting/import
ordering. Do not mark behavior, security, database, permission or infrastructure
changes as safe fixes.

## Report contents

The report does not persist command stdout/stderr.

This reduces accidental secret retention, but a configured command can still
print sensitive information to the terminal/CI log. Checks must follow normal
secret-safe logging practices.

## Fingerprint limitations

The Git fingerprint proves equality with the observed repository state according
to the V0 algorithm. It does not sign the report and does not prove who executed
the checks.

A future release may add signed provenance without changing the V0 report's
fail-closed semantics.

## Required vs optional

A failed required gate makes the overall report FAIL.

Optional gates may produce WARN and do not block the overall result. Use
optional gates only for advisory checks.
