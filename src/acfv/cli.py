import importlib, sys
CANDIDATES = [
    ("acfv.app", "main"),
    ("acfv.main", "main"),
    ("acfv.entry", "main"),
    ("acfv.run", "main"),
    ("acfv.tools.cli", "main"),
]
def main(argv=None):
    last_err = None
    for mod, func in CANDIDATES:
        try:
            m = importlib.import_module(mod)
            f = getattr(m, func, None)
            if callable(f):
                return f()  # 让被调用方自己处理 sys.argv
        except ModuleNotFoundError:
            continue
        except Exception as e:
            last_err = e
            break
    msg = "[acfv] 未找到真实入口。请在以下任一位置提供 main():\n" + \
          "\n".join(f"  - {m}.{f}" for m, f in CANDIDATES)
    if last_err:
        msg += f"\n最近一次错误：{type(last_err).__name__}: {last_err}"
    print(msg, file=sys.stderr)
    return 1
