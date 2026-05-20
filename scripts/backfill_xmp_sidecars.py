"""Backfill XMP sidecars for already-organized images.

Reads Lightroom-style sidecars from source paths, converts metadata to a
minimal Darktable-compatible XMP, and writes them alongside each organized
image using Darktable's appended naming convention (image.ext.xmp).

If an old Lightroom-style sidecar (image.xmp, extension-replaced) already
exists in the organized directory, it is deleted after a successful write.
Source files are NEVER modified.

Run inside the container:
    python /app/backfill_xmp_sidecars.py [--dry-run] [--catalog-id <id>]
"""

import argparse
import logging
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from textwrap import dedent

sys.path.insert(0, "/app")

from lumina.db import get_db_context
from lumina.db.models import Image

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# XMP namespaces
NS = {
    "x": "adobe:ns:meta/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "xmp": "http://ns.adobe.com/xap/1.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "crs": "http://ns.adobe.com/camera-raw-settings/1.0/",
}

for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


def _parse_lr_xmp(path: Path) -> dict:
    """Extract rating, label, and keywords from a Lightroom XMP sidecar."""
    result = {"rating": None, "label": None, "keywords": []}
    try:
        text = path.read_text(errors="ignore")
        tree = ET.fromstring(text)

        def find_attr(tag_ns, attr_ns, attr_local):
            tag = f"{{{NS[tag_ns]}}}Description"
            attr = f"{{{NS[attr_ns]}}}{attr_local}"
            for el in tree.iter(tag):
                val = el.get(attr)
                if val:
                    return val
            return None

        rating = find_attr("rdf", "xmp", "Rating")
        if rating and rating.lstrip("-").isdigit():
            result["rating"] = int(rating)

        label = find_attr("rdf", "xmp", "Label")
        if label:
            result["label"] = label

        # Keywords from dc:subject rdf:Bag
        dc_subject = f"{{{NS['dc']}}}subject"
        rdf_bag = f"{{{NS['rdf']}}}Bag"
        rdf_li = f"{{{NS['rdf']}}}li"
        for el in tree.iter(dc_subject):
            for bag in el.iter(rdf_bag):
                result["keywords"] = [li.text for li in bag.iter(rdf_li) if li.text]

    except Exception as e:
        logger.warning(f"Could not parse {path}: {e}")
    return result


def _write_darktable_xmp(dest: Path, meta: dict) -> None:
    """Write a minimal Darktable-compatible XMP sidecar."""
    rating = meta.get("rating") or 0
    label = meta.get("label") or ""
    keywords = meta.get("keywords") or []

    attrs = []
    if rating:
        attrs.append(f'    xmp:Rating="{rating}"')
    if label:
        attrs.append(f'    xmp:Label="{label}"')
    attrs_str = "\n".join(attrs)

    kw_block = ""
    if keywords:
        items = "\n".join(f"     <rdf:li>{kw}</rdf:li>" for kw in keywords)
        kw_block = dedent(f"""
   <dc:subject>
    <rdf:Bag>
{items}
    </rdf:Bag>
   </dc:subject>""").rstrip()

    xmp = dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="XMP Core 4.4.0-Exiv2">
         <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
          <rdf:Description rdf:about=""
            xmlns:xmp="http://ns.adobe.com/xap/1.0/"
            xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:darktable="http://darktable.sf.net/"
        {attrs_str}
            darktable:history_end="0"
            darktable:import_timestamp="-1"
            darktable:change_timestamp="-1"
            darktable:export_timestamp="-1"
            darktable:print_timestamp="-1">{kw_block}
          </rdf:Description>
         </rdf:RDF>
        </x:xmpmeta>
        """)
    dest.write_text(xmp, encoding="utf-8")


def _find_lr_sidecar(source: Path) -> Path | None:
    """Find a Lightroom-style sidecar (extension-replaced) for source."""
    replaced = source.parent / (source.stem + ".xmp")
    if replaced.exists():
        return replaced
    # Also check appended (Darktable style) — still useful as source metadata
    appended = source.parent / (source.name + ".xmp")
    if appended.exists():
        return appended
    return None


def backfill(catalog_id: str | None, dry_run: bool) -> None:
    with get_db_context() as db:
        query = db.query(Image).filter(Image.organized_path.isnot(None))
        if catalog_id:
            query = query.filter(Image.catalog_id == catalog_id)
        images = query.all()

    logger.info(f"Found {len(images)} organized images to check")

    written = skipped_exists = skipped_no_source = no_metadata = errors = deleted_lr = 0

    for img in images:
        source = Path(img.source_path)
        dest = Path(img.organized_path)

        sidecar_src = _find_lr_sidecar(source)
        if not sidecar_src:
            no_metadata += 1
            continue

        meta = _parse_lr_xmp(sidecar_src)
        has_meta = meta["rating"] or meta["label"] or meta["keywords"]

        # Darktable appended destination: dest.ext.xmp
        dt_dest = dest.parent / (dest.name + ".xmp")

        if dt_dest.exists():
            skipped_exists += 1
            continue

        if not dest.exists():
            skipped_no_source += 1
            logger.warning(f"Organized file missing: {dest}")
            continue

        if not has_meta:
            no_metadata += 1
            # Still clean up any LR-style sidecar in organized dir
        else:
            if dry_run:
                logger.info(
                    f"[dry-run] write DT sidecar: {dt_dest}  "
                    f"(rating={meta['rating']}, label={meta['label']}, "
                    f"keywords={meta['keywords']})"
                )
                written += 1
            else:
                try:
                    dt_dest.parent.mkdir(parents=True, exist_ok=True)
                    _write_darktable_xmp(dt_dest, meta)
                    written += 1
                except Exception as e:
                    logger.error(f"Failed writing {dt_dest}: {e}")
                    errors += 1
                    continue

        # Delete old LR-style sidecar from organized dir if present
        lr_in_organized = dest.parent / (dest.stem + ".xmp")
        if lr_in_organized.exists() and lr_in_organized != dt_dest:
            if dry_run:
                logger.info(f"[dry-run] delete LR sidecar: {lr_in_organized}")
                deleted_lr += 1
            else:
                try:
                    lr_in_organized.unlink()
                    deleted_lr += 1
                except Exception as e:
                    logger.error(f"Failed deleting {lr_in_organized}: {e}")

    label = "[dry-run] " if dry_run else ""
    logger.info(
        f"{label}Done — DT sidecars written: {written}, "
        f"LR sidecars deleted from organized dir: {deleted_lr}, "
        f"already present: {skipped_exists}, "
        f"no metadata to preserve: {no_metadata}, "
        f"missing dest file: {skipped_no_source}, errors: {errors}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report without writing")
    parser.add_argument("--catalog-id", help="Limit to one catalog")
    args = parser.parse_args()
    backfill(args.catalog_id, args.dry_run)
