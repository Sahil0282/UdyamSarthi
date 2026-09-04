-- Runs once on first container start.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;      -- fuzzy village-name index (M1)
CREATE EXTENSION IF NOT EXISTS unaccent;     -- transliteration noise in names
