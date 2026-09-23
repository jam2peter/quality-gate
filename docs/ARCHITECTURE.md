# Architecture

## Boundary

Quality Gate does not implement language-specific formatting or testing itself.

It provides:

- an ordered gate contract;
- fail-closed required gates;
- explicit safe-fix authorization;
- a machine-readable report;
- a Git-state fingerprint;
- stale-report verification.

Project tools remain responsible for actual language semantics.

## Pipeline

```text
.jampeter/quality-gate.toml
          |
          v
      parse/validate
          |
          v
 format -> clean -> lint -> type -> test -> security -> build
          |
          +-- required failure -> overall FAIL
          +-- optional failure -> warning
          |
          v
   compute Git state
          |
          v
 quality-report.json
          |
          v
 verify-report
```

## Git fingerprint

The report binds validation to:

- current HEAD;
- raw porcelain status hash;
- staged/index diff hash;
- SHA-256 of every modified/untracked/deleted path observed by Git.

The report file itself is excluded from its own fingerprint when it lives
inside the repository.

This is intended to answer:

> Is this PASS report still describing the same Git state?

It is not a cryptographic signature or supply-chain attestation.

## Safe fixes

A fix runs only when all three are true:

1. the check failed;
2. the repository declared a non-empty `safe_fix`;
3. the operator invoked `--fix-safe`.

After the fix, the original check runs again.

The CLI never invents a fix command.

## Report portability

The report intentionally avoids storing an absolute repository path or command
output. It records Git state and configured gate metadata instead.
