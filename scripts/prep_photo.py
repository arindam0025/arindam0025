#!/usr/bin/env python3
"""Stage a profile photo for the local, static SVG portrait pipeline.

`--static` makes a byte-for-byte copy.  This is the mode used for the checked-in
profile image, so regenerating the portrait never changes the supplied avatar.
Without it, Pillow is used (when installed) to normalise the image to an RGBA
PNG; that is useful when preparing a new source from a camera export.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPOSITORY_ROOT / "source" / "profile-photo.png"


def parse_args() -> argparse.Namespace:
    """Parse the small, script-friendly staging interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_SOURCE,
        help="avatar image to stage (default: source/profile-photo.png)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_SOURCE,
        help="destination PNG (default: source/profile-photo.png)",
    )
    parser.add_argument(
        "--static",
        action="store_true",
        help="copy the supplied file exactly instead of normalising it",
    )
    return parser.parse_args()


def normalise_to_png(source: Path, destination: Path) -> None:
    """Save an avatar as a portable RGBA PNG, retaining all visible pixels."""
    try:
        from PIL import Image, ImageOps
    except ImportError as error:  # pragma: no cover - depends on local setup
        message = "Pillow is required unless --static is used. Install requirements-static.txt."
        raise SystemExit(message) from error

    with Image.open(source) as raw_image:
        image = ImageOps.exif_transpose(raw_image).convert("RGBA")
    image.save(destination, format="PNG", optimize=True)


def main() -> int:
    args = parse_args()
    source = args.input.expanduser().resolve()
    destination = args.output.expanduser().resolve()

    if not source.is_file():
        raise SystemExit(f"Input image does not exist: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    if source == destination:
        # Nothing needs to be copied. Avoid opening an image for writing over
        # itself, which is especially important for a lossless static source.
        print(f"Profile source is already staged: {destination}")
        return 0

    if args.static:
        shutil.copyfile(source, destination)
        print(f"Copied static profile source: {destination}")
    else:
        normalise_to_png(source, destination)
        print(f"Normalised profile source: {destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
