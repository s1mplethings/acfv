@echo off
setlocal enabledelayedexpansion

:: Usage: launch_experiment.bat [env_name] [python_version]
:: Defaults: env_name=clip-exp, python_version=3.10

set ENV_NAME=%1
if "%ENV_NAME%"=="" set ENV_NAME=clip-exp

set PY_VER=%2
if "%PY_VER%"=="" set PY_VER=3.10

echo === Creating/activating conda env %ENV_NAME% (Python %PY_VER%) ===
conda env list >NUL 2>&1
if errorlevel 1 (
  echo [ERROR] conda not found in PATH. Please open an Anaconda Prompt.
  exit /b 1
)

:: create env if missing
conda env list | findstr /C:"%ENV_NAME%" >NUL
if errorlevel 1 (
  conda create -n %ENV_NAME% python=%PY_VER% -y
  if errorlevel 1 (
    echo [ERROR] failed to create conda env
    exit /b 1
  )
)

:: activate env
call conda activate %ENV_NAME%
if errorlevel 1 (
  echo [ERROR] failed to activate conda env %ENV_NAME%
  exit /b 1
)

echo === Installing requirements ===
pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] pip install failed
  exit /b 1
)

echo === Running spec presence tests (plugins disabled) ===
set PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
python tools\run_spec_tests.py
if errorlevel 1 (
  echo [WARN] spec tests failed; check output above
)

:: Add your experiment command below. Examples:
:: python tools\contract_selftest.py
:: python -m acfv.cli.main --help

endlocal
