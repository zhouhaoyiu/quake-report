from __future__ import annotations

from typing import Any


def apply_place_override(shocks: list[Any], place: str | None) -> list[Any]:
    place = (place or "").strip()
    if place:
        for shock in shocks:
            shock.place = place
    return shocks
