/**
 * The HUD type stack. SDL's bundled font is not pixel-identical to any
 * webfont — the spec allows HUD typography to differ ("feel is faithful;
 * pixels need not be"), so every canvas draw resolves through this one
 * stack the way the desktop build resolves through pygame.font.Font.
 */
export const FONT_STACK = 'system-ui, "Segoe UI", Arial, sans-serif';

export function fontCss(sizePx: number, weight = 700): string {
  return `${weight} ${sizePx}px ${FONT_STACK}`;
}
