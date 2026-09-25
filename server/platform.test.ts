/**
 * Platform-neutrality guard for shared/: the port's core must run
 * identically in the browser and in Node — no DOM globals, no Node-only
 * modules, no pygame. This test scans the shared sources and fails the
 * build the moment one reaches for a platform.
 *
 * Lives under server/ because it itself needs Node's fs to read the
 * sources; the invariant it enforces is about shared/.
 */
import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const SHARED_DIR = join(import.meta.dirname, "..", "shared");

/** Node built-ins the browser does not have (and which shared/ must not need). */
const NODE_ONLY_IMPORTS = [
  "node:fs", "node:path", "node:os", "node:crypto", "node:http", "node:https",
  "node:net", "node:child_process", "node:process", "node:url", "node:util",
  "node:events", "node:stream", "node:buffer", "node:worker_threads",
  "node:assert", "node:cluster", "node:dns", "node:tls", "node:ws",
];

/** DOM globals the server does not have (and which shared/ must not need). */
const DOM_GLOBALS: RegExp[] = [
  /\bwindow\b/, /\bdocument\b/, /\bHTMLElement\b/, /\blocalStorage\b/,
  /\brequestAnimationFrame\b/, /\bnavigator\b/, /\bCanvasRenderingContext2D\b/,
  /\bAudioContext\b/, /\bHTMLCanvasElement\b/, /\bperformance\.now\b/,
];

/** Remove comments so prose like "window drag" can't trip the global scan.
 * Trailing `//` comments count too; the leading-whitespace guard keeps
 * `https://` strings intact. */
function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|\s)\/\/.*$/gm, "$1");
}

function listTsFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...listTsFiles(full));
    } else if (entry.endsWith(".ts") && !entry.endsWith(".test.ts")) {
      out.push(full);
    }
  }
  return out;
}

describe("shared/ platform neutrality", () => {
  const files = listTsFiles(SHARED_DIR);

  it("has source files to check (the guard is wired up)", () => {
    expect(files.length).toBeGreaterThanOrEqual(4);
  });

  for (const file of files) {
    const rel = file.slice(SHARED_DIR.length + 1);
    const src = stripComments(readFileSync(file, "utf8"));

    it(`${rel}: imports no Node-only modules`, () => {
      for (const mod of NODE_ONLY_IMPORTS) {
        const pattern = new RegExp(`from ["']${mod}["']|require\\(["']${mod}["']\\)|import\\(["']${mod}["']\\)`);
        expect(src, `${rel} must not import ${mod}`).not.toMatch(pattern);
      }
    });

    it(`${rel}: references no DOM globals`, () => {
      for (const pattern of DOM_GLOBALS) {
        expect(src, `${rel} must not reference ${String(pattern)}`).not.toMatch(pattern);
      }
    });

    it(`${rel}: imports only within shared/`, () => {
      const importSources = [...src.matchAll(/from\s+["']([^"']+)["']/g)].map((m) => m[1] ?? "");
      for (const source of importSources) {
        // Only relative imports inside shared/ are allowed — no libraries.
        expect(source, `${rel} imports ${source}`).toMatch(/^\.\//);
      }
    });
  }
});
