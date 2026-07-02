// Конфігурація API-клієнта.
//
// За замовчуванням фронтенд бере API/WS із ПОТОЧНОГО origin (той самий
// домен, що й сторінка). Тому один білд працює скрізь: на голому IP і на
// домені, по http і по https — без перезбірки. Caddy проксить /api/* на
// backend, тож same-origin, і CORS взагалі не потрібен.
//
// Явні NEXT_PUBLIC_API_BASE / NEXT_PUBLIC_WS_BASE (якщо задані) мають
// пріоритет — напр. коли фронт і бекенд на різних хостах.

const ENV_API_BASE = process.env.NEXT_PUBLIC_API_BASE;
const ENV_WS_BASE = process.env.NEXT_PUBLIC_WS_BASE;

function isLocalhost(host: string): boolean {
  return host === "localhost" || host === "127.0.0.1";
}

function currentApiBase(): string {
  if (ENV_API_BASE) return ENV_API_BASE;
  if (typeof window !== "undefined") {
    // Локальна розробка: фронт на :3000, бекенд на :8000 (різні порти).
    if (isLocalhost(window.location.hostname)) return "http://localhost:8000";
    // Прод: same-origin через Caddy (той самий домен, будь-який протокол).
    return window.location.origin;
  }
  return "http://localhost:8000";
}

function currentWsBase(): string {
  if (ENV_WS_BASE) return ENV_WS_BASE;
  if (typeof window !== "undefined") {
    if (isLocalhost(window.location.hostname)) return "ws://localhost:8000";
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}`;
  }
  return "ws://localhost:8000";
}

export function apiUrl(path: string): string {
  return `${currentApiBase()}${path}`;
}

export function wsUrl(path: string): string {
  return `${currentWsBase()}${path}`;
}

// Зворотна сумісність (обчислюється на клієнті під час імпорту).
export const API_BASE = currentApiBase();
export const WS_BASE = currentWsBase();
