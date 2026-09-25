/**
 * Entry point: one origin on one port — the built client from dist/ and
 * the room WebSocket at /ws. Build first, then run the bundle:
 *
 *   npm run build && npm start          # PORT env sets the port (3000)
 */

import { createServer } from "node:http";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { RoomHub } from "./rooms";
import { serveRooms } from "./gateway";
import { serveStatic } from "./static";

const PORT = Number(process.env.PORT ?? "") || 3000;
const DIST_ROOT = fileURLToPath(new URL("../dist/", import.meta.url));

if (!existsSync(`${DIST_ROOT}index.html`)) {
  process.stderr.write("[server] dist/index.html not found — run `npm run build` to emit the client\n");
}

const hub = new RoomHub();
const server = createServer((req, res) => serveStatic(req, res, DIST_ROOT));
serveRooms(server, hub);
server.listen(PORT, () => {
  process.stdout.write(`asteroids room server: http://localhost:${PORT} (client from dist/, ws at /ws)\n`);
});
