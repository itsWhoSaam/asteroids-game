/**
 * The entry point: build the shared chrome (canvas, background, save,
 * audio, input), then hand control to the landing page. Solo runs the
 * shared sim locally with a session-seeded RNG; rooms attach a
 * RoomConnection and render server snapshots. Solo stays playable with
 * the server down — zero server dependency.
 *
 * Ordering constraint: buildLanding() wipes its container and its
 * ?room= deep link fires a join DURING the build, so the canvas/status
 * chrome exists before the landing is built, and mode starts hide the
 * landing through a nullable binding.
 */
import "./main.css";
import { AudioSfx } from "./audio";
import { InputCapture } from "./input";
import { buildLanding, newRoomCode, type LandingHandle } from "./landing";
import { buildBackground, canvasPoint, fitCanvasToWindow, SCREEN_HEIGHT, SCREEN_WIDTH } from "./render";
import { loadSave, writeSave, type WebSave } from "./storage";
import { SoloGame } from "./solo";
import { RoomGame, statusText } from "./room";
import { shopCellAt } from "./shop";
import { RoomConnection } from "./ws";

/** The game mode currently driving the rAF loop; null = landing only. */
interface ActiveMode {
  frame(dtMs: number): void;
  sync?(): void;
}

function requireElement<T extends HTMLElement>(selector: string): T {
  const node = document.querySelector<T>(selector);
  if (!node) throw new Error(`${selector} is missing from index.html`);
  return node;
}

function main(): void {
  const stage = requireElement<HTMLDivElement>("#stage");
  const app = requireElement<HTMLDivElement>("#app");

  const canvas = document.createElement("canvas");
  canvas.width = SCREEN_WIDTH;
  canvas.height = SCREEN_HEIGHT;
  canvas.className = "game-canvas";
  stage.append(canvas);
  fitCanvasToWindow(canvas);

  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas 2D context unavailable");
  const background = buildBackground(SCREEN_WIDTH, SCREEN_HEIGHT);

  const status = document.createElement("div");
  status.className = "status-banner";
  status.hidden = true;
  stage.append(status);
  const setStatus = (text: string | null, severity: "info" | "error" = "info"): void => {
    if (text === null) {
      status.hidden = true;
      status.textContent = "";
      return;
    }
    status.hidden = false;
    status.textContent = text;
    status.dataset.severity = severity;
  };

  const save: WebSave = loadSave(window.localStorage);
  const audio = new AudioSfx();
  audio.setMuted(save.muted);
  // The AudioContext stays suspended until a user gesture; one unlock
  // listener covers the session.
  window.addEventListener("pointerdown", () => void audio.resume(), { once: true });

  let mode: ActiveMode | null = null;
  let solo: SoloGame | null = null;
  let room: RoomGame | null = null;
  let connection: RoomConnection | null = null;
  let landing: LandingHandle | null = null;

  const persist = (s: WebSave): void => writeSave(window.localStorage, s);

  // The single rAF loop: each active mode receives the frame delta. dt is
  // clamped so a backgrounded tab's multi-second gap cannot fast-forward
  // the sim on return (MAX_DT bounds each step inside the modes).
  let lastNow = 0;
  const loop = (nowMs: number): void => {
    const dtMs = lastNow === 0 ? 0 : Math.min(nowMs - lastNow, 250);
    lastNow = nowMs;
    mode?.frame(dtMs);
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);

  const startSolo = (name: string): void => {
    connection?.close();
    connection = null;
    room = null;
    const game = new SoloGame({
      seed: (Math.random() * 0x7fffffff) | 0,
      playerName: name === "" ? "Pilot" : name,
      save,
      writeSave: persist,
      ctx,
      background,
      audio,
    });
    game.setInputSource(input);
    solo = game;
    mode = { frame: (dt) => game.frame(dt), sync: () => game.syncSave() };
    setStatus(null);
    landing?.hide();
  };

  const wsUrl = (): string =>
    `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;

  const startRoom = (code: string, name: string): void => {
    solo = null;
    connection?.close();
    // The room code is shown in the HUD (RoomGame) and mirrored into the URL
    // so the creator can copy a shareable deep link — the spec's "room code
    // shown" on entry.
    history.replaceState(null, "", `/?room=${encodeURIComponent(code)}`);
    // Late-bound: the connection's callbacks fire into a game that does
    // not exist until the connection is constructed (its events can
    // arrive as soon as connect() runs).
    let game: RoomGame | null = null;
    const conn = new RoomConnection(
      { url: wsUrl(), room: code, name: name === "" ? "Pilot" : name },
      {
        onWelcome: (you, snapshot) => {
          setStatus(null);
          game?.onWelcome(you, snapshot);
        },
        onSnapshot: (message) => game?.onSnapshot(message),
        onStatus: (next, reason) => {
          if (next === "connected") setStatus(null);
          else if (next === "rejected") setStatus(statusText(next, reason), "error");
          else setStatus(statusText(next, reason));
        },
      },
    );
    const started = new RoomGame({
      connection: conn,
      roomCode: code,
      ctx,
      background,
      save,
      writeSave: persist,
      audio,
    });
    started.setInputSource(input);
    game = started;
    room = started;
    connection = conn;
    mode = { frame: (dt) => room?.frame(dt) };
    setStatus(statusText("connecting"));
    landing?.hide();
    conn.connect();
  };

  const input = new InputCapture({
    onSlot: (slot) => {
      if (solo) solo.buySlot(slot);
      else room?.buySlot(slot);
    },
    onToggleMute: () => {
      save.muted = !save.muted;
      audio.setMuted(save.muted);
      persist(save);
    },
    onRestart: () => {
      if (solo) solo.restart();
      else room?.restart();
    },
  });
  input.attach(window);
  window.addEventListener("blur", () => input.clear());

  canvas.addEventListener("click", (event) => {
    const point = canvasPoint(canvas, event.clientX, event.clientY);
    // A click inside the shop strips buys; anywhere else it chips rocks
    // (click-to-chip works for everyone in rooms, per the spec).
    const target = solo !== null ? solo : room;
    if (!target) return;
    const slot = shopCellAt(point.x, point.y);
    if (slot !== null) target.buySlot(slot);
    else target.click(point.x, point.y);
  });

  window.addEventListener("pagehide", () => mode?.sync?.());

  landing = buildLanding(app, {
    onSolo: startSolo,
    onCreate: (name) => startRoom(newRoomCode(), name),
    onJoin: (code, name) => startRoom(code, name),
  });
  // A deep-link join fired during buildLanding — the card must yield.
  if (room !== null) landing.hide();
}

main();
