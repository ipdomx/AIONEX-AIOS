# AIONEX AIOS Dashboard — Frontend Dockerfile

FROM node:24-alpine@sha256:e67514e5d0f6c46656005e1b693b2ec9d52e80b641307de684d4a015ba7a4eaf AS base

FROM base AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

FROM base AS builder
WORKDIR /app
ARG NEXT_PUBLIC_USER_PORTAL_URL=https://ai.vip-e.net
ENV NEXT_TELEMETRY_DISABLED=1
ENV AIOS_BACKEND_ORIGIN=http://backend:8000
ENV NEXT_PUBLIC_USER_PORTAL_URL=$NEXT_PUBLIC_USER_PORTAL_URL
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM base AS runner
WORKDIR /app

# These are web runtimes, not build workers. Keep only the patched TLS
# libraries and Node runtime; npm/yarn are build-stage tools, not runtime APIs.
# Alpine stable repositories retire superseded package revisions. Require a
# security floor rather than an unavailable exact revision, keep signed APK
# verification enabled, and record the resolved, matching TLS library versions.
RUN set -eu; \
    apk upgrade --no-cache; \
    apk add --no-cache --upgrade 'libcrypto3>=3.5.9-r0' 'libssl3>=3.5.9-r0'; \
    crypto="$(apk list --installed libcrypto3 | awk 'NR==1{print $1} END{if(NR!=1)exit 1}')"; \
    ssl="$(apk list --installed libssl3 | awk 'NR==1{print $1} END{if(NR!=1)exit 1}')"; \
    test "${crypto#libcrypto3-}" = "${ssl#libssl3-}"; \
    comparison="$(apk version -t "${crypto#libcrypto3-}" 3.5.9-r0)"; \
    case "$comparison" in '='|'>') ;; *) exit 1 ;; esac; \
    mkdir -p /usr/local/share/aionex; \
    printf '%s\n' "$crypto" "$ssl" > /usr/local/share/aionex/tls-packages.txt; \
    rm -rf /usr/local/lib/node_modules/npm /opt/yarn-*; \
    rm -f /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/yarn /usr/local/bin/yarnpkg

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
ENV AIOS_BACKEND_ORIGIN=http://backend:8000

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
