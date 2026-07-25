import asyncio
import threading
import logging
import numpy as np
from collections import deque
from dotenv import load_dotenv
import os
import res_whisp

load_dotenv()

logger=logging.getLogger(__name__)

SAMPLE_RATE:int=int(os.getenv("Sample_rate","16000"))

CHUNK_SECONDS:int=int(os.getenv("Chunk_seconds","7"))
CHUNK_SAMPLES:int=SAMPLE_RATE*CHUNK_SECONDS

ws_port:int=int(os.getenv("ws_port","8765"))
ws_host:str=os.getenv("ws_host","0.0.0.0")


class Audio_Receiver:
    def __init__(
        self,
        on_audio_ready,
        sample_rate:int=SAMPLE_RATE,
        chunk_sample:int=CHUNK_SAMPLES,
        host:str=ws_host,
        port:int=ws_port
    ):
     
     self.on_audio_ready=on_audio_ready
     self.sample=sample_rate
     self.chunk_sample=chunk_sample
     self.host=host
     self.port=port
     
     self._buffer=deque()
     self._lock=asyncio.Lock()
     self._running=False
     self._server=None
     
     self._client_count=0
     self._chunk_received=0
     
    async def start(self):
        import websockets
        self._running=True
        logger.info(f"websocket acceso {self.port} {self.host}")
        async with websockets.serve(
        self._handle_client,
        self.host,
        self.port,
        max_size=None,
        ping_interval=20,
        ping_timeout=10
        
        ) as server:
         self._server=server
         await asyncio.Future()
     
    async def stop(self):
        self._running=False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        logger.info("fermato")
            
    async def _handle_client(self,websocket):
        client_addr=websocket.remote_address
        self._client_count+=1
        logging.info(f"porta e ip rasberry {client_addr}")
        try:
            async for message in websocket:
                if not isinstance(message,bytes):
                    logging.warning("formato non corretto")
                    continue
                await self._process_chunk(message)
        except Exception as e:
            logging.warning("errore nell'arrivo del messaggio")
        finally:
            self._client_count-=1
            logging.info("fatto")
            
            
    async def _process_chunk(self,pcm_bytes):
         self._chunk_received+=1
         try:
             audio_np_int16=np.frombuffer(pcm_bytes,dtype=np.int16)
         except ValueError as e:
             logging.warning("errore pcm corrotto")
             return
         audio_np_float32=audio_np_int16.astype(np.float32)/32768
         async with self._lock:
             self._buffer.extend(audio_np_float32.tolist())
             if len(self._buffer)>=self.chunk_sample:
                 audio_chunk=np.array([self._buffer.popleft() for _ in range(self.chunk_sample)],dtype=np.float32)
                 
                 await self.on_audio_ready(audio_chunk)
                 
                 
                 
async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    )
   
    receiver=Audio_Receiver(on_audio_ready=res_whisp.on_audio_ready)
    print(f"Server WebSocket audio avviato su ws://0.0.0.0:{ws_port}")
    print(f"Chunk size: {CHUNK_SECONDS}s ({CHUNK_SAMPLES} campioni)")
    print("Aspetto connessione dal Raspberry... (Ctrl+C per uscire)")
    try:
        res_whisp.start()
        await receiver.start()
    except Exception as e:
        await receiver.stop()
        print("fermato")
    
        
if __name__ =="__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print("server fermato")
    