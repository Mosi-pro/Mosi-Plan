# Build-Stufe: statische Dateien erzeugen
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# Laufzeit: Nginx als Reverse Proxy + Auslieferung der App
FROM nginx:1.27-alpine
COPY --from=build /src/dist /usr/share/nginx/html
COPY nginx/ /etc/nginx/mosi/
COPY nginx/entrypoint.sh /docker-entrypoint.d/40-mosi.sh
RUN chmod +x /docker-entrypoint.d/40-mosi.sh && rm /etc/nginx/conf.d/default.conf
EXPOSE 80 443
