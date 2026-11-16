"""
sequences/mode_preview.py — FUSION / RoboEyes

Feedback visivo mentre si tiene/cicla il tasto Y sul controller per
scegliere la modalità operativa (xboxPiDirect.py), PRIMA di confermare
con X. Si attiva/aggiorna via MQTT (mqtt_bridge.py, topic
"robot/face/mode_preview") e NON è una sequenza "esclusiva" come le
altre in questa cartella: gli occhi restano quelli normali (idle,
blink, ecc.), questo overlay ci disegna semplicemente sopra. Per
questo drawEyes() lo richiama alla fine, vedi eyes/drawing.py.

Protocollo (vedi anche mqtt_bridge.py e xboxPiDirect.py):
  topic:   robot/face/mode_preview
  payload: "generale" | "jarvis" | "drone" | "esplorazione" | "linea"
           → mostra/aggiorna l'overlay per quella modalità
  payload: "end"
           → nasconde l'overlay (mandato alla conferma con X, o alla
             disconnessione del controller)

Per aggiungere una NUOVA modalità:
  1. scrivi un metodo _mp_draw_<nome>(self, ct, elapsed) qui sotto
  2. aggiungilo al dizionario MODE_PREVIEW_DRAW in fondo al file
  3. aggiungi lo stesso nome a MODALITA_ORDINE in xboxPiDirect.py
Nessun altro file va toccato.
"""

import math
import pygame


class ModePreviewMixin:

    def start_mode_preview(self, nome):
        """Attiva/aggiorna l'overlay per la modalità `nome`."""
        self.mode_preview = nome
        self.mode_preview_timer = pygame.time.get_ticks()

    def end_mode_preview(self):
        """Nasconde l'overlay (conferma con X, o sicurezza su disconnessione)."""
        self.mode_preview = None

    def _draw_mode_preview(self, ct):
        draw_fn = MODE_PREVIEW_DRAW.get(self.mode_preview)
        if draw_fn is None:
            return

        if not hasattr(self, "_mp_font_label"):
            self._mp_font_label = pygame.font.SysFont("monospace", 20, bold=True)

        elapsed = (ct - self.mode_preview_timer) / 1000.0
        draw_fn(self, ct, elapsed)

        # Etichetta col nome della modalità, fade-in rapido ad ogni cambio
        label = self.mode_preview.upper()
        alpha = int(min(1.0, elapsed / 0.25) * 255)
        txt = self._mp_font_label.render(label, True, (255, 255, 255))
        txt.set_alpha(alpha)
        cx = self.screen_width // 2
        self.surface.blit(txt, (cx - txt.get_width() // 2, self.eyeLy + 90))

    # ── GENERALE — volantino che ruota leggermente ──────────────────
    def _mp_draw_generale(self, ct, elapsed):
        cx = self.screen_width // 2
        cy = self.eyeLy - 70
        r = 26
        col = (255, 255, 255)
        angle = math.sin(elapsed * 2.0) * 0.4
        pygame.draw.circle(self.surface, col, (cx, cy), r, 3)
        pygame.draw.circle(self.surface, col, (cx, cy), 5, 0)
        for off in range(3):
            a = angle + off * (2 * math.pi / 3)
            x2 = cx + math.cos(a) * r
            y2 = cy + math.sin(a) * r
            pygame.draw.line(self.surface, col, (cx, cy), (x2, y2), 3)

    # ── JARVIS — reticolo HUD stile sci-fi attorno agli occhi ───────
    def _mp_draw_jarvis(self, ct, elapsed):
        col = (80, 220, 255)
        bl = 10
        for (ex, ey, ew, eh) in (
            (self.eyeLx, self.eyeLy, self.eyeLwidth_current, self.eyeLheight_current),
            (self.eyeRx, self.eyeRy, self.eyeRwidth_current, self.eyeRheight_current),
        ):
            pad = 10
            x0, y0 = ex - pad, ey - pad
            x1, y1 = ex + ew + pad, ey + eh + pad
            for (cx_, cy_, dx, dy) in (
                (x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)
            ):
                pygame.draw.line(self.surface, col, (cx_, cy_), (cx_ + bl * dx, cy_), 2)
                pygame.draw.line(self.surface, col, (cx_, cy_), (cx_, cy_ + bl * dy), 2)
        sweep_y = self.eyeLy + (math.sin(elapsed * 3.0) * 0.5 + 0.5) * self.eyeLheight_current
        pygame.draw.line(
            self.surface, col,
            (self.eyeLx - 14, int(sweep_y)),
            (self.eyeRx + self.eyeRwidth_current + 14, int(sweep_y)), 1
        )

    # ── DRONE — occhialini da pilota ─────────────────────────────────
    def _mp_draw_drone(self, ct, elapsed):
        goggle_col = (35, 35, 35)
        lens_col = (120, 190, 255)
        cy = self.eyeLy + self.eyeLheight_current // 2
        r = max(self.eyeLheight_current, self.eyeRheight_current) // 2 + 16
        centers = (
            self.eyeLx + self.eyeLwidth_current // 2,
            self.eyeRx + self.eyeRwidth_current // 2,
        )
        for ex in centers:
            pygame.draw.circle(self.surface, goggle_col, (ex, cy), r, 6)
            pygame.draw.circle(self.surface, lens_col, (ex, cy), r - 6, 3)
            # piccolo riflesso per dare l'idea della lente
            pygame.draw.circle(self.surface, (255, 255, 255), (ex - r // 3, cy - r // 3), 3)
        # ponticello centrale + fascette laterali (stile aviatore)
        pygame.draw.line(self.surface, goggle_col, (centers[0] + r, cy), (centers[1] - r, cy), 6)
        pygame.draw.line(self.surface, goggle_col, (0, cy - r // 2), (centers[0] - r, cy), 4)
        pygame.draw.line(self.surface, goggle_col, (centers[1] + r, cy), (self.screen_width, cy - r // 2), 4)

    # ── ESPLORAZIONE — radar che ruota sopra gli occhi ───────────────
    def _mp_draw_esplorazione(self, ct, elapsed):
        col = (120, 255, 150)
        cx = self.screen_width // 2
        cy = self.eyeLy - 70
        r = 28
        pygame.draw.circle(self.surface, col, (cx, cy), r, 2)
        pygame.draw.circle(self.surface, col, (cx, cy), r * 2 // 3, 1)
        angle = elapsed * 3.0
        x2 = cx + math.cos(angle) * r
        y2 = cy + math.sin(angle) * r
        pygame.draw.line(self.surface, col, (cx, cy), (x2, y2), 2)

    # ── LINEA — pista tratteggiata, occhi che "sbandano" seguendola ──
    def _mp_draw_linea(self, ct, elapsed):
        col = (255, 220, 60)
        track_y = self.eyeLy + self.eyeLheight_default + 34
        phase = int(elapsed * 40) % 24
        for x in range(-24 + phase, self.screen_width, 24):
            pygame.draw.rect(self.surface, col, (x, track_y, 14, 4))
        offset = int(math.sin(elapsed * 2.5) * 6)
        for (ex, ey, ew, eh) in (
            (self.eyeLx, self.eyeLy, self.eyeLwidth_current, self.eyeLheight_current),
            (self.eyeRx, self.eyeRy, self.eyeRwidth_current, self.eyeRheight_current),
        ):
            px = ex + ew // 2 + offset
            py = ey + eh - 6
            pygame.draw.circle(self.surface, (0, 0, 0), (px, py), 4)


MODE_PREVIEW_DRAW = {
    "generale":     ModePreviewMixin._mp_draw_generale,
    "jarvis":       ModePreviewMixin._mp_draw_jarvis,
    "drone":        ModePreviewMixin._mp_draw_drone,
    "esplorazione": ModePreviewMixin._mp_draw_esplorazione,
    "linea":        ModePreviewMixin._mp_draw_linea,
}
