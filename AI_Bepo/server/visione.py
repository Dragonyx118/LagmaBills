"""
vision_pipeline.py
──────────────────
Pipeline visuale leggera per Nova.

Strati (attivabili indipendentemente):
  1. YOLO nano      → oggetti + bbox  (sempre attivo se camera disponibile)
  2. MediaPipe      → pose corpo / mani          (MEDIAPIPE=true in .env)
  3. ONNX face det. → visi + landmark emozione   (ONNX_FACE=true in .env)

Output:
  • aggiorna video_context in cervello.py
  • mette VisionResult in vision_queue per arm_controller.py

Requisiti pip:
  ultralytics          # yolov8 nano
  mediapipe            # opzionale
  onnxruntime          # opzionale
  opencv-python
  numpy
"""

import asyncio
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# configurazione da .env
# -----------------------------------------------------------------------

CAMERA_INDEX   = int(os.getenv("CAMERA_INDEX",   "0"))
FRAME_WIDTH    = int(os.getenv("FRAME_WIDTH",    "640"))
FRAME_HEIGHT   = int(os.getenv("FRAME_HEIGHT",   "480"))
YOLO_MODEL     = os.getenv("YOLO_MODEL",         "yolov8n.pt")   # nano = ~6 MB
YOLO_CONF      = float(os.getenv("YOLO_CONF",    "0.45"))
YOLO_IMGSZ     = int(os.getenv("YOLO_IMGSZ",     "320"))         # 320 = più veloce
FRAME_SKIP     = int(os.getenv("FRAME_SKIP",     "2"))           # elabora 1 frame ogni N

# -----------------------------------------------------------------------
# struttura risultato visione
# -----------------------------------------------------------------------

@dataclass
class BBox:
    """Bounding box normalizzata [0-1] rispetto al frame."""
    x1: float
    y1: float
    x2: float
    y2: float
    label: str
    conf: float

    @property
    def cx(self) -> float:
        """Centro X normalizzato."""
        return (self.x1 + self.x2) / 2

    @property
    def cy(self) -> float:
        """Centro Y normalizzato."""
        return (self.y1 + self.y2) / 2

    @property
    def area(self) -> float:
        """Area normalizzata — proxy della distanza."""
        return (self.x2 - self.x1) * (self.y2 - self.y1)


@dataclass
class VisionResult:
    """Tutto quello che vision_pipeline sa in un dato frame."""
    timestamp: float = field(default_factory=time.time)

    # YOLO
    objects: list[BBox] = field(default_factory=list)

    # MediaPipe              (TODO)
    pose_landmarks: Optional[list] = None
    hand_landmarks: Optional[list] = None

    # ONNX face              (TODO)
    faces:   Optional[list[BBox]] = None
    emotion: Optional[str]        = None

    def best_object(self, label: Optional[str] = None) -> Optional[BBox]:
        """
        Ritorna l'oggetto più vicino (area maggiore = più vicino).
        Se label è specificato filtra per classe.
        """
        pool = [o for o in self.objects if label is None or o.label == label]
        if not pool:
            return None
        return max(pool, key=lambda b: b.area)

    def object_labels(self) -> list[str]:
        return list({o.label for o in self.objects})


# -----------------------------------------------------------------------
# code condivise (importabili da cervello e arm_controller)
# -----------------------------------------------------------------------

# asyncio.Queue — arm_controller la consuma
vision_queue: asyncio.Queue = None  # inizializzata in init()


def _init_queue(loop: asyncio.AbstractEventLoop):
    global vision_queue
    vision_queue = asyncio.Queue(maxsize=5)


# -----------------------------------------------------------------------
# caricamento modelli
# -----------------------------------------------------------------------

_yolo = None


def _load_yolo():
    global _yolo
    if _yolo is not None:
        return
    try:
        from ultralytics import YOLO
        _yolo = YOLO(YOLO_MODEL)
        _yolo.fuse()   # fonde BN + Conv → più veloce su CPU
        logger.info(f"YOLO caricato: {YOLO_MODEL}")
    except Exception as e:
        logger.error(f"YOLO non caricato: {e}")


def _load_mediapipe():
    pass  # TODO


def _load_onnx_face():
    pass  # TODO


# -----------------------------------------------------------------------
# inferenza YOLO
# -----------------------------------------------------------------------

def _run_yolo(frame_bgr: np.ndarray) -> list[BBox]:
    if _yolo is None:
        return []
    h, w = frame_bgr.shape[:2]
    try:
        results = _yolo.predict(
            frame_bgr,
            imgsz=YOLO_IMGSZ,
            conf=YOLO_CONF,
            verbose=False
        )
        boxes = []
        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                label = r.names[int(box.cls[0])]
                conf  = float(box.conf[0])
                boxes.append(BBox(
                    x1 / w, y1 / h, x2 / w, y2 / h,
                    label, conf
                ))
        return boxes
    except Exception as e:
        logger.warning(f"YOLO predict errore: {e}")
        return []


# -----------------------------------------------------------------------
# inferenza MediaPipe
# -----------------------------------------------------------------------

def _run_mediapipe(frame_bgr: np.ndarray):
    pass  # TODO


# -----------------------------------------------------------------------
# inferenza ONNX face
# (compatibile con modelli tipo scrfd, retinaface onnx export)
# adatta il pre/post processing al tuo modello specifico
# -----------------------------------------------------------------------

def _run_onnx_face(frame_bgr: np.ndarray):
    pass  # TODO


# -----------------------------------------------------------------------
# aggiorna video_context in cervello.py
# -----------------------------------------------------------------------

def _update_cervello(result: VisionResult):
    """
    Aggiorna il dizionario video_context importato da cervello.
    Import lazy per evitare circolarità.
    """
    try:
        import cervello
        cervello.aggiorna_contesto_video({
            "oggetti":  result.object_labels() or None,
            "emozione": None,   # TODO: ONNX face
            "pose":     None,   # TODO: MediaPipe
            "persona":  None,   # TODO: ArcFace
        })
    except Exception as e:
        logger.warning(f"aggiorna_contesto_video errore: {e}")


def _pose_summary(pose_lm) -> Optional[str]:
    pass  # TODO: MediaPipe


# -----------------------------------------------------------------------
# thread di cattura + elaborazione
# -----------------------------------------------------------------------

_stop_event = threading.Event()
_loop_ref: Optional[asyncio.AbstractEventLoop] = None


def _pipeline_thread():
    """
    Thread sincrono — cattura frame, elabora, manda risultati alla queue asyncio.
    """
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        logger.error(f"Camera {CAMERA_INDEX} non disponibile")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # minimizza latenza buffer
    logger.info(f"Camera {CAMERA_INDEX} aperta ({FRAME_WIDTH}x{FRAME_HEIGHT})")

    frame_count = 0

    while not _stop_event.is_set():
        ok, frame = cap.read()
        if not ok:
            logger.warning("Frame non letto dalla camera")
            time.sleep(0.05)
            continue

        frame_count += 1
        if frame_count % FRAME_SKIP != 0:
            continue

        result = VisionResult()

        # ── YOLO ──────────────────────────────────────────────────────
        result.objects = _run_yolo(frame)

        # ── MediaPipe ─────────────────────────────────────────────────
        # TODO

        # ── ONNX face ─────────────────────────────────────────────────
        # TODO

        # ── aggiorna cervello ─────────────────────────────────────────
        _update_cervello(result)

        # ── manda a vision_queue per arm_controller ───────────────────
        if _loop_ref is not None and vision_queue is not None:
            try:
                asyncio.run_coroutine_threadsafe(
                    _put_vision(result), _loop_ref
                )
            except Exception:
                pass

    cap.release()
    logger.info("Camera rilasciata")


async def _put_vision(result: VisionResult):
    """Mette il risultato nella queue, scarta se piena (non blocca)."""
    try:
        vision_queue.put_nowait(result)
    except asyncio.QueueFull:
        # scarta il frame vecchio e metti il nuovo
        try:
            vision_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            vision_queue.put_nowait(result)
        except:
            pass


# -----------------------------------------------------------------------
# API pubblica
# -----------------------------------------------------------------------

def start(loop: asyncio.AbstractEventLoop):
    """
    Avvia la pipeline visuale.
    Chiamare da main.py passando il loop asyncio corrente.
    """
    global _loop_ref
    _loop_ref = loop
    _init_queue(loop)

    _load_yolo()

    t = threading.Thread(target=_pipeline_thread, daemon=True, name="vision_pipeline")
    t.start()
    logger.info("vision_pipeline avviata")


def stop():
    _stop_event.set()