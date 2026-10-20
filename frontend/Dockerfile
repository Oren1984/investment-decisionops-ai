# syntax=docker/dockerfile:1
# Build context: repository root.
FROM node:22-alpine AS build
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM caddy:2.11.7-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY deploy/starting.html /srv/starting.html
COPY --from=build /web/dist /srv/app
EXPOSE 8080
