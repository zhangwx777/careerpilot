FROM node:22-bookworm-slim

WORKDIR /workspace
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml /workspace/
RUN pnpm install --frozen-lockfile
COPY . /workspace
