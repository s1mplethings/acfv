import argparse
from . import __version__

def main() -> None:
    p = argparse.ArgumentParser(prog="acfv", description="ACFV CLI")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("hello", help="print version and hello")

    args = p.parse_args()
    if args.cmd == "hello":
        print(f"acfv {__version__} - hello")
    else:
        p.print_help()
