from __future__ import annotations

from typing import Any

_REGISTRIES: dict[str, dict[str, type]] = {
    "source": {},
    "channel": {},
    "action": {},
}


def _register(kind: str, name: str):
    def decorator(cls: type) -> type:
        _REGISTRIES[kind][name] = cls
        return cls
    return decorator


def register_source(name: str):
    return _register("source", name)


def register_channel(name: str):
    return _register("channel", name)


def register_action(name: str):
    return _register("action", name)


def get_adapter(kind: str, name: str, **kwargs: Any):
    registry = _REGISTRIES.get(kind)
    if registry is None:
        raise ValueError(f"Unknown adapter kind: {kind!r}")
    cls = registry.get(name)
    if cls is None:
        available = ", ".join(sorted(registry)) or "(none)"
        raise ValueError(f"Unknown {kind} adapter: {name!r}. Available: {available}")
    return cls(**kwargs)


def get_source(name: str, **kwargs: Any):
    return get_adapter("source", name, **kwargs)


def get_channel(name: str, **kwargs: Any):
    return get_adapter("channel", name, **kwargs)


def get_action(name: str, **kwargs: Any):
    return get_adapter("action", name, **kwargs)


def list_adapters(kind: str) -> list[str]:
    registry = _REGISTRIES.get(kind)
    if registry is None:
        raise ValueError(f"Unknown adapter kind: {kind!r}")
    return sorted(registry)
