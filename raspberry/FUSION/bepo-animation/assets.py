"""
assets.py — FUSION / RoboEyes
Caricamento immagini dalla cartella images/ (stessa cartella dello script).
"""

import os
import pygame

IMG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")


def load_image(filename):
    path = os.path.join(IMG_DIR, filename)
    img = pygame.image.load(path)
    return img.convert_alpha()
