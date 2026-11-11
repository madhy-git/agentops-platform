# LEARNING NOTES
# - Two stages: Node builds the static bundle; the runtime image is just nginx + files. No Node, no npm, no
#   source code in production: a much smaller attack surface (and image).
# - nginx-unprivileged listens on 8080 and runs as uid 101, so it passes the cluster's "restricted" Pod Security.
# - `npm ci` installs exactly what package-lock.json says (reproducible), and fails if the lockfile is stale.
FROM node:22.16.0-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.28.0-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
