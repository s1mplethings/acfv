import os, shutil, sys, subprocess, pathlib

PROJECT_ROOT = pathlib.Path(__file__).parent.resolve()
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
EXE_NAME = "ACFV"

# Prefer repo icon if present
ICON = None
for candidate in [PROJECT_ROOT / "config" / "app.ico", PROJECT_ROOT / "assets" / "acfv-icon.ico"]:
    if candidate.exists():
        ICON = candidate
        break

# Extra files/dirs to bundle; adjust as needed
EXTRA_DATAS = [
    ("best.pt", "."),
    ("TwitchDownloaderCLI.exe", "."),
    ("config", "config"),
    ("data", "data"),
    ("processing", "processing"),
    ("src/acfv", "acfv"),
]

def build():
    if DIST_DIR.exists(): shutil.rmtree(DIST_DIR)
    if BUILD_DIR.exists(): shutil.rmtree(BUILD_DIR)

    add_data_args = []
    for src, dst in EXTRA_DATAS:
        sp = PROJECT_ROOT / src
        if sp.exists():
            add_data_args += ["--add-data", f"{sp}{os.pathsep}{dst}"]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "launcher.py",
        "--name", EXE_NAME,
        "--noconsole",
        "--onefile",
        "--clean",
        # Remove the next flag if elevation is not desired
        # "--uac-admin",
    ]
    # Avoid mixing multiple Qt bindings in frozen app
    cmd += [
        "--exclude-module", "PyQt6",
        "--exclude-module", "PySide6",
        "--exclude-module", "PySide2",
    ]
if ICON:
        print(f"Using icon: {ICON}")
        cmd += ["--icon", str(ICON)]
    cmd += add_data_args

    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=PROJECT_ROOT)

    portable_dir = DIST_DIR / f"{EXE_NAME}_portable"
    portable_dir.mkdir(parents=True, exist_ok=True)

    exe_path = DIST_DIR / f"{EXE_NAME}.exe"
    shutil.copy2(exe_path, portable_dir / f"{EXE_NAME}.exe")

    for f in ["README.md", "LICENSE", "THIRD-PARTY-LICENSES.txt", "COPYRIGHT.txt"]:
        p = PROJECT_ROOT / f
        if p.exists():
            shutil.copy2(p, portable_dir / p.name)

    shutil.make_archive(str(DIST_DIR / f"{EXE_NAME}_Portable"), "zip", portable_dir)
    print("Build done:", exe_path)

if __name__ == "__main__":
    build()
