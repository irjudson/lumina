#!/usr/bin/env python3
"""Backfill burst detection with EXIF metadata matching."""
import sys
import traceback
import uuid
from datetime import datetime

def main():
    from lumina.db.connection import SessionLocal
    from lumina.db.models import Image, Burst
    from lumina.analysis.bursts import detect_bursts
    from sqlalchemy import update

    catalog_id = '36ee8b6f-9bfc-4bcd-a0ad-3e5a26946886'
    db = SessionLocal()

    print('Querying images...')
    rows = db.query(
        Image.id, Image.capture_time, Image.camera_model,
        Image.quality_score, Image.focal_length, Image.aperture, Image.iso
    ).filter(
        Image.catalog_id == catalog_id,
        Image.capture_time.isnot(None)
    ).all()
    print(f'Fetched {len(rows)} images')

    image_dict = {}
    image_list = []
    for r in rows:
        d = {
            'id': str(r.id),
            'timestamp': r.capture_time,
            'camera': r.camera_model or 'unknown',
            'quality_score': r.quality_score or 0,
            'focal_length': r.focal_length,
            'aperture': r.aperture,
            'iso': r.iso,
        }
        image_dict[d['id']] = d
        image_list.append(d)
    del rows

    print('Running burst detection...')
    bursts = detect_bursts(image_list, gap_threshold=2.0, min_size=3)
    total_imgs = sum(len(b['image_ids']) for b in bursts)
    print(f'Detected {len(bursts)} bursts with {total_imgs} images')

    print('Saving to database...')
    saved = 0
    for i, b in enumerate(bursts):
        burst_id = uuid.uuid4()
        best_id = max(
            b['image_ids'],
            key=lambda x: image_dict[x].get('quality_score', 0)
        )

        db.add(Burst(
            id=burst_id,
            catalog_id=catalog_id,
            image_count=len(b['image_ids']),
            start_time=b['start_time'],
            end_time=b['end_time'],
            duration_seconds=b['duration_seconds'],
            camera_make=None,
            camera_model=b.get('camera'),
            best_image_id=best_id,
            selection_method='quality',
            created_at=datetime.utcnow(),
        ))
        db.flush()  # Flush Burst row so FK constraint is satisfied

        for seq, img_id in enumerate(b['image_ids']):
            db.execute(
                update(Image)
                .where(Image.id == img_id)
                .values(burst_id=burst_id, burst_sequence=seq)
            )

        saved += 1
        if saved % 20 == 0:
            db.commit()
            print(f'  Saved {saved}/{len(bursts)} bursts')

    db.commit()
    print(f'Done! Saved {saved} bursts to database')
    db.close()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
