import base64
import io
import json
import os
import pickle
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image

from keystroke_models import EventModel, ProfileModel
from runtime_toggle_utils import normalize_runtime_toggle_trigger


PROFILE_SCHEMA_VERSION = 1
_PNG_B64_ATTR = "_ks_png_b64"
_PNG_IDENTITY_ATTR = "_ks_png_identity"
_PROFILE_META_CACHE: Dict[Path, tuple[tuple[int, int], bool]] = {}


def _perf_enabled() -> bool:
    return os.getenv("KEYSIM_PROFILE_PERF") == "1"


def _log_perf(label: str, start: float) -> None:
    if _perf_enabled():
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        print(f"[perf] {label}: {elapsed_ms:.3f}ms")


def _json_path(profiles_dir: Path, name: str) -> Path:
    return profiles_dir / f"{name}.json"


def _pkl_path(profiles_dir: Path, name: str) -> Path:
    return profiles_dir / f"{name}.pkl"


def _image_identity(img: Image.Image) -> tuple[int, tuple[int, int], str]:
    return (id(img), img.size, img.mode)


def _cache_png_b64(img: Image.Image, data_b64: str) -> None:
    setattr(img, _PNG_B64_ATTR, data_b64)
    setattr(img, _PNG_IDENTITY_ATTR, _image_identity(img))


def _get_cached_png_b64(img: Image.Image) -> Optional[str]:
    cached_b64 = getattr(img, _PNG_B64_ATTR, None)
    cached_identity = getattr(img, _PNG_IDENTITY_ATTR, None)
    if cached_b64 and cached_identity == _image_identity(img):
        return cached_b64
    return None


def _profile_file_signature(path: Path) -> Optional[tuple[int, int]]:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _load_json_meta_favorite(path: Path) -> bool:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    meta = (data or {}).get("profile") or {}
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

    pkl_path = _pkl_path(profiles_dir, name)
    signature = _profile_file_signature(pkl_path)
    cached = _PROFILE_META_CACHE.get(pkl_path)
    if cached and cached[0] == signature:
        return cached[1]

    profile = load_profile(profiles_dir, name, migrate=False)
    favorite = bool(getattr(profile, "favorite", False))
    if signature is not None:
        _PROFILE_META_CACHE[pkl_path] = (signature, favorite)
    return favorite


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


def _to_xy(v: Any) -> Optional[tuple[int, int]]:
    if v is None:
        return None
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        return (int(v[0]), int(v[1]))
    return None


def _to_rgba(v: Any) -> Optional[tuple[int, ...]]:
    if v is None:
        return None
    if isinstance(v, (list, tuple)) and len(v) >= 3:
        return tuple(int(x) for x in v)
    return None


def _normalized_event_name(name: Any) -> str:
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


def event_to_dict(evt: EventModel) -> Dict[str, Any]:
    held_img = getattr(evt, "held_screenshot", None)
    held_payload = None
    if held_img is not None:
        held_payload = {"format": "png", "data_b64": _img_to_png_b64(held_img)}

    # Intentionally do NOT persist latest_screenshot.
    return {
        "event_name": getattr(evt, "event_name", None),
        "use_event": bool(getattr(evt, "use_event", True)),
        "capture_size": list(getattr(evt, "capture_size", (100, 100)) or [100, 100]),
        "latest_position": list(getattr(evt, "latest_position", None) or []) or None,
        "clicked_position": list(getattr(evt, "clicked_position", None) or []) or None,
        "ref_pixel_value": list(getattr(evt, "ref_pixel_value", None) or []) or None,
        "key_to_enter": getattr(evt, "key_to_enter", None),
        "press_duration_ms": getattr(evt, "press_duration_ms", None),
        "randomization_ms": getattr(evt, "randomization_ms", None),
        "independent_thread": bool(getattr(evt, "independent_thread", False)),
        "match_mode": getattr(evt, "match_mode", "pixel"),
        "invert_match": bool(getattr(evt, "invert_match", False)),
        "region_size": list(getattr(evt, "region_size", None) or []) or None,
        "execute_action": bool(getattr(evt, "execute_action", True)),
        "group_id": getattr(evt, "group_id", None),
        "priority": int(getattr(evt, "priority", 0) or 0),
        "conditions": dict(getattr(evt, "conditions", {}) or {}),
        "runtime_toggle_member": bool(getattr(evt, "runtime_toggle_member", False)),
        "held_screenshot": held_payload,
    }


def event_from_dict(d: Dict[str, Any]) -> EventModel:
    held_payload = d.get("held_screenshot") or None
    held_img = None
    if isinstance(held_payload, dict) and held_payload.get("data_b64"):
        fmt = (held_payload.get("format") or "png").lower()
        if fmt != "png":
            raise ValueError(f"Unsupported image format: {fmt}")
        held_img = _png_b64_to_img(held_payload["data_b64"])

    latest_pos = _to_xy(d.get("latest_position"))
    clicked_pos = _to_xy(d.get("clicked_position"))
    ref_pixel = _to_rgba(d.get("ref_pixel_value"))
    region_size = _to_xy(d.get("region_size"))
    capture_size = _to_xy(d.get("capture_size")) or (100, 100)

    return EventModel(
        event_name=d.get("event_name"),
        capture_size=capture_size,
        latest_position=latest_pos,
        clicked_position=clicked_pos,
        latest_screenshot=None,  # removed from persisted format
        held_screenshot=held_img,
        ref_pixel_value=ref_pixel,
        key_to_enter=d.get("key_to_enter"),
        press_duration_ms=d.get("press_duration_ms"),
        randomization_ms=d.get("randomization_ms"),
        independent_thread=bool(d.get("independent_thread", False)),
        use_event=bool(d.get("use_event", True)),
        match_mode=d.get("match_mode", "pixel"),
        invert_match=bool(d.get("invert_match", False)),
        region_size=region_size,
        execute_action=bool(d.get("execute_action", True)),
        group_id=d.get("group_id"),
        priority=int(d.get("priority", 0) or 0),
        conditions=dict(d.get("conditions") or {}),
        runtime_toggle_member=bool(d.get("runtime_toggle_member", False)),
    )


def profile_to_dict(profile: ProfileModel) -> Dict[str, Any]:
    raw_runtime_toggle_key = getattr(profile, "runtime_toggle_key", None)
    normalized_runtime_toggle_key = normalize_runtime_toggle_trigger(
        raw_runtime_toggle_key
    )
    runtime_toggle_key = normalized_runtime_toggle_key or (
        str(raw_runtime_toggle_key).strip() if raw_runtime_toggle_key else None
    )
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "profile": {
            "name": getattr(profile, "name", None),
            "favorite": bool(getattr(profile, "favorite", False)),
            "modification_keys": getattr(profile, "modification_keys", None),
            "runtime_toggle_enabled": bool(
                getattr(profile, "runtime_toggle_enabled", False)
            ),
            "runtime_toggle_key": runtime_toggle_key,
        },
        "events": [event_to_dict(e) for e in (profile.event_list or [])],
    }


def profile_from_dict(d: Dict[str, Any]) -> ProfileModel:
    meta = d.get("profile") or {}
    events_raw = d.get("events") or []
    events = [event_from_dict(e) for e in events_raw if isinstance(e, dict)]
    p = ProfileModel(
        name=meta.get("name"),
        event_list=events,
        modification_keys=meta.get("modification_keys"),
        favorite=bool(meta.get("favorite", False)),
        runtime_toggle_enabled=bool(meta.get("runtime_toggle_enabled", False)),
        runtime_toggle_key=meta.get("runtime_toggle_key"),
    )
    _ensure_profile_defaults(p)
    return p


def _ensure_profile_defaults(p: ProfileModel) -> None:
    p.favorite = bool(getattr(p, "favorite", False))
    p.runtime_toggle_enabled = bool(getattr(p, "runtime_toggle_enabled", False))
    runtime_toggle_key = getattr(p, "runtime_toggle_key", None)
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
        evt.runtime_toggle_member = bool(getattr(evt, "runtime_toggle_member", False))

    for e in p.event_list:
        if not hasattr(e, "use_event"):
            e.use_event = True
        if not hasattr(e, "capture_size") or not getattr(e, "capture_size", None):
            e.capture_size = (100, 100)
        if not hasattr(e, "match_mode"):
            e.match_mode = "pixel"
        if not hasattr(e, "invert_match"):
            e.invert_match = False
        if not hasattr(e, "region_size"):
            e.region_size = None
        if not hasattr(e, "execute_action"):
            e.execute_action = True
        if not hasattr(e, "group_id"):
            e.group_id = None
        if not hasattr(e, "priority"):
            e.priority = 0
        if not hasattr(e, "conditions"):
            e.conditions = {}
        if not hasattr(e, "independent_thread"):
            e.independent_thread = False

        # Legacy fallback: if only latest_screenshot exists, promote it to held_screenshot.
        if not getattr(e, "held_screenshot", None) and getattr(
            e, "latest_screenshot", None
        ):
            e.held_screenshot = e.latest_screenshot


def list_profile_names(profiles_dir: Path) -> list[str]:
    profiles_dir.mkdir(exist_ok=True)
    json_names = {p.stem for p in profiles_dir.glob("*.json")}
    pkl_names = {p.stem for p in profiles_dir.glob("*.pkl")}
    names = sorted(json_names | pkl_names)
    if "Quick" in names:
        names.remove("Quick")
        names.insert(0, "Quick")
    return names


def ensure_quick_profile(profiles_dir: Path) -> None:
    profiles_dir.mkdir(exist_ok=True)
    if _json_path(profiles_dir, "Quick").exists():
        return
    if _pkl_path(profiles_dir, "Quick").exists():
        load_profile(profiles_dir, "Quick", migrate=True)
        return
    save_profile(profiles_dir, ProfileModel(name="Quick", event_list=[]), name="Quick")


def load_profile_meta_favorite(profiles_dir: Path, name: str) -> bool:
    """
    Favorite lookup without constructing models or decoding images.
    Falls back to legacy pickle if JSON doesn't exist yet.
    """
    return _load_profile_meta_favorite_cached(profiles_dir, name)


def load_profile_favorites(profiles_dir: Path, names: list[str]) -> Dict[str, bool]:
    return {
        name: _load_profile_meta_favorite_cached(profiles_dir, name) for name in names
    }


def load_profile(profiles_dir: Path, name: str, migrate: bool = True) -> ProfileModel:
    started = time.perf_counter()
    profiles_dir.mkdir(exist_ok=True)
    jpath = _json_path(profiles_dir, name)
    if jpath.exists():
        with open(jpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        profile = profile_from_dict(data or {})
        changed = _normalize_loaded_event_names(profile)
        if migrate and changed:
            save_profile(profiles_dir, profile, name=name)
        _log_perf(f"load_profile[{name}]", started)
        return profile

    pkl = _pkl_path(profiles_dir, name)
    if pkl.exists():
        with open(pkl, "rb") as f:
            p = pickle.load(f)
        _ensure_profile_defaults(p)
        changed = _normalize_loaded_event_names(p)
        if migrate:
            save_profile(profiles_dir, p, name=name)
        _log_perf(f"load_profile[{name}]", started)
        return p

    p = ProfileModel(name=name, event_list=[], favorite=False)
    _ensure_profile_defaults(p)
    _log_perf(f"load_profile[{name}]", started)
    return p


def save_profile(
    profiles_dir: Path, profile: ProfileModel, name: Optional[str] = None
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
            bool(getattr(profile, "favorite", False)),
        )
    _log_perf(f"save_profile[{prof_name}]", started)
    return path


def delete_profile_files(profiles_dir: Path, name: str) -> None:
    _json_path(profiles_dir, name).unlink(missing_ok=True)
    _pkl_path(profiles_dir, name).unlink(missing_ok=True)


def copy_profile(profiles_dir: Path, src_name: str, dst_name: str) -> None:
    dst_name = (dst_name or "").strip()
    if not dst_name:
        raise ValueError("dst_name is empty")
    if (
        _json_path(profiles_dir, dst_name).exists()
        or _pkl_path(profiles_dir, dst_name).exists()
    ):
        raise FileExistsError(f"'{dst_name}' exists.")
    prof = load_profile(profiles_dir, src_name, migrate=True)
    save_profile(profiles_dir, prof, name=dst_name)


def rename_profile_files(profiles_dir: Path, old_name: str, new_name: str) -> None:
    new_name = (new_name or "").strip()
    if not new_name:
        raise ValueError("new_name is empty")

    dst = _json_path(profiles_dir, new_name)
    if dst.exists() or _pkl_path(profiles_dir, new_name).exists():
        raise FileExistsError(f"'{new_name}' exists.")

    src_json = _json_path(profiles_dir, old_name)
    if src_json.exists():
        src_json.rename(dst)
        _pkl_path(profiles_dir, old_name).unlink(missing_ok=True)
        return

    prof = load_profile(profiles_dir, old_name, migrate=False)
    delete_profile_files(profiles_dir, old_name)
    save_profile(profiles_dir, prof, name=new_name)
