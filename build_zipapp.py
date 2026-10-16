#!/usr/bin/env python3
"""Build a stdlib-only, source-based standalone .pyz (no bundled interpreter)."""
import argparse
from pathlib import Path
from tools.build_pyz import build

def main():
    root = Path(__file__).resolve().parent
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, default=root / 'PyEmuera.pyz')
    a = p.parse_args()
    build(root, a.output)
    print(a.output.resolve())

if __name__=='__main__':main()
