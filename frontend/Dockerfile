# frontend image — the built SPA behind nginx, which also proxies /api (including the alerts
# WebSocket) to the api service so the browser sees one origin.
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Where the browser finds the media server. Vite bakes these in at build time. Empty (the default)
# keeps the development defaults (http://localhost:8889 and :8888); a deployment behind a reverse
# proxy builds with same-origin paths, e.g. --build-arg VITE_MEDIAMTX_WEBRTC_URL=/webrtc
# --build-arg VITE_MEDIAMTX_HLS_URL=/hls (deploy/compose/Caddyfile routes them).
ARG VITE_MEDIAMTX_WEBRTC_URL=
ARG VITE_MEDIAMTX_HLS_URL=
ENV VITE_MEDIAMTX_WEBRTC_URL=$VITE_MEDIAMTX_WEBRTC_URL \
    VITE_MEDIAMTX_HLS_URL=$VITE_MEDIAMTX_HLS_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
