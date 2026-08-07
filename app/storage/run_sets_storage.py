"""Named run-set catalog: which profiles run together at Start."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from loguru import logger

RUN_SETS_SCHEMA_VERSION = 1
DEFAULT_RUN_SETS_PATH = Path("run_sets.json")
# Virtual selection: follow the main profile combobox (not stored in catalog).
CURRENT_RUN_SET_ID = "__current__"


def is_current_run_set(set_id: object) -> bool:
    return isinstance(set_id, str) and set_id.strip() == CURRENT_RUN_SET_ID


def _normalize_set_name(name: object) -> str | None:
    if not isinstance(name, str):
        return None
    cleaned = name.strip()
    if not cleaned or cleaned == CURRENT_RUN_SET_ID:
        return None
    return cleaned


def _normalize_profile_list(raw: object) -> list[str]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in cast(Sequence[object], raw):
        if not isinstance(item, str):
            continue
        name = item.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def empty_catalog() -> dict[str, list[str]]:
    return {}


def _as_object_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    raw = cast(Mapping[object, object], value)
    return {str(key): item for key, item in raw.items()}


def _parse_catalog(data: object) -> dict[str, list[str]]:
    root = _as_object_dict(data)
    if root is None:
        return empty_catalog()
    catalog: dict[str, list[str]] = {}
    sets_raw = root.get("sets")
    if isinstance(sets_raw, list):
        for entry_obj in cast(list[object], sets_raw):
            entry = _as_object_dict(entry_obj)
            if entry is None:
                continue
            name = _normalize_set_name(entry.get("name"))
            if not name:
                continue
            profiles = _normalize_profile_list(entry.get("profiles"))
            if not profiles:
                continue
            catalog[name] = profiles
    elif isinstance(sets_raw, Mapping):
        for raw_name, raw_profiles in cast(Mapping[object, object], sets_raw).items():
            name = _normalize_set_name(raw_name)
            if not name:
                continue
            profiles = _normalize_profile_list(raw_profiles)
            if not profiles:
                continue
            catalog[name] = profiles
    return catalog


def _catalog_to_payload(catalog: Mapping[str, list[str]]) -> dict[str, object]:
    ordered = sorted(catalog.keys(), key=lambda n: n.lower())
    return {
        "schema_version": RUN_SETS_SCHEMA_VERSION,
        "sets": [
            {"name": name, "profiles": list(catalog[name])} for name in ordered
        ],
    }


def load_run_sets(path: Path | None = None) -> dict[str, list[str]]:
    target = Path(path) if path is not None else DEFAULT_RUN_SETS_PATH
    if not target.exists():
        return empty_catalog()
    try:
        data: object = json.loads(target.read_text(encoding="utf-8"))
        return _parse_catalog(data)
    except Exception as exc:
        logger.warning(f"Load run sets failed for {target}: {exc}")
        return empty_catalog()


def save_run_sets(
    catalog: Mapping[str, list[str]], path: Path | None = None
) -> None:
    target = Path(path) if path is not None else DEFAULT_RUN_SETS_PATH
    payload = _catalog_to_payload(catalog)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tmp.replace(target)


def list_run_set_names(path: Path | None = None) -> list[str]:
    catalog = load_run_sets(path)
    return sorted(catalog.keys(), key=lambda n: n.lower())


def get_run_set(name: str, path: Path | None = None) -> list[str]:
    cleaned = _normalize_set_name(name)
    if not cleaned:
        return []
    catalog = load_run_sets(path)
    return list(catalog.get(cleaned, []))


def upsert_run_set(
    name: str, profiles: list[str], path: Path | None = None
) -> str:
    cleaned = _normalize_set_name(name)
    if not cleaned:
        raise ValueError("Run set name is required")
    members = _normalize_profile_list(profiles)
    if not members:
        raise ValueError("Run set needs at least one profile")
    catalog = load_run_sets(path)
    catalog[cleaned] = members
    save_run_sets(catalog, path)
    return cleaned


def copy_run_set(src: str, dst: str, path: Path | None = None) -> str:
    src_name = _normalize_set_name(src)
    dst_name = _normalize_set_name(dst)
    if not src_name or not dst_name:
        raise ValueError("Run set name is required")
    catalog = load_run_sets(path)
    if src_name not in catalog:
        raise KeyError(f"Run set '{src_name}' not found")
    if dst_name in catalog:
        raise FileExistsError(f"Run set '{dst_name}' already exists")
    catalog[dst_name] = list(catalog[src_name])
    save_run_sets(catalog, path)
    return dst_name


def delete_run_set(name: str, path: Path | None = None) -> str | None:
    cleaned = _normalize_set_name(name)
    if not cleaned:
        return None
    catalog = load_run_sets(path)
    if cleaned not in catalog:
        return None
    del catalog[cleaned]
    save_run_sets(catalog, path)
    remaining = sorted(catalog.keys(), key=lambda n: n.lower())
    return remaining[0] if remaining else CURRENT_RUN_SET_ID


def rename_run_set(src: str, dst: str, path: Path | None = None) -> str:
    src_name = _normalize_set_name(src)
    dst_name = _normalize_set_name(dst)
    if not src_name or not dst_name:
        raise ValueError("Run set name is required")
    catalog = load_run_sets(path)
    if src_name not in catalog:
        raise KeyError(f"Run set '{src_name}' not found")
    if dst_name != src_name and dst_name in catalog:
        raise FileExistsError(f"Run set '{dst_name}' already exists")
    profiles = catalog.pop(src_name)
    catalog[dst_name] = profiles
    save_run_sets(catalog, path)
    return dst_name
