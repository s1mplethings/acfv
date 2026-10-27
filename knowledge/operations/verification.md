# Verification Operations

Windows is first-class. Run `scripts/verify.ps1` for the canonical repository gate;
`scripts/verify.sh` is the POSIX equivalent. Raw receipts belong in `var/`. Promote a
reviewed receipt to `evidence/` only when it is bound to a commit and records commands,
environment, results, and limitations.
