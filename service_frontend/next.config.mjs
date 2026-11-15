import { FEEDBACK_REDIRECTS } from './lib/feedback-redirects.mjs';

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone server output → minimal prod image (.next/standalone + server.js).
  // The deploy Dockerfile copies only standalone + static + public.
  output: 'standalone',
  // For local development, basePath is '/'
  // This file will be overwritten during deployment with the appropriate basePath
  images: {},
  // Dev-only: allow the Cloudflare quick tunnel (Meta Embedded Signup needs a
  // public HTTPS origin - see plan 04 runbook) to hit the dev server's assets.
  allowedDevOrigins: ['*.trycloudflare.com'],
  // Old idea URLs -> feedback paths, permanent (lane FEEDBACK-RENAME).
  async redirects() {
    return FEEDBACK_REDIRECTS;
  },
};

export default nextConfig;
