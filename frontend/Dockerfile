FROM node:20-slim

WORKDIR /app

RUN npm install -g pnpm@9

# Спершу лише маніфест → кеш шару з залежностями
COPY package.json ./
RUN pnpm install

COPY . .

# NEXT_PUBLIC_* пекуться під час build (потрапляють у клієнтський бандл)
ARG NEXT_PUBLIC_API_BASE
ARG NEXT_PUBLIC_WS_BASE
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
ENV NEXT_PUBLIC_WS_BASE=$NEXT_PUBLIC_WS_BASE
ENV NEXT_TELEMETRY_DISABLED=1

RUN pnpm build

EXPOSE 3000

CMD ["pnpm", "start"]
