FROM node:22-alpine AS base

ENV NEXT_TELEMETRY_DISABLED=1 \
    PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH

RUN corepack enable && corepack prepare pnpm@9.15.0 --activate

WORKDIR /workspace

FROM base AS deps

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY packages/shared/package.json packages/shared/package.json
RUN pnpm install --frozen-lockfile

FROM deps AS development

COPY apps/web apps/web
COPY packages/shared packages/shared

EXPOSE 3000

CMD ["pnpm", "--dir", "apps/web", "exec", "next", "dev", "--webpack", "--hostname", "0.0.0.0"]

FROM deps AS builder

ARG DEMO_MODE=0
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_SCREENSHOT_SESSION_ID

ENV DEMO_MODE=$DEMO_MODE \
    NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_SCREENSHOT_SESSION_ID=$NEXT_PUBLIC_SCREENSHOT_SESSION_ID

COPY apps/web apps/web
COPY packages/shared packages/shared
RUN pnpm --dir apps/web build

FROM base AS prod-deps

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY packages/shared/package.json packages/shared/package.json
RUN pnpm install --prod --frozen-lockfile

FROM base AS runner

ENV NODE_ENV=production

COPY --from=prod-deps --chown=node:node /workspace/node_modules ./node_modules
COPY --from=prod-deps --chown=node:node /workspace/apps/web/node_modules ./apps/web/node_modules
COPY --from=builder --chown=node:node /workspace/apps/web/.next ./apps/web/.next
COPY --from=builder --chown=node:node /workspace/apps/web/next.config.ts ./apps/web/next.config.ts
COPY --from=builder --chown=node:node /workspace/apps/web/package.json ./apps/web/package.json
COPY --from=builder --chown=node:node /workspace/apps/web/public ./apps/web/public
COPY --from=builder --chown=node:node /workspace/packages/shared ./packages/shared
COPY --chown=node:node package.json pnpm-lock.yaml pnpm-workspace.yaml ./

USER node

EXPOSE 3000

CMD ["pnpm", "--dir", "apps/web", "exec", "next", "start", "--hostname", "0.0.0.0", "--port", "3000"]
