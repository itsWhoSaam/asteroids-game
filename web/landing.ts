/**
 * The landing page — Play solo, Create a room, or Join a code, with an
 * optional display name (spec: Player-visible behavior). The `?room=CODE`
 * deep link prefills the join and fires the connect attempt immediately.
 * DOM building lives here; the pure URL/code parsing helpers are pinned
 * by tests.
 */

/** Strict room code: exactly 4 alphanumeric characters, uppercased. */
export function parseRoomCode(raw: string): string | null {
  const code = raw.trim().toUpperCase();
  return /^[A-Z0-9]{4}$/.test(code) ? code : null;
}

/** A fresh 4-char room code from the unambiguous alphabet — "Create
 * room" generates one and joins it; the server creates rooms on first
 * join (the protocol's only vocabulary is join). */
export function newRoomCode(random: () => number = Math.random): string {
  // No 0/O or 1/I: codes are read aloud across a room.
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  let code = "";
  for (let i = 0; i < 4; i += 1) {
    code += alphabet[Math.floor(random() * alphabet.length)];
  }
  return code;
}

/** The room code in a URL's query string, or null (also null for junk). */
export function roomFromSearch(search: string): string | null {
  const param = new URLSearchParams(search).get("room");
  return param === null ? null : parseRoomCode(param);
}

/** A shareable deep link for a room code. */
export function roomDeepLink(code: string, origin = ""): string {
  return `${origin}/?room=${encodeURIComponent(code)}`;
}

export interface LandingActions {
  onSolo(name: string): void;
  onCreate(name: string): void;
  onJoin(code: string, name: string): void;
}

export interface LandingHandle {
  hide(): void;
}

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** Build the landing overlay inside `container`; returns a hide() handle. */
export function buildLanding(container: HTMLElement, actions: LandingActions): LandingHandle {
  container.textContent = "";
  container.classList.add("landing");

  const card = el("div", "landing-card");

  const title = el("h1", "landing-title", "ASTEROIDS");
  const subtitle = el(
    "p",
    "landing-subtitle",
    "Co-op rooms for 2–4 players. Fly with WASD or the arrows, shoot with space.",
  );
  card.append(title, subtitle);

  const nameRow = el("div", "landing-row");
  const nameLabel = el("label", "landing-label");
  nameLabel.htmlFor = "landing-name";
  nameLabel.textContent = "Name (optional)";
  const nameInput = el("input", "landing-input") as HTMLInputElement;
  nameInput.id = "landing-name";
  nameInput.maxLength = 16;
  nameInput.placeholder = "Anonymous";
  nameRow.append(nameLabel, nameInput);
  card.append(nameRow);

  const soloButton = el("button", "landing-button landing-solo", "Play solo");
  soloButton.type = "button";
  soloButton.addEventListener("click", () => actions.onSolo(nameInput.value.trim()));

  const createButton = el("button", "landing-button landing-create", "Create room");
  createButton.type = "button";
  createButton.addEventListener("click", () => actions.onCreate(nameInput.value.trim()));

  const joinRow = el("div", "landing-row landing-join");
  const codeInput = el("input", "landing-input landing-code") as HTMLInputElement;
  codeInput.maxLength = 4;
  codeInput.placeholder = "CODE";
  codeInput.autocapitalize = "characters";
  const joinButton = el("button", "landing-button landing-join", "Join room");
  joinButton.type = "button";
  joinButton.addEventListener("click", () => {
    const code = parseRoomCode(codeInput.value);
    if (code !== null) actions.onJoin(code, nameInput.value.trim());
  });
  joinRow.append(codeInput, joinButton);

  card.append(soloButton, createButton, joinRow);
  container.append(card);

  const deepLinkRoom = roomFromSearch(window.location.search);
  if (deepLinkRoom !== null) {
    codeInput.value = deepLinkRoom;
    // The deep link IS the connect attempt: join immediately.
    actions.onJoin(deepLinkRoom, nameInput.value.trim());
  }

  return {
    hide(): void {
      container.textContent = "";
      container.classList.remove("landing");
    },
  };
}
