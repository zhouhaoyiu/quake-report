from __future__ import annotations

import csv

import pandas as pd


def write_catalog_csv(catalog, path: str) -> None:
    df = catalog.copy()
    if "time" in df.columns:
        df = df.sort_values("time", ascending=True).reset_index(drop=True)
    for col in (
        "latitude", "longitude", "depth", "mag", "nst", "gap", "dmin", "rms",
        "horizontalError", "depthError", "magError", "magNst",
    ):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "dist_km" in df.columns:
        df["dist_km"] = pd.to_numeric(df["dist_km"], errors="coerce")
    df.to_csv(path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
