from __future__ import annotations

import importlib
import sys


LEGACY_MODULE_ALIASES: dict[str, str] = {
    "i18n": "app.utils.i18n",
    "keystroke_capturer": "app.core.capturer",
    "keystroke_event_editor": "app.ui.event_editor",
    "keystroke_event_graph": "app.ui.event_graph",
    "keystroke_event_importer": "app.ui.event_importer",
    "keystroke_models": "app.core.models",
    "keystroke_modkeys": "app.ui.modkeys",
    "keystroke_processor": "app.core.processor",
    "keystroke_profile_storage": "app.storage.profile_storage",
    "keystroke_profiles": "app.ui.profiles",
    "keystroke_quick_event_editor": "app.ui.quick_event_editor",
    "keystroke_settings": "app.ui.settings",
    "keystroke_simulator_app": "app.ui.simulator_app",
    "keystroke_sounds": "app.utils.sounds",
    "keystroke_sort_events": "app.ui.sort_events",
    "keystroke_utils": "app.utils.system",
    "profile_display": "app.storage.profile_display",
    "runtime_toggle_sound_assets": "app.utils.sound_assets",
    "runtime_toggle_utils": "app.utils.runtime_toggle",
}


def remap_legacy_module_name(module_name: str) -> str:
    return LEGACY_MODULE_ALIASES.get(module_name, module_name)


def install_legacy_module_alias(alias_name: str) -> object:
    target_name = LEGACY_MODULE_ALIASES[alias_name]
    module = importlib.import_module(target_name)
    sys.modules[alias_name] = module
    return module


def legacy_module_names() -> list[str]:
    return list(LEGACY_MODULE_ALIASES)


def canonical_module_names() -> list[str]:
    return list(dict.fromkeys(LEGACY_MODULE_ALIASES.values()))
