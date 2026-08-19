import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN ?? "http://localhost:8000";

export function proxy(request: NextRequest) {
  const url = request.nextUrl.clone();
  const backendUrl = new URL(url.pathname + url.search, BACKEND_ORIGIN);

  return NextResponse.rewrite(backendUrl);
}

export const config = {
  matcher: "/api/:path*",
};
