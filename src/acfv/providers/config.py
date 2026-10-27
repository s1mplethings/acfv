from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_MISSING = object()


def _raw_mapping(source: Any) -> Mapping[str, Any] | None:
    if isinstance(source, Mapping):
        return source
    payload = getattr(source, "payload", None)
    if isinstance(payload, Mapping):
        return payload
    values = getattr(source, "values", None)
    if isinstance(values, Mapping):
        return values
    config = getattr(source, "config", None)
    if isinstance(config, Mapping):
        return config
    return None


def resolve_nested_value(source: Any, key: str, default: Any = None) -> Any:
    if not key:
        return default
    mapping = _raw_mapping(source)
    if mapping is None:
        getter = getattr(source, "get", None)
        if callable(getter):
            try:
                value = getter(key, _MISSING)
            except TypeError:
                value = getter(key)
            except Exception:
                value = _MISSING
            return default if value is _MISSING else value
        return default

    if key in mapping:
        return mapping[key]

    cursor: Any = mapping
    for part in key.split("."):
        if not isinstance(cursor, Mapping) or part not in cursor:
            cursor = _MISSING
            break
        cursor = cursor[part]
    if cursor is not _MISSING:
        return cursor

    getter = getattr(source, "get", None)
    if callable(getter):
        try:
            value = getter(key, _MISSING)
        except TypeError:
            value = getter(key)
        except Exception:
            value = _MISSING
        if value is not _MISSING:
            return value
    return default


def _normalize_provider_name(value: Any, default: str) -> str:
    text = str(value or "").strip().lower()
    return text or default


def provider_name(source: Any, domain: str, *, default: str, legacy_key: str | None = None) -> str:
    explicit = resolve_nested_value(source, f"providers.{domain}.default", _MISSING)
    if explicit is not _MISSING:
        return _normalize_provider_name(explicit, default)
    if legacy_key:
        legacy = resolve_nested_value(source, legacy_key, _MISSING)
        if legacy is not _MISSING:
            return _normalize_provider_name(legacy, default)
    return default


def provider_settings(
    source: Any,
    domain: str,
    *,
    default_provider: str,
    legacy: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    provider = provider_name(source, domain, default=default_provider)
    result: dict[str, Any] = {"provider": provider}

    common = resolve_nested_value(source, f"providers.{domain}.common", {})
    if isinstance(common, Mapping):
        result.update(common)

    domain_root = resolve_nested_value(source, f"providers.{domain}", {})
    if isinstance(domain_root, Mapping):
        for key, value in domain_root.items():
            if key in {"default", "common"}:
                continue
            if key == provider and isinstance(value, Mapping):
                result.update(value)
                continue
            if not isinstance(value, Mapping):
                result.setdefault(key, value)

    for legacy_key, target_key in (legacy or {}).items():
        value = resolve_nested_value(source, legacy_key, _MISSING)
        if value is not _MISSING:
            result[target_key] = value

    return result


def config_bool(source: Any, key: str, default: bool = False) -> bool:
    value = resolve_nested_value(source, key, default)
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def config_int(source: Any, key: str, default: int) -> int:
    try:
        return int(resolve_nested_value(source, key, default))
    except Exception:
        return default


def config_float(source: Any, key: str, default: float) -> float:
    try:
        return float(resolve_nested_value(source, key, default))
    except Exception:
        return default


def config_text(source: Any, key: str, default: str = "") -> str:
    value = resolve_nested_value(source, key, default)
    return str(value or default).strip()


__all__ = [
    "config_bool",
    "config_float",
    "config_int",
    "config_text",
    "provider_name",
    "provider_settings",
    "resolve_nested_value",
]
