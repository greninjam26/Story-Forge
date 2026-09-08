type SecurityHeaderEnvironment = "development" | "production";

export type SecurityHeader = {
  key: string;
  value: string;
};

export type SecurityHeaderRule = {
  source: string;
  headers: SecurityHeader[];
};

function normalizeMediaOrigin(mediaOrigin?: string | null): string | null {
  if (!mediaOrigin) {
    return null;
  }
  try {
    const parsed = new URL(mediaOrigin);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return null;
    }
    return parsed.origin;
  } catch {
    return null;
  }
}

function buildContentSecurityPolicy(
  environment: SecurityHeaderEnvironment,
  mediaOrigin?: string | null,
) {
  const scriptSources = [
    "'self'",
    "'unsafe-inline'",
    "https://accounts.google.com",
    "https://va.vercel-scripts.com",
  ];
  if (environment === "development") {
    scriptSources.push("'unsafe-eval'");
  }

  // Illustrations and narration are served from the API origin, which is the
  // Render HTTPS origin in production and a plain-HTTP localhost port in
  // development and the offline end-to-end run. Allow it explicitly rather
  // than relying on a scheme wildcard that cannot cover both.
  const resolvedMediaOrigin = normalizeMediaOrigin(mediaOrigin);
  const servesMediaOverHttp =
    resolvedMediaOrigin !== null && resolvedMediaOrigin.startsWith("http://");
  const mediaSources = ["'self'", "https:", "data:", "blob:"];
  if (resolvedMediaOrigin !== null) {
    mediaSources.push(resolvedMediaOrigin);
  }

  const directives = [
    ["default-src", "'self'"],
    ["base-uri", "'self'"],
    ["object-src", "'none'"],
    ["frame-ancestors", "'none'"],
    ["form-action", "'self'"],
    ["script-src", ...scriptSources],
    ["style-src", "'self'", "'unsafe-inline'", "https://accounts.google.com"],
    ["frame-src", "https://accounts.google.com"],
    [
      "connect-src",
      "'self'",
      "https://accounts.google.com",
      "https://vitals.vercel-insights.com",
    ],
    ["img-src", ...mediaSources],
    ["media-src", ...mediaSources],
    ["font-src", "'self'", "data:"],
  ];

  // `upgrade-insecure-requests` rewrites every http:// subresource to https://,
  // which breaks the app's own media whenever the API is reached over plain
  // HTTP. A configured http:// media origin therefore marks a deployment that
  // is not TLS-terminated, and the upgrade is withheld for it alone.
  if (environment === "production" && !servesMediaOverHttp) {
    directives.push(["upgrade-insecure-requests"]);
  }

  return directives.map((directive) => directive.join(" ")).join("; ");
}

export function buildSecurityHeaders(
  environment: SecurityHeaderEnvironment,
  mediaOrigin?: string | null,
): SecurityHeader[] {
  const headers: SecurityHeader[] = [
    {
      key: "Content-Security-Policy",
      value: buildContentSecurityPolicy(environment, mediaOrigin),
    },
    // Reader links contain a capability token in the path. This also prevents
    // propagation to same-origin requests, where stricter-origin policies do not.
    { key: "Referrer-Policy", value: "no-referrer" },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "X-Frame-Options", value: "DENY" },
    {
      key: "Permissions-Policy",
      value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    },
    {
      key: "Cross-Origin-Opener-Policy",
      value: "same-origin-allow-popups",
    },
  ];

  if (environment === "production") {
    headers.push({
      key: "Strict-Transport-Security",
      value: "max-age=31536000; includeSubDomains",
    });
  }

  return headers;
}

export function buildSecurityHeaderRules(
  environment: SecurityHeaderEnvironment,
  mediaOrigin?: string | null,
): SecurityHeaderRule[] {
  return [
    {
      source: "/:path*",
      headers: buildSecurityHeaders(environment, mediaOrigin),
    },
    {
      source: "/reader/:path*",
      headers: [
        {
          key: "X-Robots-Tag",
          value: "noindex, nofollow, noarchive",
        },
      ],
    },
  ];
}
