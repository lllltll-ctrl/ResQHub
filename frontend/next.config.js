/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // ESLint не блокує прод-білд: правила стилю (no-unescaped-entities тощо)
  // не мають ламати деплой. Типи все одно перевіряються (tsc / next build).
  eslint: { ignoreDuringBuilds: true },
};

module.exports = nextConfig;