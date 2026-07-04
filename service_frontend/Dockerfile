# Multi-stage build for the FoundryX EMS Next.js 15 frontend (standalone output).
# No Prisma (stripped from this app), no in-container nginx — host nginx fronts it.
FROM node:20-alpine AS builder

WORKDIR /app

# React 19 peer deps need legacy resolution (mirrors `npm install --force` locally).
COPY package*.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --prefer-offline --no-audit --legacy-peer-deps

COPY . .

# NEXT_PUBLIC_* are INLINED at build time → the browser-facing backend origin
# must be known here, not at runtime. Pass via --build-arg in CI/compose.
ARG NEXT_PUBLIC_BACKEND_API_URL=http://localhost:8001
ENV NEXT_PUBLIC_BACKEND_API_URL=$NEXT_PUBLIC_BACKEND_API_URL
ARG NEXT_PUBLIC_META_APP_ID=
ENV NEXT_PUBLIC_META_APP_ID=$NEXT_PUBLIC_META_APP_ID
ARG NEXT_PUBLIC_META_ES_CONFIG_ID=
ENV NEXT_PUBLIC_META_ES_CONFIG_ID=$NEXT_PUBLIC_META_ES_CONFIG_ID
ARG NEXT_PUBLIC_META_GRAPH_VERSION=v19.0
ENV NEXT_PUBLIC_META_GRAPH_VERSION=$NEXT_PUBLIC_META_GRAPH_VERSION

ENV NODE_OPTIONS="--max-old-space-size=4096"
RUN --mount=type=cache,target=/app/.next/cache,sharing=locked \
    NEXT_TELEMETRY_DISABLED=1 NODE_ENV=production npm run build

# ── Production stage ────────────────────────────────────────────────────────
FROM node:20-alpine

RUN apk add --no-cache curl

WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3001
ENV HOSTNAME=0.0.0.0

# Standalone bundle = a self-contained node server + only its used deps.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001 && chown -R nextjs:nodejs /app
USER nextjs

EXPOSE 3001

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD curl -fsS http://localhost:3001/ >/dev/null || exit 1

CMD ["node", "server.js"]
