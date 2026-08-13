FROM postgres:16-alpine

# Init script creates the three databases we need for Hermes Platform.
# COPY path is relative to the build context (repo root), not the Dockerfile.
COPY postgres-hub/init-scripts/ /docker-entrypoint-initdb.d/
