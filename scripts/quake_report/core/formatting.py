"""Small display-format helpers."""
from __future__ import annotations


def format_km(value: float | int | str, decimals: int = 1) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.{decimals}f}".rstrip("0").rstrip(".")
