"""Adapter registration and discovery."""
from .registry import register, resolve, list_adapters

__all__ = ["register", "resolve", "list_adapters"]
