"""Restore / validate viewport placement against connected displays."""

from __future__ import annotations


def _rects_intersect(
    ax: int,
    ay: int,
    aw: int,
    ah: int,
    bx: int,
    by: int,
    bw: int,
    bh: int,
) -> bool:
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def _get_monitors():
    try:
        from screeninfo import get_monitors

        return list(get_monitors())
    except Exception:
        return []


def viewport_restored_position_is_valid(x: int, y: int, w: int, h: int) -> bool:
    """True if the window rect intersects any currently reported monitor."""
    monitors = _get_monitors()
    if not monitors:
        return True
    for m in monitors:
        if _rects_intersect(x, y, w, h, m.x, m.y, m.width, m.height):
            return True
    return False


def centered_position_on_primary(window_w: int, window_h: int) -> tuple[int, int]:
    """Top-left position to center a window of the given size on the primary monitor."""
    monitors = _get_monitors()
    if not monitors:
        return 100, 100
    primary = None
    for m in monitors:
        if getattr(m, "is_primary", False):
            primary = m
            break
    if primary is None:
        primary = monitors[0]
    x = int(primary.x + max(0, (primary.width - window_w) // 2))
    y = int(primary.y + max(0, (primary.height - window_h) // 2))
    return x, y
