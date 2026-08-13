"""Deterministic per-location marker color.

Shared between the server-rendered list swatches (devices/_locate_cell.html)
and the client-side map pins (static/app.js's colorForKey) - both hash the
same "<canonic_id>:<index>" key with the same algorithm, so a location's
swatch in the table and its pin on the map always land on the same color
without the two sides needing to coordinate over the wire.
"""


def location_color(canonic_id: str, index: int) -> str:
    key = f"{canonic_id}:{index}"
    h = 0
    for ch in key:
        # Matches static/app.js's colorForKey bit for bit: JS keeps the
        # running hash as an unsigned 32-bit int via `Math.imul(...) >>> 0`
        # each step, which is exactly "mask to 32 bits" - masking here does
        # the same regardless of Python's arbitrary-precision ints.
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    hue = h % 360
    return f"hsl({hue}, 72%, 40%)"
