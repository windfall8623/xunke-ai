ARG NODE_IMAGE=node:22-bookworm-slim
ARG NGINX_IMAGE=nginx:1.28-alpine
FROM ${NODE_IMAGE} AS build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM ${NGINX_IMAGE} AS runtime
COPY deploy/nginx.conf /etc/nginx/nginx.conf
COPY deploy/nginx-app.conf /etc/nginx/snippets/app.conf
COPY deploy/nginx-site.conf /etc/nginx/sites-enabled/site.conf
COPY --from=build /web/dist/ /usr/share/nginx/html/
USER nginx
EXPOSE 8080 8443
# Bypass image entrypoint configuration edits; runtime filesystem is read-only.
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
