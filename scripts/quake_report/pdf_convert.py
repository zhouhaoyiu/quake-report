#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from quake_report.core.docx_builder import convert_docx_to_pdf


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("docx")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    print(convert_docx_to_pdf(args.docx, args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
