from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
import ast

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "build",
    "dist",
    ".mypy_cache",
    ".pytest_cache",
    "artifacts",
    "assets",
    "clips",
    "logs",
    "processing",
    "thumbnails",
    "var",
    "secrets",
    "node_modules",
    ".idea",
    ".vscode",
}


@dataclass
class FoundSpec:
    kind: str  # "module" or "adapter"
    name: str
    version: str
    description: Optional[str]
    impl_path: Optional[str]
    requires: List[str]
    provides: List[str]
    src: Optional[str]
    dst: Optional[str]
    file_path: str
    line: int


def _is_skip_path(p: Path) -> bool:
    for part in p.parts:
        if part in SKIP_DIRS:
            return True
    return False


def _get_str(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _resolve_str(node: ast.AST, consts: Dict[str, str]) -> Optional[str]:
    literal = _get_str(node)
    if literal is not None:
        return literal
    if isinstance(node, ast.Name):
        return consts.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return consts.get(node.attr, node.attr)
    return None


def _get_list_of_str(node: ast.AST, consts: Dict[str, str]) -> Optional[List[str]]:
    if isinstance(node, (ast.List, ast.Tuple)):
        out: List[str] = []
        for el in node.elts:
            s = _resolve_str(el, consts)
            if s is None:
                return None
            out.append(s)
        return out
    return None


def _call_name(call: ast.Call) -> str:
    fn = call.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return ""


def _kw_map(call: ast.Call) -> Dict[str, ast.AST]:
    m: Dict[str, ast.AST] = {}
    for kw in call.keywords:
        if kw.arg:
            m[kw.arg] = kw.value
    return m


def _parse_module_spec(call: ast.Call, file_path: str, lineno: int, consts: Dict[str, str]) -> Optional[FoundSpec]:
    kw = _kw_map(call)
    name = _resolve_str(kw.get("name"), consts) if "name" in kw else None
    version = _resolve_str(kw.get("version"), consts) if "version" in kw else None
    description = _resolve_str(kw.get("description"), consts) if "description" in kw else None
    impl_path = _resolve_str(kw.get("impl_path"), consts) if "impl_path" in kw else None

    requires = _get_list_of_str(kw.get("requires"), consts) if "requires" in kw else None
    if requires is None and "inputs" in kw:
        requires = _get_list_of_str(kw.get("inputs"), consts)
    provides = _get_list_of_str(kw.get("provides"), consts) if "provides" in kw else None
    if provides is None and "outputs" in kw:
        provides = _get_list_of_str(kw.get("outputs"), consts)

    if not name or not version:
        return None
    if requires is None:
        requires = []
    if provides is None:
        provides = []

    return FoundSpec(
        kind="module",
        name=name,
        version=version,
        description=description,
        impl_path=impl_path,
        requires=requires,
        provides=provides,
        src=None,
        dst=None,
        file_path=file_path,
        line=lineno,
    )


def _parse_adapter_spec(call: ast.Call, file_path: str, lineno: int, consts: Dict[str, str]) -> Optional[FoundSpec]:
    kw = _kw_map(call)
    name = _resolve_str(kw.get("name"), consts) if "name" in kw else None
    version = _resolve_str(kw.get("version"), consts) if "version" in kw else None
    description = _resolve_str(kw.get("description"), consts) if "description" in kw else None

    src = None
    if "src" in kw:
        src = _resolve_str(kw.get("src"), consts)
    if src is None and "source_type" in kw:
        src = _resolve_str(kw.get("source_type"), consts)

    dst = None
    if "dst" in kw:
        dst = _resolve_str(kw.get("dst"), consts)
    if dst is None and "target_type" in kw:
        dst = _resolve_str(kw.get("target_type"), consts)

    if not name or not version or not src or not dst:
        return None

    return FoundSpec(
        kind="adapter",
        name=name,
        version=version,
        description=description,
        impl_path=None,
        requires=[],
        provides=[dst],
        src=src,
        dst=dst,
        file_path=file_path,
        line=lineno,
    )


class _ConstVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.found: Dict[str, str] = {}

    def visit_Assign(self, node: ast.Assign) -> None:
        if len(node.targets) != 1:
            return
        target = node.targets[0]
        if isinstance(target, ast.Name):
            value = _get_str(node.value)
            if value is not None and target.id not in self.found:
                self.found[target.id] = value
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            value = _get_str(node.value) if node.value else None
            if value is not None and node.target.id not in self.found:
                self.found[node.target.id] = value
        self.generic_visit(node)


class _SpecVisitor(ast.NodeVisitor):
    def __init__(self, file_path: str, consts: Dict[str, str]) -> None:
        self.file_path = file_path
        self.consts = consts
        self.found: List[FoundSpec] = []

    def visit_Assign(self, node: ast.Assign) -> None:
        if isinstance(node.value, ast.Call):
            cname = _call_name(node.value)
            if cname == "ModuleSpec":
                fm = _parse_module_spec(node.value, self.file_path, getattr(node, "lineno", 1), self.consts)
                if fm:
                    self.found.append(fm)
            elif cname == "AdapterSpec":
                fa = _parse_adapter_spec(node.value, self.file_path, getattr(node, "lineno", 1), self.consts)
                if fa:
                    self.found.append(fa)
        self.generic_visit(node)


def _load_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def _collect_constants(files: List[Path]) -> Dict[str, str]:
    consts: Dict[str, str] = {}
    for path in files:
        text = _load_text(path)
        if text is None:
            continue
        try:
            tree = ast.parse(text)
        except Exception:
            continue
        visitor = _ConstVisitor()
        visitor.visit(tree)
        for k, v in visitor.found.items():
            if k not in consts:
                consts[k] = v
    return consts


def scan_project(root_dir: str) -> List[FoundSpec]:
    root = Path(root_dir)
    files: List[Path] = []

    for p in sorted(root.rglob("*.py")):
        if _is_skip_path(p):
            continue
        files.append(p)

    consts = _collect_constants(files)
    out: List[FoundSpec] = []

    for p in files:
        text = _load_text(p)
        if text is None:
            continue
        try:
            tree = ast.parse(text)
        except Exception:
            continue
        visitor = _SpecVisitor(str(p.resolve()), consts)
        visitor.visit(tree)
        out.extend(visitor.found)

    seen = set()
    uniq: List[FoundSpec] = []
    for item in out:
        key = (item.kind, item.name)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)

    uniq.sort(key=lambda x: (x.kind, x.name))
    return uniq


__all__ = ["FoundSpec", "scan_project"]
