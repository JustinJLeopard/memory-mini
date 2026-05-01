from __future__ import annotations

DEFAULT_NAMESPACE = "default"


def normalize_namespace(namespace: str | None) -> str:
    if namespace is None:
        return DEFAULT_NAMESPACE
    cleaned = namespace.strip().strip("/")
    if not cleaned:
        return DEFAULT_NAMESPACE
    parts = [part for part in cleaned.split("/") if part]
    return "/".join(parts)


def namespace_parts(namespace: str | None) -> tuple[str, ...]:
    return tuple(normalize_namespace(namespace).split("/"))


def namespace_parent(namespace: str | None) -> str | None:
    parts = namespace_parts(namespace)
    if len(parts) <= 1:
        return None
    return "/".join(parts[:-1])


def namespace_children(namespace: str | None, known_namespaces: list[str]) -> list[str]:
    prefix = f"{normalize_namespace(namespace)}/"
    return sorted(name for name in known_namespaces if name.startswith(prefix))
