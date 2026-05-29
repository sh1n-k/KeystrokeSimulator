import base64
import io
import json
import os
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from loguru import logger
from PIL import Image

from app.core.models import EventModel, ModificationKeys, ProfileModel
from app.utils.runtime_toggle import normalize_runtime_toggle_trigger


PROFILE_SCHEMA_VERSION = 1
_PNG_B64_ATTR = "_ks_png_b64"
_PNG_IDENTITY_ATTR = "_ks_png_identity"
_PROFILE_META_CACHE: dict[Path, tuple[tuple[int, int], bool]] = {}


def _as_object_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    raw = cast(Mapping[object, object], value)
    return {str(key): item for key, item in raw.items()}


def _perf_enabled() -> bool:
    return os.getenv("KEYSIM_PROFILE_PERF") == "1"


def _log_perf(label: str, start: float) -> None:
    if _perf_enabled():
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        print(f"[perf] {label}: {elapsed_ms:.3f}ms")


def _json_path(profiles_dir: Path, name: str) -> Path:
    return profiles_dir / f"{name}.json"


def _image_identity(img: Image.Image) -> tuple[int, tuple[int, int], str]:
    return (id(img), img.size, img.mode)


def _cache_png_b64(img: Image.Image, data_b64: str) -> None:
    setattr(img, _PNG_B64_ATTR, data_b64)
    setattr(img, _PNG_IDENTITY_ATTR, _image_identity(img))


def _get_cached_png_b64(img: Image.Image) -> str | None:
    cached_b64 = getattr(img, _PNG_B64_ATTR, None)
    cached_identity = getattr(img, _PNG_IDENTITY_ATTR, None)
    if cached_b64 and cached_identity == _image_identity(img):
        return cached_b64
    return None


def _profile_file_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _load_json_meta_favorite(path: Path) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_data: object = json.load(f)
    except Exception as exc:
        logger.warning(f"Profile metadata load failed for {path}: {exc}")
        return False
    if not isinstance(raw_data, dict):
        logger.warning(
            f"Profile metadata ignored for {path}: expected object, got {type(raw_data).__name__}"
        )
        return False
    data = _as_object_dict(cast(object, raw_data))
    if data is None:
        return False
    raw_meta: object = data.get("profile") or {}
    meta = _as_object_dict(raw_meta)
    if meta is None:
        logger.warning(
            f"Profile metadata ignored for {path}: profile must be an object"
        )
        return False
    return bool(meta.get("favorite", False))


def _load_profile_meta_favorite_cached(profiles_dir: Path, name: str) -> bool:
    jpath = _json_path(profiles_dir, name)
    if jpath.exists():
        signature = _profile_file_signature(jpath)
        cached = _PROFILE_META_CACHE.get(jpath)
        if cached and cached[0] == signature:
            return cached[1]

        favorite = _load_json_meta_favorite(jpath)
        if signature is not None:
            _PROFILE_META_CACHE[jpath] = (signature, favorite)
        return favorite
    return False


def _img_to_png_b64(img: Image.Image) -> str:
    if cached := _get_cached_png_b64(img):
        return cached

    buf = io.BytesIO()
    # PNG is lossless (important for pixel/region matching reproducibility).
    img.save(buf, format="PNG")
    data_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    _cache_png_b64(img, data_b64)
    return data_b64


def _png_b64_to_img(data_b64: str) -> Image.Image:
    raw = base64.b64decode(data_b64.encode("ascii"))
    with Image.open(io.BytesIO(raw)) as im:
        img = im.copy()
    _cache_png_b64(img, data_b64)
    return img


def _to_xy(v: object) -> tuple[int, int] | None:
    if v is None:
        return None
    if isinstance(v, Sequence) and not isinstance(v, (str, bytes, bytearray)):
        seq = cast(Sequence[object], v)
        if len(seq) < 2:
            return None
        x = seq[0]
        y = seq[1]
        if not isinstance(x, (int, float, str)) or not isinstance(y, (int, float, str)):
            return None
        try:
            return (int(x), int(y))
        except (TypeError, ValueError, OverflowError):
            return None
    return None


def _to_rgba(v: object) -> tuple[int, ...] | None:
    if v is None:
        return None
    if isinstance(v, Sequence) and not isinstance(v, (str, bytes, bytearray)):
        seq = cast(Sequence[object], v)
        if len(seq) < 3:
            return None
        values: list[int] = []
        for item in seq:
            if not isinstance(item, (int, float, str)):
                return None
            try:
                values.append(int(item))
            except (TypeError, ValueError, OverflowError):
                return None
        return tuple(values)
    return None


def _to_int(v: object, default: int = 0) -> int:
    if isinstance(v, bool):
        return default
    if not isinstance(v, (int, float, str)):
        return default
    try:
        return int(v)
    except (TypeError, ValueError, OverflowError):
        return default


def _to_float_or_none(v: object) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if not isinstance(v, (int, float, str)):
        return None
    try:
        return float(v)
    except (TypeError, ValueError, OverflowError):
        return None


def _to_str_or_none(v: object) -> str | None:
    if v is None:
        return None
    return str(v)


def _to_conditions(v: object) -> dict[str, bool]:
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise ValueError("conditions must be an object")
    raw_conditions = cast(Mapping[object, object], v)
    conditions: dict[str, bool] = {}
    for key, value in raw_conditions.items():
        if not isinstance(value, bool):
            raise ValueError(f"condition '{key}' must be a boolean")
        conditions[str(key)] = value
    return conditions


def _normalized_event_name(name: object) -> str:
    return str(name or "").strip()


def _next_available_event_name(base_name: str, used_names: set[str]) -> str:
    candidate = base_name
    suffix = 2
    while candidate in used_names:
        candidate = f"{base_name} ({suffix})"
        suffix += 1
    return candidate


def _normalize_loaded_event_names(profile: ProfileModel) -> bool:
    events = list(getattr(profile, "event_list", []) or [])
    if not events:
        return False

    raw_names = [
        _normalized_event_name(getattr(evt, "event_name", None)) for evt in events
    ]
    duplicates = {
        name
        for name, count in Counter(name for name in raw_names if name).items()
        if count > 1
    }

    used_names: set[str] = set()
    changed = False
    for index, evt in enumerate(events, start=1):
        current_name = _normalized_event_name(getattr(evt, "event_name", None))
        base_name = current_name or f"Event {index}"
        if current_name in duplicates or not current_name:
            final_name = _next_available_event_name(base_name, used_names)
        else:
            final_name = base_name

        if getattr(evt, "event_name", None) != final_name:
            evt.event_name = final_name
            changed = True
        used_names.add(final_name)

    return changed


def event_to_dict(evt: EventModel) -> dict[str, object]:
    held_img = evt.held_screenshot
    held_payload: dict[str, str] | None = None
    if held_img is not None:
        held_payload = {"format": "png", "data_b64": _img_to_png_b64(held_img)}

    # Intentionally do NOT persist latest_screenshot.
    return {
        "event_name": evt.event_name,
        "use_event": bool(evt.use_event),
        "capture_size": list(evt.capture_size or (100, 100)),
        "latest_position": list(evt.latest_position or []) or None,
        "clicked_position": list(evt.clicked_position or []) or None,
        "ref_pixel_value": list(evt.ref_pixel_value or []) or None,
        "key_to_enter": evt.key_to_enter,
        "press_duration_ms": evt.press_duration_ms,
        "randomization_ms": evt.randomization_ms,
        "independent_thread": bool(evt.independent_thread),
        "match_mode": evt.match_mode,
        "invert_match": bool(evt.invert_match),
        "region_size": list(evt.region_size or []) or None,
        "execute_action": bool(evt.execute_action),
        "group_id": evt.group_id,
        "priority": int(evt.priority or 0),
        "conditions": dict(evt.conditions or {}),
        "runtime_toggle_member": bool(evt.runtime_toggle_member),
        "held_screenshot": held_payload,
    }


def event_from_dict(d: Mapping[str, object]) -> EventModel:
    held_payload = d.get("held_screenshot")
    held_img = None
    if isinstance(held_payload, dict):
        payload = cast(dict[str, object], held_payload)
        data_b64 = payload.get("data_b64")
        fmt_raw = payload.get("format")
        fmt = fmt_raw.lower() if isinstance(fmt_raw, str) else "png"
        if fmt != "png":
            raise ValueError(f"Unsupported image format: {fmt}")
        if isinstance(data_b64, str) and data_b64:
            held_img = _png_b64_to_img(data_b64)

    latest_pos = _to_xy(d.get("latest_position"))
    clicked_pos = _to_xy(d.get("clicked_position"))
    ref_pixel = _to_rgba(d.get("ref_pixel_value"))
    region_size = _to_xy(d.get("region_size"))
    capture_size = _to_xy(d.get("capture_size")) or (100, 100)

    return EventModel(
        event_name=_to_str_or_none(d.get("event_name")),
        capture_size=capture_size,
        latest_position=latest_pos,
        clicked_position=clicked_pos,
        latest_screenshot=None,  # removed from persisted format
        held_screenshot=held_img,
        ref_pixel_value=ref_pixel,
        key_to_enter=_to_str_or_none(d.get("key_to_enter")),
        press_duration_ms=_to_float_or_none(d.get("press_duration_ms")),
        randomization_ms=_to_float_or_none(d.get("randomization_ms")),
        independent_thread=bool(d.get("independent_thread", False)),
        use_event=bool(d.get("use_event", True)),
        match_mode=str(d.get("match_mode", "pixel") or "pixel"),
        invert_match=bool(d.get("invert_match", False)),
        region_size=region_size,
        execute_action=bool(d.get("execute_action", True)),
        group_id=_to_str_or_none(d.get("group_id")),
        priority=_to_int(d.get("priority", 0), default=0),
        conditions=_to_conditions(d.get("conditions")),
        runtime_toggle_member=bool(d.get("runtime_toggle_member", False)),
    )


def profile_to_dict(profile: ProfileModel) -> dict[str, object]:
    raw_runtime_toggle_key = profile.runtime_toggle_key
    normalized_runtime_toggle_key = normalize_runtime_toggle_trigger(
        raw_runtime_toggle_key
    )
    runtime_toggle_key = normalized_runtime_toggle_key or (
        str(raw_runtime_toggle_key).strip() if raw_runtime_toggle_key else None
    )
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "profile": {
            "name": profile.name,
            "favorite": bool(profile.favorite),
            "modification_keys": profile.modification_keys,
            "runtime_toggle_enabled": bool(profile.runtime_toggle_enabled),
            "runtime_toggle_key": runtime_toggle_key,
        },
        "events": [event_to_dict(e) for e in (profile.event_list or [])],
    }


def profile_from_dict(d: Mapping[str, object]) -> ProfileModel:
    if not isinstance(d, dict):
        raise ValueError(f"Profile root must be an object, got {type(d).__name__}")
    ignored_invalid_data = False
    raw_meta: object = d.get("profile") or {}
    meta = _as_object_dict(raw_meta)
    if meta is None:
        logger.warning("Ignoring invalid profile metadata: profile must be an object")
        meta = {}
        ignored_invalid_data = True
    events_raw: object = d.get("events") or []
    if not isinstance(events_raw, list):
        logger.warning("Ignoring invalid profile events: events must be a list")
        events_raw = []
        ignored_invalid_data = True
    events: list[EventModel] = []
    for index, event_data in enumerate(cast(list[object], events_raw), start=1):
        event_dict = _as_object_dict(event_data)
        if event_dict is None:
            logger.warning(f"Ignoring invalid event #{index}: event must be an object")
            ignored_invalid_data = True
            continue
        try:
            events.append(event_from_dict(event_dict))
        except Exception as exc:
            logger.warning(f"Ignoring invalid event #{index}: {exc}")
            ignored_invalid_data = True
    modification_keys = meta.get("modification_keys")
    if modification_keys is not None and not isinstance(modification_keys, dict):
        logger.warning(
            "Ignoring invalid profile metadata: modification_keys must be an object"
        )
        modification_keys = None
        ignored_invalid_data = True
    p = ProfileModel(
        name=_to_str_or_none(meta.get("name")),
        event_list=events,
        modification_keys=cast(ModificationKeys | None, modification_keys),
        favorite=bool(meta.get("favorite", False)),
        runtime_toggle_enabled=bool(meta.get("runtime_toggle_enabled", False)),
        runtime_toggle_key=_to_str_or_none(meta.get("runtime_toggle_key")),
    )
    p.load_ignored_invalid_data = ignored_invalid_data
    _ensure_profile_defaults(p)
    return p


def _ensure_profile_defaults(p: ProfileModel) -> None:
    p.favorite = bool(p.favorite)
    p.runtime_toggle_enabled = bool(p.runtime_toggle_enabled)
    runtime_toggle_key = p.runtime_toggle_key
    normalized_toggle_key = normalize_runtime_toggle_trigger(runtime_toggle_key)
    if normalized_toggle_key:
        p.runtime_toggle_key = normalized_toggle_key
    else:
        p.runtime_toggle_key = (
            str(runtime_toggle_key).strip() if runtime_toggle_key else None
        )

    # Ensure modification_keys default: all keys enabled with Pass mode
    if not getattr(p, "modification_keys", None):
        p.modification_keys = {
            "alt": {"enabled": True, "value": "Pass", "pass": True},
            "ctrl": {"enabled": True, "value": "Pass", "pass": True},
            "shift": {"enabled": True, "value": "Pass", "pass": True},
        }

    if getattr(p, "event_list", None) is None:
        p.event_list = []

    for evt in p.event_list:
        evt.runtime_toggle_member = bool(evt.runtime_toggle_member)

    for e in p.event_list:
        e.use_event = bool(e.use_event)
        if not e.capture_size:
            e.capture_size = (100, 100)
        if not e.match_mode:
            e.match_mode = "pixel"
        e.invert_match = bool(e.invert_match)
        e.execute_action = bool(e.execute_action)
        e.priority = int(e.priority or 0)
        if not e.conditions:
            e.conditions = {}
        e.independent_thread = bool(e.independent_thread)


def list_profile_names(profiles_dir: Path) -> list[str]:
    profiles_dir.mkdir(exist_ok=True)
    json_names = {p.stem for p in profiles_dir.glob("*.json")}
    names = sorted(json_names)
    if "Quick" in names:
        names.remove("Quick")
        names.insert(0, "Quick")
    return names


def ensure_quick_profile(profiles_dir: Path) -> None:
    profiles_dir.mkdir(exist_ok=True)
    if _json_path(profiles_dir, "Quick").exists():
        return
    save_profile(profiles_dir, ProfileModel(name="Quick", event_list=[]), name="Quick")


def load_profile_meta_favorite(profiles_dir: Path, name: str) -> bool:
    """Favorite lookup without constructing models or decoding images."""
    return _load_profile_meta_favorite_cached(profiles_dir, name)


def load_profile_favorites(profiles_dir: Path, names: list[str]) -> dict[str, bool]:
    return {
        name: _load_profile_meta_favorite_cached(profiles_dir, name) for name in names
    }


def load_profile(profiles_dir: Path, name: str, migrate: bool = True) -> ProfileModel:
    started = time.perf_counter()
    profiles_dir.mkdir(exist_ok=True)
    jpath = _json_path(profiles_dir, name)
    if jpath.exists():
        try:
            with open(jpath, "r", encoding="utf-8") as f:
                data: object = json.load(f)
            if data is None:
                profile = profile_from_dict({})
            elif isinstance(data, dict):
                profile = profile_from_dict(cast(dict[str, object], data))
            else:
                raise ValueError(
                    f"Profile root must be an object, got {type(data).__name__}"
                )
            if not profile.name:
                profile.name = name
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.error(f"Load profile failed for {name}: {exc}")
            profile = ProfileModel(name=name, event_list=[], favorite=False)
            _ensure_profile_defaults(profile)
            _log_perf(f"load_profile[{name}]", started)
            return profile
        changed = _normalize_loaded_event_names(profile)
        if migrate and changed and not profile.load_ignored_invalid_data:
            save_profile(profiles_dir, profile, name=name)
        elif migrate and changed:
            logger.warning(
                f"Skipped profile migration for {name}: invalid data was ignored"
            )
        _log_perf(f"load_profile[{name}]", started)
        return profile

    p = ProfileModel(name=name, event_list=[], favorite=False)
    _ensure_profile_defaults(p)
    _log_perf(f"load_profile[{name}]", started)
    return p


def save_profile(
    profiles_dir: Path, profile: ProfileModel, name: str | None = None
) -> Path:
    started = time.perf_counter()
    profiles_dir.mkdir(exist_ok=True)
    prof_name = (
        name or getattr(profile, "name", None) or "Unnamed"
    ).strip() or "Unnamed"
    profile.name = prof_name
    _ensure_profile_defaults(profile)

    path = _json_path(profiles_dir, prof_name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile_to_dict(profile), f, ensure_ascii=False, indent=2)
    signature = _profile_file_signature(path)
    if signature is not None:
        _PROFILE_META_CACHE[path] = (
            signature,
            bool(profile.favorite),
        )
    _log_perf(f"save_profile[{prof_name}]", started)
    return path


def delete_profile_files(profiles_dir: Path, name: str) -> None:
    path = _json_path(profiles_dir, name)
    path.unlink(missing_ok=True)
    _PROFILE_META_CACHE.pop(path, None)


def copy_profile(profiles_dir: Path, src_name: str, dst_name: str) -> None:
    dst_name = (dst_name or "").strip()
    if not dst_name:
        raise ValueError("dst_name is empty")
    if _json_path(profiles_dir, dst_name).exists():
        raise FileExistsError(f"'{dst_name}' exists.")
    prof = load_profile(profiles_dir, src_name, migrate=True)
    save_profile(profiles_dir, prof, name=dst_name)


def rename_profile_files(profiles_dir: Path, old_name: str, new_name: str) -> None:
    new_name = (new_name or "").strip()
    if not new_name:
        raise ValueError("new_name is empty")

    dst = _json_path(profiles_dir, new_name)
    if dst.exists():
        raise FileExistsError(f"'{new_name}' exists.")

    src_json = _json_path(profiles_dir, old_name)
    if src_json.exists():
        src_json.rename(dst)
        return

    prof = load_profile(profiles_dir, old_name, migrate=False)
    delete_profile_files(profiles_dir, old_name)
    save_profile(profiles_dir, prof, name=new_name)
