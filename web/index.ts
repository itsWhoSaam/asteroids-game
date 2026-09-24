// Placeholder entry for the built client — the real Canvas 2D renderer
// and WebAudio presentation arrive in the browser-client task.
const app = document.querySelector<HTMLDivElement>("#app");
if (!app) {
  throw new Error("#app mount point is missing from index.html");
}

app.textContent = "Asteroids — multiplayer web port (scaffold)";
