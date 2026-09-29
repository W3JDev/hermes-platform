FROM node:22-bookworm-slim AS builder

WORKDIR /app
ENV CI=true

# Copy package descriptors
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
COPY apps/server/package.json ./apps/server/
COPY apps/mobile/package.json ./apps/mobile/
COPY apps/worker/package.json ./apps/worker/
COPY packages/domain/package.json ./packages/domain/
COPY packages/integrations/package.json ./packages/integrations/
COPY packages/backends/package.json ./packages/backends/

RUN corepack enable \
  && corepack prepare pnpm@11.19.0 --activate \
  && pnpm install --frozen-lockfile

# Copy source tree
COPY tsconfig.json tsconfig.build.json biome.json ./
COPY apps ./apps
COPY packages ./packages

# Build backend and server
RUN pnpm build:server

FROM node:22-bookworm-slim AS runner

WORKDIR /app
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=8787 \
    DATA_DIR=/data

RUN groupadd --system --gid 1001 openmuse \
  && useradd --system --uid 1001 --gid openmuse --home /data --shell /usr/sbin/nologin openmuse \
  && mkdir -p /data \
  && chown -R openmuse:openmuse /app /data

COPY --from=builder --chown=openmuse:openmuse /app/node_modules ./node_modules
COPY --from=builder --chown=openmuse:openmuse /app/dist ./dist
COPY --from=builder --chown=openmuse:openmuse /app/package.json ./package.json
COPY --from=builder --chown=openmuse:openmuse /app/apps/server/package.json ./apps/server/package.json
COPY --from=builder --chown=openmuse:openmuse /app/apps/mobile/package.json ./apps/mobile/package.json
COPY --from=builder --chown=openmuse:openmuse /app/packages ./packages
COPY --from=builder --chown=openmuse:openmuse /app/apps/mobile/dist/web ./client

USER openmuse
VOLUME ["/data"]
EXPOSE 8787

HEALTHCHECK --interval=20s --timeout=5s --start-period=15s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:8787/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "dist/apps/server/src/index.js"]
