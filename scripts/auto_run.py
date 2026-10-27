#!/usr/bin/env python3
import argparse, json, subprocess, textwrap
from datetime import datetime
from pathlib import Path


def sh(cmd):
    p = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    return p.returncode, p.stdout or "", p.stderr or ""


def write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def append_problem(entry: str):
    pr = Path("ai_context/problem_registry.md")
    pr.parent.mkdir(parents=True, exist_ok=True)
    if not pr.exists():
        pr.write_text("# Problem Registry\n\n", encoding="utf-8")
    with pr.open("a", encoding="utf-8") as f:
        f.write(entry)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--run", action="store_true")
    args = ap.parse_args()

    dc, dout, derr = sh("python scripts/auto_discover.py")
    task = json.loads(dout.strip() or "{}")
    ts = task.get("timestamp") or datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    run_dir = Path("ai_context/runs") / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    vb_c, vb_o, vb_e = sh("bash scripts/verify.sh")
    write(run_dir / "verify_before.txt", vb_o + "\n" + vb_e)
    if vb_c == 0:
        write(run_dir / "result.md", "# Auto Mode Result\n\nStatus: PASS\n\nNothing to fix.\n")
        print(f"[auto] PASS: nothing to do ({run_dir})")
        return 0

    task_card = textwrap.dedent(f"""    # Task Card

    ## Goal
    Fix verification failure so `bash scripts/verify.sh` passes.

    ## Signal (head)
    ```text
    {task.get("signal_head","")}
    ```

    ## Rules
    - Follow ai_context/prompts/00_agent_entry.md
    - Follow ai_context/auto/00_auto_mode_rules.md
    - Do NOT remove/weaken tests.

    ## Acceptance Criteria
    - `bash scripts/verify.sh` exits 0
    """).strip() + "\n"
    write(run_dir / "task_card.md", task_card)

    prompt = textwrap.dedent(f"""    You are an agent working in a code repository.

    MUST READ:
    - ai_context/prompts/00_agent_entry.md
    - ai_context/auto/00_auto_mode_rules.md
    - ai_context/auto/result_template.md

    TASK CARD:
    {task_card}

    REQUIRED OUTPUT:
    - Make changes.
    - Run `bash scripts/verify.sh`.
    - Write report to: {run_dir.as_posix()}/result.md
    """).strip() + "\n"
    write(Path("ai_context/auto/generated_task_prompt.md"), prompt)

    if args.dry_run and not args.run:
        print(f"[auto] dry-run written prompt + {run_dir}")
        return 0

    if not args.run:
        print("[auto] Not running agent. Use --run after configuring ai_context/auto/agent_config.json")
        return 0

    cfg = json.loads(Path("ai_context/auto/agent_config.json").read_text(encoding="utf-8"))
    ai_cmd = cfg.get("ai_cmd", "")
    if not ai_cmd:
        print("[auto] Missing ai_cmd")
        return 2

    rc, aout, aerr = sh(ai_cmd)
    write(run_dir / "agent_stdout.txt", aout)
    write(run_dir / "agent_stderr.txt", aerr)
    if rc != 0:
        append_problem(textwrap.dedent(f"""        ## {ts} Agent command failed
        - Command: `{ai_cmd}`
        - Exit code: {rc}

        **stderr**
        ```text
        {aerr[:4000]}
        ```

        """))
        print("[auto] agent failed; recorded")
        return 4

    va_c, va_o, va_e = sh("bash scripts/verify.sh")
    write(run_dir / "verify_after.txt", va_o + "\n" + va_e)
    res = run_dir / "result.md"
    if not res.exists():
        status = "PASS" if va_c == 0 else "FAIL"
        write(res, f"# Auto Mode Result\n\nStatus: {status}\n")
    if va_c != 0:
        append_problem(textwrap.dedent(f"""        ## {ts} verify still failing after agent run
        - Repro: `bash scripts/verify.sh`
        - Logs: {run_dir.as_posix()}
        """))
        print("[auto] still failing; recorded")
        return 5

    print("[auto] SUCCESS: verify PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
