FROM postgres:16-alpine

# Init script creates the three databases we need for Hermes Platform
COPY init-scripts/ /docker-entrypoint-initdb.d/
