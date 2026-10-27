"""Design tokens shared by every UI: colors, spacing and icon glyphs.

Plain constants with no toolkit import, shared by the graph renderer and the
Qt UI.
"""

# ---------------------------------------------------------------------------
# Surface — background tones (paper / panel / canvas / sunken / divider)
# ---------------------------------------------------------------------------
SURFACE_PAPER = "#FAF7F2"        # main background
SURFACE_PANEL = "#F4F0E8"        # nav rail / side panel
SURFACE_SUNKEN = "#EEE9DD"       # input fields / disabled area
SURFACE_DIVIDER = "#D9D2C1"      # 1px dividers


# ---------------------------------------------------------------------------
# Ink — text / icon tones
# ---------------------------------------------------------------------------
INK_PRIMARY = "#1A1816"
INK_SECONDARY = "#4A463E"
INK_MUTED = "#8A8474"


# ---------------------------------------------------------------------------
# Signal — single accent color
# ---------------------------------------------------------------------------
SIGNAL_BASE = "#2A6B4A"
SIGNAL_HOVER = "#225A3D"


# ---------------------------------------------------------------------------
# Status — bg / fg pairs with companion icons (color + glyph + label = 3 axes)
# ---------------------------------------------------------------------------
STATUS_READY_BG = "#E6F0E4"
STATUS_READY_FG = "#1F4A2E"
STATUS_READY_ICON = "●"      # ●

STATUS_RUNNING_BG = "#FFF1D6"
STATUS_RUNNING_FG = "#7A5500"
STATUS_RUNNING_ICON = "▶"    # ▶

STATUS_WARN_BG = "#FFE9CC"
STATUS_WARN_FG = "#7A4500"
STATUS_WARN_ICON = "⚠"       # ⚠

STATUS_ERROR_BG = "#F7DAD4"
STATUS_ERROR_FG = "#7A2820"
STATUS_ERROR_ICON = "✕"      # ✕


# ---------------------------------------------------------------------------
# Semantic — condition
# ---------------------------------------------------------------------------
COND_INACTIVE_FG = "#7A2820"

# Capture box outline drawn over the game while the capture HUD is open.
# Saturated so it reads on both dark and bright game scenes.
CAPTURE_BORDER = "#FF2D55"
CAPTURE_BORDER_WIDTH = 2


# ---------------------------------------------------------------------------
# Spacing — 4px base grid (use these for margins and spacing)
# ---------------------------------------------------------------------------
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12


# ---------------------------------------------------------------------------
# Icon vocabulary — unicode glyphs that render across macOS and Windows.
# ---------------------------------------------------------------------------
# Only glyphs that carry an affordance stay; feature emoji were removed in
# favour of words and the status color dots above.
ICON_FAVORITE = "★"
ICON_SEARCH = "⌕"
ICON_TOOLS = "⚙"
ICON_START = "▶"
ICON_STOP = "■"
ICON_EXPANDED = "▾"
ICON_COLLAPSED = "▸"
ICON_REMOVE = "✕"
