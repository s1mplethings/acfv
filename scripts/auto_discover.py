#!/usr/bin/env python3
import json, subprocess, sys
from datetime import datetime


def run(cmd: str):
    p = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    return p.returncode, p.stdout or "", p.stderr or ""


def main():
    code, out, err = run("bash scripts/verify.sh")
    combined = (out + "\n" + err).strip()
    head = "\n".join([l for l in combined.splitlines() if l.strip()][:120])
    task = {
        "timestamp": datetime.utcnow().strftime("%Y%m%d_%H%M%S"),
        "source": "verify",
        "verify_exit_code": code,
        "signal_head": head,
    }
    print(json.dumps(task, ensure_ascii=False, indent=2))
    sys.exit(0 if code == 0 else 2)


if __name__ == "__main__":
    main()
