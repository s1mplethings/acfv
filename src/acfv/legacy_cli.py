import importlib, sys

CANDIDATES = [
    ("acfv.app", "main"),
    ("acfv.main", "main"),
    ("acfv.entry", "main"),
    ("acfv.run", "main"),
    ("acfv.tools.cli", "main"),
]


def main(argv=None):
    """Legacy dynamic dispatcher.

    Tries a list of candidate modules to find a callable ``main``. Kept for
    backward compatibility during transition to Typer-based CLI.
    """
    last_err = None
    for mod, func in CANDIDATES:
        try:
            m = importlib.import_module(mod)
            f = getattr(m, func, None)
            if callable(f):
                return f()  # Let target handle sys.argv
        except ModuleNotFoundError:
            continue
        except Exception as e:  # noqa: BLE001
            last_err = e
            break
    msg = (
        "[acfv] 未找到真实入口。请在以下任一位置提供 main():\n" +
        "\n".join(f"  - {m}.{f}" for m, f in CANDIDATES)
    )
    if last_err:
        msg += f"\n最近一次错误：{type(last_err).__name__}: {last_err}"
    print(msg, file=sys.stderr)
    return 1
