-- Add hand-verification columns to images
ALTER TABLE images
  ADD COLUMN IF NOT EXISTS quality_verified_score INTEGER,
  ADD COLUMN IF NOT EXISTS quality_verified_at TIMESTAMP;
