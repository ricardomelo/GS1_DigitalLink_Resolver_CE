#!/usr/bin/env python3
"""
Writes portal/gs1_dictionary.json from the GS1 Barcode Syntax Dictionary of an engine build
(Documentation/adr/0003-gs1-rules-from-the-dictionary.md).

  python portal/tools/gen_dictionary.py [engine directory] [--out FILE] [--check]

The engine directory is what tools/build-syntax-engine.sh makes (gs1-syntax-dictionary.txt and RELEASE);
default $GS1_SYNTAX_ENGINE_DIR. --check writes nothing and exits with status 1 when the file in the repository
differs from what the dictionary gives (the development tests and the weekly update check use it). The portal's
rules are then built from the file (gs1.py), which fails at import when a key or qualifier has a format the
portal cannot check yet.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import gs1dict  # noqa: E402


def generate(engine_dir: str) -> str:
    """The text of gs1_dictionary.json for the engine build in engine_dir."""
    with open(os.path.join(engine_dir, "gs1-syntax-dictionary.txt"), encoding="utf-8") as fh:
        data = gs1dict.parse(fh.read())
    with open(os.path.join(engine_dir, "RELEASE"), encoding="utf-8") as fh:
        release = fh.read().strip()
    return gs1dict.dump({"release": release, **data})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("engine_dir", nargs="?", default=os.environ.get("GS1_SYNTAX_ENGINE_DIR", ""))
    parser.add_argument("--out", default=gs1dict.PATH)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not args.engine_dir:
        parser.error("give the engine directory or set GS1_SYNTAX_ENGINE_DIR")
    text = generate(args.engine_dir)
    if args.check:
        try:
            with open(args.out, encoding="utf-8") as fh:
                same = fh.read() == text
        except OSError:
            same = False
        print(f"{args.out} is {'up to date' if same else 'NOT up to date'} with {args.engine_dir}")
        return 0 if same else 1
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
