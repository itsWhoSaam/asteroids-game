/**
 * Static serving of the built client from dist/ — the same HTTP server
 * that owns the /ws upgrade, so page and WebSocket share one origin. Exact
 * files only: `/` maps to index.html, anything missing 404s, and a decoded
 * path can never resolve outside the root.
 */

import { readFileSync } from "node:fs";
import type { IncomingMessage, ServerResponse } from "node:http";
import { resolve, sep } from "node:path";

const CONTENT_TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".txt": "text/plain; charset=utf-8",
  ".wasm": "application/wasm",
};

const DEFAULT_TYPE = "application/octet-stream";

export function serveStatic(req: IncomingMessage, res: ServerResponse, root: string): void {
  const isHead = req.method === "HEAD";
  const respond = (status: number, body: string, type = "text/plain; charset=utf-8"): void => {
    res.writeHead(status, { "Content-Type": type });
    res.end(isHead ? undefined : body);
  };
  if (req.method !== "GET" && !isHead) {
    respond(405, "method not allowed");
    return;
  }

  let pathname: string;
  try {
    pathname = decodeURIComponent(new URL(req.url ?? "/", "http://localhost").pathname);
  } catch {
    respond(400, "bad request"); // malformed percent-encoding
    return;
  }
  if (pathname.endsWith("/")) pathname += "index.html";

  // Resolve, then refuse anything that escaped the root — encoded or raw
  // `..` segments normalize away here, so the prefix check is the gate.
  const rootDir = resolve(root);
  const filePath = resolve(rootDir, `.${pathname}`);
  if (!filePath.startsWith(rootDir + sep)) {
    respond(404, "not found");
    return;
  }

  try {
    const body = readFileSync(filePath); // a directory read throws EISDIR → 404
    const dot = filePath.lastIndexOf(".");
    const type = dot >= 0 ? (CONTENT_TYPES[filePath.slice(dot)] ?? DEFAULT_TYPE) : DEFAULT_TYPE;
    res.writeHead(200, { "Content-Type": type, "Content-Length": body.length });
    res.end(isHead ? undefined : body);
  } catch {
    respond(404, "not found");
  }
}
