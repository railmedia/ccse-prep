FROM node:22-alpine AS base
WORKDIR /app
COPY package*.json ./

FROM base AS deps
RUN npm ci

# --- development ------------------------------------------------------------
FROM deps AS dev
COPY . .
EXPOSE 4321
CMD ["npm", "run", "dev"]

# --- production -------------------------------------------------------------
FROM deps AS build
COPY . .
RUN npm run build

FROM nginx:stable-alpine AS prod
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
# 127.0.0.1, not localhost: nginx binds IPv4 only here, and localhost
# resolves to ::1 first, which fails and marks the container unhealthy.
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1/healthz || exit 1
