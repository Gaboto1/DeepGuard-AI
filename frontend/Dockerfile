# ──────────────────────────────────────────────────────────────────────────────
# DeepGuard AI — Dockerfile Frontend (static export)
#
# Sirve el output estático de Next.js con nginx.
# En producción se usa Netlify (no este Dockerfile).
# Este archivo es útil para despliegues Docker/Docker Compose locales.
# ──────────────────────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

# URL de la API de producción (Render)
ARG NEXT_PUBLIC_API_URL=https://deepguard-ai-api.onrender.com
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_TELEMETRY_DISABLED=1

# Genera la carpeta /out con HTML/CSS/JS estático
RUN npm run build

# ── Servidor estático ─────────────────────────────────────────────────────────
FROM nginx:alpine AS runner
COPY --from=builder /app/out /usr/share/nginx/html

# Configuración SPA: todas las rutas sirven index.html
RUN printf 'server {\n  listen 3000;\n  root /usr/share/nginx/html;\n  index index.html;\n  location / { try_files $uri $uri/ /index.html; }\n}\n' \
    > /etc/nginx/conf.d/default.conf

EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
