import base64
import io
import json
import pickle
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image

from keystroke_models import EventModel, ProfileModel


PROFILE_SCHEMA_VERSION = 1


def _json_path(profiles_dir: Path, name: str) -> Path:
    return profiles_dir / f"{name}.json"


def _pkl_path(profiles_dir: Path, name: str) -> Path:
    return profiles_dir / f"{name}.pkl"


def _img_to_png_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    # PNG is lossless (important for pixel/region matching reproducibility).
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _png_b64_to_img(data_b64: str) -> Image.Image:
    raw = base64.b64decode(data_b64.encode("ascii"))
    with Image.open(io.BytesIO(raw)) as im:
        return im.copy()


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


def event_to_dict(evt: EventModel) -> Dict[str, Any]:
    held_img = getattr(evt, "held_screenshot", None)
    held_payload = None
    if held_img is not None:
        held_payload = {"format": "png", "data_b64": _img_to_png_b64(held_img)}

    # Intentionally do NOT persist latest_screenshot.
    return {
        "event_name": getattr(evt, "event_name", None),
        "use_event": bool(getattr(evt, "use_event", True)),
        "latest_position": list(getattr(evt, "latest_position", None) or [])
        or None,
        "clicked_position": list(getattr(evt, "clicked_position", None) or [])
        or None,
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

    return EventModel(
        event_name=d.get("event_name"),
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
    )


def profile_to_dict(profile: ProfileModel) -> Dict[str, Any]:
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "profile": {
            "name": getattr(profile, "name", None),
            "favorite": bool(getattr(profile, "favorite", False)),
            "modification_keys": getattr(profile, "modification_keys", None),
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
    )
    _ensure_profile_defaults(p)
    return p


def _ensure_profile_defaults(p: ProfileModel) -> None:
    p.favorite = bool(getattr(p, "favorite", False))
    if getattr(p, "event_list", None) is None:
        p.event_list = []

    for e in p.event_list:
        if not hasattr(e, "use_event"):
            e.use_event = True
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
        if (
            not getattr(e, "held_screenshot", None)
            and getattr(e, "latest_screenshot", None)
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
    jpath = _json_path(profiles_dir, name)
    if jpath.exists():
        with open(jpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        meta = (data or {}).get("profile") or {}
        return bool(meta.get("favorite", False))

    # Avoid implicit migration when we are only listing metadata.
    p = load_profile(profiles_dir, name, migrate=False)
    return bool(getattr(p, "favorite", False))


def load_profile(profiles_dir: Path, name: str, migrate: bool = True) -> ProfileModel:
    profiles_dir.mkdir(exist_ok=True)
    jpath = _json_path(profiles_dir, name)
    if jpath.exists():
        with open(jpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return profile_from_dict(data or {})

    pkl = _pkl_path(profiles_dir, name)
    if pkl.exists():
        with open(pkl, "rb") as f:
            p = pickle.load(f)
        _ensure_profile_defaults(p)
        if migrate:
            save_profile(profiles_dir, p, name=name)
        return p

    return ProfileModel(name=name, event_list=[], favorite=False)


def save_profile(
    profiles_dir: Path, profile: ProfileModel, name: Optional[str] = None
) -> Path:
    profiles_dir.mkdir(exist_ok=True)
    prof_name = (name or getattr(profile, "name", None) or "Unnamed").strip() or "Unnamed"
    profile.name = prof_name
    _ensure_profile_defaults(profile)

    path = _json_path(profiles_dir, prof_name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile_to_dict(profile), f, ensure_ascii=False, indent=2)
    return path


def delete_profile_files(profiles_dir: Path, name: str) -> None:
    _json_path(profiles_dir, name).unlink(missing_ok=True)
    _pkl_path(profiles_dir, name).unlink(missing_ok=True)


def copy_profile(profiles_dir: Path, src_name: str, dst_name: str) -> None:
    dst_name = (dst_name or "").strip()
    if not dst_name:
        raise ValueError("dst_name is empty")
    if _json_path(profiles_dir, dst_name).exists() or _pkl_path(profiles_dir, dst_name).exists():
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
