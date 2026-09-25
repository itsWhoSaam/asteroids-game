/**
 * Static-serving behavior: exact files from the root, index at `/`,
 * 404 everywhere else — and traversal (raw or percent-encoded) never
 * escapes the root.
 */

import { afterAll, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { IncomingMessage, ServerResponse } from "node:http";
import { serveStatic } from "./static";

function makeRoot(): string {
  const root = mkdtempSync(join(tmpdir(), "asteroids-static-"));
  writeFileSync(join(root, "index.html"), "<html>client</html>");
  writeFileSync(join(root, "index.js"), "console.log('hi')");
  return root;
}

function fakeReq(url: string, method = "GET"): IncomingMessage {
  return { method, url } as unknown as IncomingMessage;
}

interface Captured {
  status: number | undefined;
  contentType: string | undefined;
  body: string | undefined;
}

function fakeRes(): { res: ServerResponse; captured: Captured } {
  const captured: Captured = { status: undefined, contentType: undefined, body: undefined };
  const res = {
    writeHead(status: number, headers: Record<string, string>) {
      captured.status = status;
      captured.contentType = headers["Content-Type"];
    },
    end(body?: string) {
      captured.body = body;
    },
  } as unknown as ServerResponse;
  return { res, captured };
}

const ROOT = makeRoot();

describe("serveStatic", () => {
  it("serves index.html at /", () => {
    const { res, captured } = fakeRes();
    serveStatic(fakeReq("/"), res, ROOT);
    expect(captured.status).toBe(200);
    expect(captured.contentType).toContain("text/html");
    expect(String(captured.body)).toBe("<html>client</html>"); // res.end gets the raw Buffer
  });

  it("serves js files with a js content type", () => {
    const { res, captured } = fakeRes();
    serveStatic(fakeReq("/index.js"), res, ROOT);
    expect(captured.status).toBe(200);
    expect(captured.contentType).toContain("text/javascript");
  });

  it("404s missing files", () => {
    const { res, captured } = fakeRes();
    serveStatic(fakeReq("/missing.js"), res, ROOT);
    expect(captured.status).toBe(404);
  });

  it("404s directory traversal, raw and percent-encoded", () => {
    for (const url of ["/../package.json", "/%2e%2e/package.json", "/..%2fpackage.json"]) {
      const { res, captured } = fakeRes();
      serveStatic(fakeReq(url), res, ROOT);
      expect(captured.status, url).toBe(404);
    }
  });

  it("rejects non-GET methods", () => {
    const { res, captured } = fakeRes();
    serveStatic(fakeReq("/", "POST"), res, ROOT);
    expect(captured.status).toBe(405);
  });

  it("omits the body on HEAD", () => {
    const { res, captured } = fakeRes();
    serveStatic(fakeReq("/", "HEAD"), res, ROOT);
    expect(captured.status).toBe(200);
    expect(captured.body).toBeUndefined();
  });

  afterAll(() => {
    rmSync(ROOT, { recursive: true, force: true });
  });
});
