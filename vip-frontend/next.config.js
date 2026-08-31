// Next.js loads this configuration as CommonJS.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const createNextIntlPlugin = require("next-intl/plugin");

const withNextIntl = createNextIntlPlugin("./src/i18n.ts");
const staticExport = process.env.AIOS_VIP_STATIC_EXPORT === "true";
const backendOrigin = (
  process.env.AIOS_BACKEND_ORIGIN || "https://api.vip-e.net"
).replace(/\/$/, "");

const contentSecurityPolicy = [
  "default-src 'self'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "object-src 'none'",
  "script-src 'self' 'unsafe-inline' https://www.gstatic.com https://www.google.com https://apis.google.com https://www.recaptcha.net",
  "script-src-attr 'none'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https://api.vip-e.net",
  "font-src 'self' data: https://api.vip-e.net",
  "connect-src 'self' https://api.vip-e.net https://identitytoolkit.googleapis.com https://securetoken.googleapis.com https://www.googleapis.com https://*.googleapis.com https://*.firebaseapp.com",
  "frame-src https://www.google.com https://accounts.google.com https://www.recaptcha.net https://*.firebaseapp.com",
  "upgrade-insecure-requests",
].join("; ");

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: staticExport ? "export" : "standalone",
  trailingSlash: staticExport,
  poweredByHeader: false,
  reactStrictMode: true,
  images: { unoptimized: true },
  ...(staticExport
    ? {}
    : {
        async rewrites() {
          return [
            {
              source: "/api/v1/:path*",
              destination: `${backendOrigin}/api/v1/:path*`,
            },
          ];
        },
        async headers() {
          return [
            {
              source: "/:path*",
              headers: [
                {
                  key: "Content-Security-Policy",
                  value: contentSecurityPolicy,
                },
                {
                  key: "Referrer-Policy",
                  value: "strict-origin-when-cross-origin",
                },
                { key: "Strict-Transport-Security", value: "max-age=31536000" },
                { key: "X-Content-Type-Options", value: "nosniff" },
                { key: "X-Frame-Options", value: "DENY" },
                {
                  key: "Permissions-Policy",
                  value:
                    "camera=(), geolocation=(), microphone=(), payment=(), publickey-credentials-create=(self), publickey-credentials-get=(self), usb=()",
                },
              ],
            },
          ];
        },
      }),
};

module.exports = withNextIntl(nextConfig);
