"""Dedicated storage for named modification-key sets (profile-independent)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from loguru import logger

from app.core.models import ModificationKeys

MODKEY_SETS_SCHEMA_VERSION = 1
DEFAULT_MODKEY_SET_NAME = "Default"
DEFAULT_MODKEY_SETS_PATH = Path("modkey_sets.json")


def default_modification_keys() -> ModificationKeys:
    return {
        "alt": {"enabled": True, "value": "Pass", "pass": True},
        "ctrl": {"enabled": True, "value": "Pass", "pass": True},
        "shift": {"enabled": True, "value": "Pass", "pass": True},
    }


def coerce_modification_keys(raw: object) -> ModificationKeys:
    """Normalize stored keys; invalid/missing entries fall back to defaults."""
    result = default_modification_keys()
    if not isinstance(raw, Mapping):
        return result
    root = {str(k): v for k, v in cast(Mapping[object, object], raw).items()}
    for key in ("alt", "ctrl", "shift"):
        item_raw = root.get(key)
        if not isinstance(item_raw, Mapping):
            continue
        item = {str(k): v for k, v in cast(Mapping[object, object], item_raw).items()}
        enabled = bool(item.get("enabled", True))
        pass_through = bool(item.get("pass", False))
        raw_value = item.get("value", "Pass")
        value = (
            "Pass"
            if pass_through
            else str(raw_value if raw_value is not None else "Pass")
        )
        if not value:
            value = "Pass"
        result[key] = {
            "enabled": enabled,
            "value": value,
            "pass": pass_through,
        }
    return result


def _as_object_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    raw = cast(Mapping[object, object], value)
    return {str(key): item for key, item in raw.items()}


def _normalize_set_name(name: object) -> str | None:
    if not isinstance(name, str):
        return None
    cleaned = name.strip()
    return cleaned or None


def empty_catalog() -> dict[str, ModificationKeys]:
    return {DEFAULT_MODKEY_SET_NAME: default_modification_keys()}


def _parse_catalog(data: object) -> dict[str, ModificationKeys]:
    root = _as_object_dict(data)
    if root is None:
        return empty_catalog()

    sets_raw = root.get("sets")
    catalog: dict[str, ModificationKeys] = {}

    if isinstance(sets_raw, list):
        for entry_obj in cast(list[object], sets_raw):
            entry_dict = _as_object_dict(entry_obj)
            if entry_dict is None:
                continue
            name = _normalize_set_name(entry_dict.get("name"))
            if not name:
                continue
            catalog[name] = coerce_modification_keys(entry_dict.get("keys"))
    elif isinstance(sets_raw, Mapping):
        # Alternate shape: {"sets": {"Name": {keys...}}}
        for raw_name, raw_keys in cast(Mapping[object, object], sets_raw).items():
            name = _normalize_set_name(raw_name)
            if not name:
                continue
            catalog[name] = coerce_modification_keys(raw_keys)

    if not catalog:
        return empty_catalog()
    return catalog


def _catalog_to_payload(catalog: Mapping[str, ModificationKeys]) -> dict[str, object]:
    ordered_names = sorted(catalog.keys(), key=lambda n: (n != DEFAULT_MODKEY_SET_NAME, n.lower()))
    return {
        "schema_version": MODKEY_SETS_SCHEMA_VERSION,
        "sets": [
            {
                "name": name,
                "keys": coerce_modification_keys(catalog[name]),
            }
            for name in ordered_names
        ],
    }


def load_modkey_sets(path: Path | None = None) -> dict[str, ModificationKeys]:
    target = Path(path) if path is not None else DEFAULT_MODKEY_SETS_PATH
    if not target.exists():
        catalog = empty_catalog()
        save_modkey_sets(catalog, target)
        return catalog
    try:
        raw: object = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"Load modkey sets failed for {target}: {exc}")
        return empty_catalog()
    catalog = _parse_catalog(raw)
    return catalog


def save_modkey_sets(
    catalog: Mapping[str, ModificationKeys], path: Path | None = None
) -> None:
    target = Path(path) if path is not None else DEFAULT_MODKEY_SETS_PATH
    payload = _catalog_to_payload(catalog)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(target)


def list_modkey_set_names(path: Path | None = None) -> list[str]:
    catalog = load_modkey_sets(path)
    return sorted(
        catalog.keys(),
        key=lambda n: (n != DEFAULT_MODKEY_SET_NAME, n.lower()),
    )


def get_modkey_set(
    name: str, path: Path | None = None
) -> ModificationKeys:
    catalog = load_modkey_sets(path)
    cleaned = _normalize_set_name(name) or DEFAULT_MODKEY_SET_NAME
    if cleaned in catalog:
        return coerce_modification_keys(catalog[cleaned])
    logger.warning(
        f"ModKey set '{cleaned}' not found; using default Pass configuration"
    )
    return default_modification_keys()


def upsert_modkey_set(
    name: str,
    keys: ModificationKeys | None = None,
    path: Path | None = None,
) -> str:
    cleaned = _normalize_set_name(name)
    if not cleaned:
        raise ValueError("Set name is required")
    catalog = load_modkey_sets(path)
    catalog[cleaned] = coerce_modification_keys(
        keys if keys is not None else catalog.get(cleaned)
    )
    save_modkey_sets(catalog, path)
    return cleaned


def copy_modkey_set(
    src_name: str,
    dst_name: str,
    path: Path | None = None,
) -> str:
    src = _normalize_set_name(src_name)
    dst = _normalize_set_name(dst_name)
    if not src or not dst:
        raise ValueError("Source and destination names are required")
    catalog = load_modkey_sets(path)
    if src not in catalog:
        raise KeyError(f"ModKey set '{src}' not found")
    if dst in catalog:
        raise FileExistsError(f"ModKey set '{dst}' already exists")
    catalog[dst] = coerce_modification_keys(catalog[src])
    save_modkey_sets(catalog, path)
    return dst


def delete_modkey_set(name: str, path: Path | None = None) -> str | None:
    """Delete a set. Returns the name that should become selected, or None if unchanged."""
    cleaned = _normalize_set_name(name)
    if not cleaned:
        return None
    catalog = load_modkey_sets(path)
    if cleaned not in catalog:
        return None
    if len(catalog) <= 1:
        raise ValueError("Cannot delete the last ModKey set")
    del catalog[cleaned]
    save_modkey_sets(catalog, path)
    if DEFAULT_MODKEY_SET_NAME in catalog:
        return DEFAULT_MODKEY_SET_NAME
    return sorted(catalog.keys(), key=str.lower)[0]


def rename_modkey_set(
    old_name: str,
    new_name: str,
    path: Path | None = None,
) -> str:
    src = _normalize_set_name(old_name)
    dst = _normalize_set_name(new_name)
    if not src or not dst:
        raise ValueError("Names are required")
    if src == dst:
        return src
    catalog = load_modkey_sets(path)
    if src not in catalog:
        raise KeyError(f"ModKey set '{src}' not found")
    if dst in catalog:
        raise FileExistsError(f"ModKey set '{dst}' already exists")
    catalog[dst] = catalog.pop(src)
    save_modkey_sets(catalog, path)
    return dst


def ensure_default_modkey_set(path: Path | None = None) -> dict[str, ModificationKeys]:
    catalog = load_modkey_sets(path)
    if not catalog:
        catalog = empty_catalog()
        save_modkey_sets(catalog, path)
    return catalog
