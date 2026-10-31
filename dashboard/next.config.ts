import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // `next build` also writes a self-contained server to .next/standalone, which the Docker image runs.
  // `npm run dev` is not affected.
  output: 'standalone',
};

export default nextConfig;
