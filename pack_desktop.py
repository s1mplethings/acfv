import os
import sys
import subprocess
import shutil
import pathlib
import zipfile
import time


PROJECT_ROOT = pathlib.Path(__file__).parent.resolve()
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
EXE_NAME = "ACFV"
SPEC_FILE = PROJECT_ROOT / f"{EXE_NAME}.spec"

# 选择图标文件（按优先级）
ICON_CANDIDATES = [
    PROJECT_ROOT / "config" / "app.ico",
    PROJECT_ROOT / "assets" / "acfv-icon.ico",
]
ICON = next((p for p in ICON_CANDIDATES if p.exists()), None)

# 按需调整需要打包的额外文件/目录
EXTRA_DATAS = [
    ("processing", "processing"),
    ("src/acfv", "acfv"),
]

# 是否固定兼容版本（修复 numpy 与 scikit-learn ABI 冲突）
PIN_COMPAT_PACKAGES = True
PIN_VERSIONS = [
    "numpy<2",
    "scikit-learn<1.5",
]


def run(cmd: str, *, cwd: pathlib.Path | None = None, check: bool = True) -> int:
    """运行命令，默认失败抛出异常。"""
    print(f">>> {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}")
    return result.returncode


def clean_previous_outputs() -> None:
    targets = [DIST_DIR, BUILD_DIR, SPEC_FILE, PROJECT_ROOT / "ACFV-Setup.exe", PROJECT_ROOT / "Output"]
    for target in targets:
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()


def ensure_pip() -> None:
    run(f"{sys.executable} -m pip -V", check=False)
    run(f"{sys.executable} -m pip install --upgrade pip")


def ensure_requirements() -> None:
    req = PROJECT_ROOT / "requirements.txt"
    if req.exists():
        run(f"{sys.executable} -m pip install -r \"{req}\"")
    if PIN_COMPAT_PACKAGES:
        for version in PIN_VERSIONS:
            run(f"{sys.executable} -m pip install \"{version}\"")


def ensure_pyinstaller() -> None:
    code = run("pyinstaller --version", check=False)
    if code != 0:
        run(f"{sys.executable} -m pip install pyinstaller")


def build_with_pyinstaller() -> None:
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)

    add_data_args: list[str] = []
    for src, dst in EXTRA_DATAS:
        sp = PROJECT_ROOT / src
        if sp.exists():
            add_data_args += ["--add-data", f"{sp}{os.pathsep}{dst}"]

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "launcher.py",
        "--name",
        EXE_NAME,
        "--noconsole",
        "--onedir",  # 改为 onedir 以加速打包
        "--clean",
        "--exclude-module",
        "PyQt6",
        "--exclude-module",
        "PySide6",
        "--exclude-module",
        "PySide2",
        "--exclude-module",
        "onnxruntime",  # 尝试排除有问题的模块
    ]

    if ICON:
        cmd += ["--icon", str(ICON)]
    cmd += add_data_args

    print("Running PyInstaller:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=PROJECT_ROOT)


def make_portable_zip() -> None:
    exe_dir = DIST_DIR / EXE_NAME
    if not exe_dir.exists():
        raise FileNotFoundError(f"未找到 exe 目录：{exe_dir}")

    portable_dir = DIST_DIR / f"{EXE_NAME}_portable"
    if portable_dir.exists():
        shutil.rmtree(portable_dir)
    shutil.copytree(exe_dir, portable_dir)

    for fname in ["README.md", "LICENSE", "THIRD-PARTY-LICENSES.txt", "COPYRIGHT.txt"]:
        src_path = PROJECT_ROOT / fname
        if src_path.exists():
            shutil.copy2(src_path, portable_dir / src_path.name)

    zip_path = DIST_DIR / f"{EXE_NAME}_Portable.zip"
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(portable_dir):
            for file in files:
                full = pathlib.Path(root) / file
                zf.write(full, full.relative_to(portable_dir))
    print("绿色版 zip 已生成：", zip_path)


def try_build_installer() -> None:
    iss = PROJECT_ROOT / "installer_acfv.iss"
    if not iss.exists():
        print("未找到 installer_acfv.iss，跳过安装包编译")
        return

    if run("where ISCC.exe", check=False) != 0:
        print("未检测到 Inno Setup (ISCC.exe)，跳过安装包编译")
        return

    run(f"ISCC.exe \"{iss}\"")
    print("安装包编译完成（如无报错），请在输出目录查看 ACFV-Setup.exe")


def main() -> None:
    start = time.time()
    print("=== Step 0/5: ������Ʒ ===")
    clean_previous_outputs()
    print("=== Step 1/5: 检查/升级 pip ===")
    ensure_pip()

    print("=== Step 2/5: 安装项目依赖 ===")
    ensure_requirements()

    print("=== Step 3/5: 检查 PyInstaller ===")
    ensure_pyinstaller()

    print("=== Step 4/5: PyInstaller 打包 ===")
    build_with_pyinstaller()

    print("=== Step 5/5: 生成绿色版 zip ===")
    make_portable_zip()

    print("=== 可选步骤: 生成安装包 ===")
    try_build_installer()

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    if SPEC_FILE.exists():
        SPEC_FILE.unlink()

    duration = time.time() - start
    print(f"全部完成，用时 {duration:.1f}s")
    print(f"查看产物：{DIST_DIR / EXE_NAME}")
    print(f"绿色版：{DIST_DIR / (EXE_NAME + '_Portable.zip')}")


if __name__ == "__main__":
    main()
