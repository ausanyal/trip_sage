import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

function getBackendOrigin(): string {
  return (process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:8000").replace(
    /\/+$/,
    ""
  );
}

async function proxyToFastApi(
  req: NextRequest,
  context: { params: { path: string[] } }
): Promise<Response> {
  const subPath = (context.params.path || []).join("/");
  const search = req.nextUrl.search || "";
  const targetUrl = `${getBackendOrigin()}/api/${subPath}${search}`;

  const headers = new Headers();
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const accept = req.headers.get("accept");
  if (accept) headers.set("accept", accept);
  headers.set("accept-encoding", "identity");

  const hasBody = req.method !== "GET" && req.method !== "HEAD";
  const bodyBuffer = hasBody ? await req.arrayBuffer() : undefined;

  const upstream = await fetch(targetUrl, {
    method: req.method,
    headers,
    body: bodyBuffer,
    cache: "no-store",
  });

  const respHeaders = new Headers();
  const upContentType = upstream.headers.get("content-type");
  if (upContentType) {
    respHeaders.set("content-type", upContentType);
  }
  respHeaders.set("cache-control", "no-cache, no-transform");
  respHeaders.set("x-accel-buffering", "no");

  return new Response(upstream.body, {
    status: upstream.status,
    headers: respHeaders,
  });
}

export async function GET(
  req: NextRequest,
  ctx: { params: { path: string[] } }
): Promise<Response> {
  return proxyToFastApi(req, ctx);
}

export async function POST(
  req: NextRequest,
  ctx: { params: { path: string[] } }
): Promise<Response> {
  return proxyToFastApi(req, ctx);
}
