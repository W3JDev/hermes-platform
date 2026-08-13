-- Hermes Platform postgres-hub
-- Creates the three databases for the platform on first boot.
-- Only runs on a fresh data volume (postgres docker-entrypoint-initdb.d semantics).

CREATE DATABASE env_vault;
CREATE DATABASE hermes_jira;
CREATE DATABASE hermes_helpline;
