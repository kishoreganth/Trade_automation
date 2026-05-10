/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Production deploys: don't block build on lint/type errors. Fix incrementally in dev.
  eslint: { ignoreDuringBuilds: true },
  typescript: { ignoreBuildErrors: true },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
      {
        source: "/ws",
        destination: "http://localhost:8000/ws",
      },
      {
        source: "/health",
        destination: "http://localhost:8000/health",
      },
    ];
  },
};

module.exports = nextConfig;
