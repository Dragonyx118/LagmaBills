"""
sequences/wakeword.py — FUSION / RoboEyes
Animazione "Hey Nova" (SEQ_WAKEWORD): occhi che si stringono e si
concentrano, poi microfono + onde sonore finché non arriva
"wakeword_end" dal listener (socket_bridge.py / mqtt_bridge.py).
Questa sequenza NON fa parte della lista idle: si attiva solo su
comando esplicito.
"""

import math
import pygame

from constants import MAINCOLOR


class WakewordSequenceMixin:
    def _run_wakeword_sequence(self, ct):
        """
        Fasi:
          'focus'  (0..0.6s): occhi si stringono e si avvicinano al centro
          'listen' (0.6s→∞) : occhi aperti fissi dritti, microfono + onde sonore

        La sequenza rimane attiva finché wakeword.py non manda "wakeword_end"
        (che imposta next_mood=DEFAULT e fa uscire dal sequence).
        """
        d = self.seq_data
        elapsed = (ct - self.seq_timer) / 1000.0

        if 'phase' not in d:
            d['phase']      = 'focus'
            d['phase_timer'] = ct
            d['mic_pulse']  = 0.0
            d['ring_radii'] = []
            d['ring_timer'] = ct

        phase = d['phase']

        # ── Fase "focus": stringe e centra gli occhi ──────────────
        if phase == 'focus':
            t = min(1.0, elapsed / 0.6)
            self.eyeLheight_next = int(self.eyeLheight_default * (1 - t * 0.45))
            self.eyeRheight_next = int(self.eyeRheight_default * (1 - t * 0.45))
            squeeze = int(t * 30)
            self.eyeLx_next = self.eyeLx_default + squeeze
            self.eyeRx_next = self.eyeRx_default - squeeze
            if elapsed >= 0.6:
                d['phase']       = 'listen'
                d['phase_timer'] = ct

        # ── Fase "listen": occhi aperti fissi + microfono ─────────
        elif phase == 'listen':
            listen_elapsed = (ct - d['phase_timer']) / 1000.0

            # occhi tornano centrati e leggermente più aperti
            self.eyeLheight_next = int(self.eyeLheight_default * 1.05)
            self.eyeRheight_next = int(self.eyeRheight_default * 1.05)
            self.eyeLx_next = self.eyeLx_default
            self.eyeRx_next = self.eyeRx_default

            # sopracciglia dritte concentrate
            brow_y = self.eyeLy - 16
            gap    = 8
            pygame.draw.line(
                self.surface, MAINCOLOR,
                (self.eyeLx + gap, brow_y),
                (self.eyeLx + self.eyeLwidth_current - gap, brow_y), 5)
            pygame.draw.line(
                self.surface, MAINCOLOR,
                (self.eyeRx + gap, brow_y),
                (self.eyeRx + self.eyeRwidth_current - gap, brow_y), 5)

            # ── microfono stilizzato ───────────────────────────────
            d['mic_pulse'] += 0.08
            pulse = 0.92 + 0.08 * abs(math.sin(d['mic_pulse'] * 2.5))

            cx   = self.screen_width  // 2
            base = self.screen_height - 30

            mic_w = int(28 * pulse)
            mic_h = int(46 * pulse)
            mic_x = cx - mic_w // 2
            mic_y = base - mic_h - 38

            # ombra
            pygame.draw.rect(self.surface, (40, 40, 40),
                             (mic_x + 3, mic_y + 3, mic_w, mic_h),
                             border_radius=mic_w // 2)
            # corpo bianco
            pygame.draw.rect(self.surface, (230, 230, 230),
                             (mic_x, mic_y, mic_w, mic_h),
                             border_radius=mic_w // 2)
            # griglia (3 linee nere)
            for li in range(3):
                ly = mic_y + mic_h // 4 + li * (mic_h // 4)
                pygame.draw.line(self.surface, (80, 80, 80),
                                 (mic_x + 5, ly), (mic_x + mic_w - 5, ly), 1)

            # stand verticale
            stand_top = mic_y + mic_h
            stand_bot = base - 6
            pygame.draw.line(self.surface, (180, 180, 180),
                             (cx, stand_top), (cx, stand_bot), 3)
            # base a T
            pygame.draw.line(self.surface, (180, 180, 180),
                             (cx - 16, stand_bot), (cx + 16, stand_bot), 4)

            # ── onde sonore concentriche ───────────────────────────
            if ct - d['ring_timer'] > 500:
                d['ring_radii'].append({'r': 0.0, 'born': ct})
                d['ring_timer'] = ct

            new_rings = []
            for ring in d['ring_radii']:
                age   = (ct - ring['born']) / 1000.0
                r     = int(age * 70)
                alpha = int(255 * max(0.0, 1.0 - age / 1.4))
                if alpha > 0 and r > 0:
                    s = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
                    pygame.draw.arc(
                        s, (255, 255, 255, alpha),
                        (2, 2, r * 2, r * 2),
                        math.radians(200), math.radians(340), 2)
                    mic_cx   = cx
                    mic_cy   = mic_y + mic_h // 2
                    self.surface.blit(s, (mic_cx - r - 2, mic_cy - r - 2))
                    new_rings.append(ring)
            d['ring_radii'] = new_rings

            # ── testo "In ascolto..." ──────────────────────────────
            if 'font_listen' not in d:
                d['font_listen'] = pygame.font.SysFont('monospace', 18, bold=False)
            blink_char = '●' if int(listen_elapsed * 2) % 2 == 0 else '○'
            txt = d['font_listen'].render(
                f'{blink_char}  In ascolto...', True, (160, 160, 160))
            self.surface.blit(
                txt, (cx - txt.get_width() // 2, mic_y - 28))

        return True  # rimane attiva finché non arriva wakeword_end

