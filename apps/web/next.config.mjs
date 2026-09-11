/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  typescript: {
    ignoreBuildErrors: false,
  },
  experimental: {
    useTypeScriptCli: false,
  },
};
export default nextConfig;
