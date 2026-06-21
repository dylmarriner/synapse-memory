-- Nexus shared-memory database initialisation
-- Creates extensions for the nexus database.
-- Runs automatically on first postgres container start.

\connect nexus
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
