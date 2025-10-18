from importlib.resources import files
from pathlib import Path

PKG_ROOT = files("acfv")

def pkg_path(*parts: str) -> Path:
    return Path(PKG_ROOT.joinpath(*parts))

def assets_path(*parts: str) -> Path:
    return pkg_path("assets", *parts)

def config_path(*parts: str) -> Path:
    return pkg_path("config", *parts)

def data_path(*parts: str) -> Path:
    return pkg_path("data", *parts)

def processing_path(*parts: str) -> Path:
    return pkg_path("processing", *parts)
