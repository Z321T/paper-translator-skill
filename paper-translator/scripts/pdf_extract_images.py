"""Extract PDF image regions into a portable Markdown asset bundle.

Automatic extraction renders raster image blocks as PNG files. Vector or
composite figures can be preserved with repeatable ``--clip`` arguments.

Usage:
    uv run python scripts/pdf_extract_images.py paper.pdf --markdown paper_translation.md
    uv run python scripts/pdf_extract_images.py paper.pdf --markdown paper_translation.md --clip "3:45,80,550,420=figure-2"
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple, Sequence
from urllib.parse import quote

import pymupdf


class ClipSpec(NamedTuple):
    """A one-based PDF page number and crop rectangle in PDF points."""

    page: int
    bbox: tuple[float, float, float, float]
    label: str = "figure"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "figure"


def _relative_asset_path(assets_dir: Path, filename: str) -> str:
    return (Path(assets_dir.name) / filename).as_posix()


def _markdown_destination(relative_path: str) -> str:
    return quote(relative_path, safe="/._-")


def _render_clip(
    page: pymupdf.Page, bbox: Sequence[float], output: Path, dpi: int
) -> None:
    rect = pymupdf.Rect(bbox) & page.rect
    if rect.is_empty or rect.is_infinite:
        raise ValueError(f"Crop rectangle is outside page {page.number + 1}: {bbox}")
    pixmap = page.get_pixmap(dpi=dpi, clip=rect, alpha=False)
    pixmap.save(output)


def _validate_options(
    page_count: int,
    dpi: int,
    min_width: float,
    min_height: float,
    clips: Sequence[ClipSpec],
) -> None:
    if dpi <= 0:
        raise ValueError("dpi must be greater than zero")
    if not math.isfinite(min_width) or min_width < 0:
        raise ValueError("min_width must be a finite non-negative number")
    if not math.isfinite(min_height) or min_height < 0:
        raise ValueError("min_height must be a finite non-negative number")
    for clip in clips:
        if clip.page < 1 or clip.page > page_count:
            raise ValueError(
                f"Clip page {clip.page} is outside PDF page range 1-{page_count}"
            )
        if len(clip.bbox) != 4 or not all(math.isfinite(v) for v in clip.bbox):
            raise ValueError(f"Clip coordinates must be four finite numbers: {clip.bbox}")
        x0, y0, x1, y1 = clip.bbox
        if x0 >= x1 or y0 >= y1:
            raise ValueError(f"Clip rectangle must satisfy x0 < x1 and y0 < y1: {clip.bbox}")


def _remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


@contextmanager
def _staging_directory(parent: Path, prefix: str) -> Iterator[Path]:
    """Create a unique sibling directory that inherits parent permissions.

    ``tempfile.TemporaryDirectory`` deliberately creates private directories.
    On Windows that also protects the DACL from inheritance, which can make a
    renamed output directory unreadable to desktop applications running as the
    interactive user. Generated assets are user-facing output, so create the
    staging directory with normal directory semantics and clean it up here.
    """
    while True:
        staging_dir = parent / f"{prefix}{uuid.uuid4().hex}"
        try:
            staging_dir.mkdir()
        except FileExistsError:
            continue
        break

    try:
        yield staging_dir
    finally:
        _remove_path(staging_dir)


def _replace_directory(staging_dir: Path, assets_dir: Path) -> None:
    """Replace an asset directory while allowing rollback on commit failure."""
    backup_dir: Path | None = None
    if assets_dir.exists():
        backup_dir = assets_dir.with_name(
            f".{assets_dir.name}.backup-{uuid.uuid4().hex}"
        )
        assets_dir.replace(backup_dir)
    try:
        staging_dir.replace(assets_dir)
    except Exception:
        if backup_dir is not None and backup_dir.exists() and not assets_dir.exists():
            backup_dir.replace(assets_dir)
        raise
    if backup_dir is not None:
        _remove_path(backup_dir)


def extract_pdf_images(
    pdf_path: str | Path,
    markdown_path: str | Path,
    *,
    dpi: int = 200,
    min_width: float = 40,
    min_height: float = 40,
    clips: Sequence[ClipSpec] = (),
) -> dict:
    """Extract image blocks and requested page crops beside a Markdown file.

    The asset directory is named ``<markdown-stem>_assets``. All paths stored
    in the manifest use POSIX separators and are relative to the Markdown
    document, so the Markdown file and asset directory can be moved together.
    """
    pdf_path = Path(pdf_path)
    markdown_path = Path(markdown_path)
    assets_dir = markdown_path.parent / f"{markdown_path.stem}_assets"

    images: list[dict] = []
    with pymupdf.open(pdf_path) as document:
        _validate_options(len(document), dpi, min_width, min_height, clips)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        with _staging_directory(
            markdown_path.parent, f".{assets_dir.name}-staging-"
        ) as staging_dir:
            for page_index, page in enumerate(document):
                image_number = 0
                for block in page.get_text("dict").get("blocks", []):
                    if block.get("type") != 1:
                        continue
                    bbox = tuple(float(value) for value in block["bbox"])
                    width = bbox[2] - bbox[0]
                    height = bbox[3] - bbox[1]
                    if width < min_width or height < min_height:
                        continue
                    image_number += 1
                    filename = (
                        f"page-{page_index + 1:03d}-image-{image_number:02d}.png"
                    )
                    _render_clip(page, bbox, staging_dir / filename, dpi)
                    relative_path = _relative_asset_path(assets_dir, filename)
                    images.append(
                        {
                            "id": f"p{page_index + 1}-image-{image_number}",
                            "page": page_index + 1,
                            "kind": "embedded",
                            "bbox": [round(value, 2) for value in bbox],
                            "file": relative_path,
                            "markdown": (
                                f"![Image from PDF page {page_index + 1}]"
                                f"({_markdown_destination(relative_path)})"
                            ),
                        }
                    )

            for clip_number, clip in enumerate(clips, start=1):
                page = document[clip.page - 1]
                filename = (
                    f"page-{clip.page:03d}-clip-{clip_number:02d}-"
                    f"{_slugify(clip.label)}.png"
                )
                _render_clip(page, clip.bbox, staging_dir / filename, dpi)
                relative_path = _relative_asset_path(assets_dir, filename)
                images.append(
                    {
                        "id": f"p{clip.page}-clip-{clip_number}",
                        "page": clip.page,
                        "kind": "clip",
                        "bbox": [round(value, 2) for value in clip.bbox],
                        "file": relative_path,
                        "markdown": (
                            f"![Figure from PDF page {clip.page}]"
                            f"({_markdown_destination(relative_path)})"
                        ),
                    }
                )

            manifest = {
                "version": 1,
                "source_pdf": pdf_path.name,
                "markdown": markdown_path.name,
                "assets_dir": assets_dir.name,
                "images": images,
            }
            (staging_dir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            _replace_directory(staging_dir, assets_dir)
    return manifest


def _parse_clip(value: str) -> ClipSpec:
    try:
        page_text, remainder = value.split(":", 1)
        coordinates, separator, label = remainder.partition("=")
        bbox = tuple(float(item) for item in coordinates.split(","))
        if len(bbox) != 4:
            raise ValueError
        return ClipSpec(int(page_text), bbox, label if separator else "figure")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "clip must be PAGE:X0,Y0,X1,Y1 or PAGE:X0,Y0,X1,Y1=LABEL"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="source PDF file")
    parser.add_argument(
        "--markdown",
        type=Path,
        default=Path("paper_translation.md"),
        help="target Markdown path; determines the adjacent asset directory",
    )
    parser.add_argument("--dpi", type=int, default=200, help="PNG render DPI")
    parser.add_argument("--min-width", type=float, default=40)
    parser.add_argument("--min-height", type=float, default=40)
    parser.add_argument(
        "--clip",
        action="append",
        type=_parse_clip,
        default=[],
        metavar="PAGE:X0,Y0,X1,Y1=LABEL",
        help="render a vector/composite figure region; may be repeated",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        manifest = extract_pdf_images(
            args.pdf,
            args.markdown,
            dpi=args.dpi,
            min_width=args.min_width,
            min_height=args.min_height,
            clips=args.clip,
        )
    except (ValueError, OSError, pymupdf.FileDataError) as exc:
        parser.error(str(exc))
    print(
        f"Extracted {len(manifest['images'])} image(s) to "
        f"{manifest['assets_dir']}/manifest.json"
    )


if __name__ == "__main__":
    main()
