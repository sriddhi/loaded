/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Same-origin proxy: the browser calls /api/* on the frontend origin and Next
  // forwards to the backend. This keeps auth cookies same-site (SameSite=Lax)
  // without CORS or Secure-cookie gymnastics across :3000 and :8000.
  async rewrites() {
    const backend = process.env.BACKEND_INTERNAL_URL ?? "http://backend:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${backend}/:path*`,
      },
    ];
  },
};

export default nextConfig;
