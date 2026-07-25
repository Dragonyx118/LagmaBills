import asyncio
import logging
from server import Audio_Receiver
import res_whisp
import cervello
import command_sender

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)

async def main():
    res_whisp.start()  # avvia worker audio — una volta sola
    queue = asyncio.Queue()
    receiver = Audio_Receiver(on_audio_ready=res_whisp.on_audio_ready)

    await asyncio.gather(
        receiver.start(),                                    # WebSocket audio
        cervello.run(queue),                                      # LLM + logica
        command_sender.run(queue),  
        return_exceptions=True
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Fermato.")