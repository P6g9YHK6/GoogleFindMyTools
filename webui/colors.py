"""Deterministic per-device hue, per-location shade for map pins.

Shared between the server-rendered list swatches (devices/_locate_cell.html,
devices/_map_links_cell.html) and the client-side map pins
(static/app.js's hueForDevice/colorForDeviceLocation) - both hash a
device's canonic_id into one base hue with the same algorithm, then pick a
shade of it for a given location index from the same SHADE_LIGHTNESS table,
so a location's swatch in the table and its pin on the map always land on
the same color without the two sides needing to coordinate over the wire.
"""

# %, cycles past 5 simultaneous locations for one device - see
# static/app.js's identical table for why this stays a small fixed
# progression rather than an unbounded hash like the hue is.
SHADE_LIGHTNESS = [38, 48, 58, 68, 30]

# The hash below is quantized to this many evenly-spaced hues rather than
# used as a raw mod-360 value: two devices whose IDs happen to hash close
# together (e.g. 40° apart) would otherwise render as near-identical
# colors. 12 steps = 30° apart, which stays visually distinct at these
# lightness levels; devices only share a hue once there are more than 12
# of them. Matches static/app.js's identical HUE_STEPS.
HUE_STEPS = 12


def _hue_for_device(canonic_id: str) -> int:
    h = 0
    for ch in canonic_id:
        # Matches static/app.js's hueForDevice bit for bit: JS keeps the
        # running hash as an unsigned 32-bit int via `Math.imul(...) >>> 0`
        # each step, which is exactly "mask to 32 bits" - masking here does
        # the same regardless of Python's arbitrary-precision ints.
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return (h % HUE_STEPS) * (360 // HUE_STEPS)


def location_color(canonic_id: str, index: int) -> str:
    hue = _hue_for_device(canonic_id)
    lightness = SHADE_LIGHTNESS[index % len(SHADE_LIGHTNESS)]
    return f"hsl({hue}, 70%, {lightness}%)"
