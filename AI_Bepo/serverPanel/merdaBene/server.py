import asyncio
import logging
import numpy as np
from collections import deque
from dotenv import load_dotenv
import os
import res_whisp

load_dotenv()

logger = logging.getLogger(__name__)

SAMPLE_RATE   = int(os.getenv("Sample_rate",   "16000"))
CHUNK_SECONDS = int(os.getenv("Chunk_seconds", "7"))
CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_SECONDS

ws_port = int(os.getenv("ws_port", "8765"))
ws_host = os.getenv("ws_host", "0.0.0.0")

# Minimo campioni per processare il buffer al flush (evita rumori brevissimi)
MIN_FLUSH_SAMPLES = SAMPLE_RATE * 1  # almeno 1 secondo


class Audio_Receiver:
    def __init__(
        self,
        on_audio_ready,
        sample_rate:  int = SAMPLE_RATE,
        chunk_sample: int = CHUNK_SAMPLES,
        host: str = ws_host,
        port: int = ws_port,
    ):
        self.on_audio_ready = on_audio_ready
        self.sample         = sample_rate
        self.chunk_sample   = chunk_sample
        self.host           = host
        self.port           = port

        self._buffer       = deque()
        self._lock         = asyncio.Lock()
        self._running      = False
        self._server       = None
        self._client_count = 0
        self._chunk_received = 0

    async def start(self):
        import websockets
        self._running = True
        logger.info(f"WebSocket in ascolto su {self.host}:{self.port}")
        async with websockets.serve(
            self._handle_client,
            self.host,
            self.port,
            max_size=None,
            ping_interval=20,
            ping_timeout=10,
        ) as server:
            self._server = server
            await asyncio.Future()

    async def stop(self):
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        logger.info("Server fermato")

    async def _handle_client(self, websocket):
        client_addr = websocket.remote_address
        self._client_count += 1
        logger.info(f"Client connesso: {client_addr}")

        # Buffer locale per questa sessione — reset ad ogni nuova connessione
        async with self._lock:
            self._buffer.clear()

        try:
            async for message in websocket:
                if not isinstance(message, bytes):
                    logger.warning("Messaggio non-bytes ignorato")
                    continue
                await self._process_chunk(message)

        except Exception as e:
            logger.warning(f"Errore client {client_addr}: {e}")

        finally:
            self._client_count -= 1
            # FIX BUG 1: flush del buffer residuo alla disconnessione
            # così l'audio < 7s viene processato ugualmente
            await self._flush_buffer()
            logger.info(f"Client disconnesso: {client_addr} — buffer flushed")

    async def _process_chunk(self, pcm_bytes: bytes):
        self._chunk_received += 1
        try:
            audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        except ValueError:
            logger.warning("PCM corrotto, chunk ignorato")
            return

        audio_f32 = audio_int16.astype(np.float32) / 32768.0

        async with self._lock:
            self._buffer.extend(audio_f32.tolist())

            # Invia chunk completi da CHUNK_SAMPLES mentre il buffer è pieno
            while len(self._buffer) >= self.chunk_sample:
                audio_chunk = np.array(
                    [self._buffer.popleft() for _ in range(self.chunk_sample)],
                    dtype=np.float32,
                )
                logger.info(f"Chunk completo ({self.chunk_sample} campioni) → pipeline")
                await self._send(audio_chunk)

    async def _flush_buffer(self):
        """
        Invia il buffer residuo alla disconnessione del client.
        Evita di perdere l'audio quando lo stream dura meno di CHUNK_SECONDS.
        """
        async with self._lock:
            n = len(self._buffer)
            if n < MIN_FLUSH_SAMPLES:
                logger.info(f"Buffer residuo troppo corto ({n} campioni), scartato")
                self._buffer.clear()
                return

            audio_chunk = np.array(list(self._buffer), dtype=np.float32)
            self._buffer.clear()

        logger.info(f"Flush buffer residuo: {n} campioni ({n/self.sample:.2f}s) → pipeline")
        await self._send(audio_chunk)

    async def _send(self, audio_chunk: np.ndarray):
        """Passa l'audio alla callback con gestione errori."""
        try:
            await self.on_audio_ready(audio_chunk)
        except Exception as e:
            logger.warning(f"on_audio_ready errore: {e}")


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    res_whisp.start()
    receiver = Audio_Receiver(on_audio_ready=res_whisp.on_audio_ready)

    print(f"Server WebSocket su ws://0.0.0.0:{ws_port}")
    print(f"Chunk size: {CHUNK_SECONDS}s ({CHUNK_SAMPLES} campioni)")
    print(f"Flush minimo: {MIN_FLUSH_SAMPLES} campioni (1s)")
    print("In attesa del Raspberry... (Ctrl+C per uscire)")

    try:
        await receiver.start()
    except KeyboardInterrupt:
        await receiver.stop()
        print("Fermato.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Server fermato.")