-- Migration 002: Add warehouse job support with priority system
-- Extends jobs table with source, priority, and scheduling capabilities

-- Add new columns to jobs table
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS job_source TEXT DEFAULT 'user';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS priority INTEGER DEFAULT 50;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMP;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS warehouse_trigger TEXT;

-- Add comment documentation
COMMENT ON COLUMN jobs.job_source IS 'Source of job: user (manual) or warehouse (automated)';
COMMENT ON COLUMN jobs.priority IS 'Priority 0-100, higher = more urgent. User jobs: 80-100, Warehouse: 10-40';
COMMENT ON COLUMN jobs.scheduled_at IS 'When warehouse scheduled this job';
COMMENT ON COLUMN jobs.warehouse_trigger IS 'What triggered warehouse job (e.g., "Low confidence: 15 images")';

-- Create warehouse configuration table
CREATE TABLE IF NOT EXISTS warehouse_config (
    catalog_id UUID NOT NULL REFERENCES catalogs(id) ON DELETE CASCADE,
    task_type TEXT NOT NULL,
    enabled BOOLEAN DEFAULT true,
    check_interval_minutes INTEGER DEFAULT 60,
    threshold JSONB DEFAULT '{}'::jsonb,
    last_run TIMESTAMP,
    next_run TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (catalog_id, task_type)
);

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_jobs_priority ON jobs(priority DESC, created_at ASC) WHERE status IN ('PENDING', 'PROGRESS');
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(job_source);
CREATE INDEX IF NOT EXISTS idx_warehouse_config_next_run ON warehouse_config(next_run) WHERE enabled = true;

-- Add comment documentation for warehouse_config
COMMENT ON TABLE warehouse_config IS 'Per-catalog configuration for automated warehouse tasks';
COMMENT ON COLUMN warehouse_config.task_type IS 'Type of task: retag_low_confidence, process_new, generate_thumbnails, score_quality';
COMMENT ON COLUMN warehouse_config.check_interval_minutes IS 'How often to check if task should run';
COMMENT ON COLUMN warehouse_config.threshold IS 'Task-specific thresholds (e.g., {"confidence_threshold": 0.3, "min_images": 10})';
COMMENT ON COLUMN warehouse_config.last_run IS 'Last time this task was checked/run';
COMMENT ON COLUMN warehouse_config.next_run IS 'Next scheduled check time';
