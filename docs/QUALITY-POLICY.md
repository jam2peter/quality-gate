# Quality policy

Quality Gate separates subjective engineering judgment from objective gates.

## Clean Code baseline

Prefer:

- names that express domain intent;
- functions/classes with a coherent responsibility;
- explicit error handling;
- small public interfaces;
- configuration instead of duplicated magic values;
- tests around behavior and invariants;
- low incidental complexity;
- dependencies visible at boundaries.

Avoid:

- abstraction only to reduce line count;
- very small wrappers with no semantic value;
- silent exception swallowing;
- duplicated policy across multiple files;
- hidden global state;
- tests that only mirror implementation details.

## Formatting

Formatting should be deterministic and automated.

Typical tools:

- Python: Ruff format / Black;
- JS/TS: Prettier;
- shell: shfmt;
- YAML: yamllint-compatible style.

Formatting is a safe-fix candidate when the repository explicitly declares it.

## Comments

Prefer comments for:

### WHY

Explain non-obvious rationale.

### INVARIANT

Explain a safety/architecture rule that must not be violated.

### WORKAROUND

Explain an external limitation and the condition for removing the workaround.

Avoid comments that repeat obvious syntax.

## Verification levels

A repository may map gates to:

```text
L0 FORMAT
L1 STATIC
L2 BEHAVIOR
L3 PRESERVE
L4 RUNTIME
```

Quality Gate covers L0-L2. Auto Checkpoint provides L3. Deploy/readback
capabilities provide L4.
