import numpy as np
from resemblyzer import VoiceEncoder, preprocess_wav
from pathlib import Path
import sounddevice as sd
from resemblyzer.demo_utils import plot_similarity_matrix, plot_histograms  # dai demo 1 e 5
import threading
import queue
from collections import deque
from faster_whisper import WhisperModel


Base_Dir=Path(__file__).parent



Chunk_seconds=5
Sample=16000
similarity=0.910

sample=Sample*Chunk_seconds

try:
    Whisper=WhisperModel(
        "medium",
        device="cuda",
        compute_type="float32"
    )
    
    
except:
    Whisper=WhisperModel(
        "medium",
        device="cpu",
        compute_type="float32"
    )
    
    
buffer=deque(maxlen=sample)

try:
    encoder=VoiceEncoder("cuda")
except:
    encoder=VoiceEncoder("cpu")
    

ground_truth_dir=Base_Dir/"Voci"/"ground"
gt_f=list(ground_truth_dir.glob("*.wav"))
gt_names=[f.stem for f in gt_f]
gt_wavs=[preprocess_wav(f) for f in gt_f]
gt_emb=np.array([encoder.embed_utterance(w) for w in gt_wavs])

def normalize(v):
    return v/np.linalg.norm(v)


gt_emb=np.array([normalize(e) for e in gt_emb])


def demo15(chunk_audio):
    chunk_embed=encoder.embed_utterance(chunk_audio)
    chunk_embed=normalize(chunk_embed)
    
    sims=np.dot(gt_emb,chunk_embed)
    max_i=sims.argmax()
    max_s=sims[max_i]
    print(f"Max similarity: {max_s:.3f} con {gt_names[max_i]}")
    return max_s>similarity,gt_names[max_i]

    
    
    
audio_queue=queue.Queue()
   
def audio_callback(indata,frames,time,status):
    global buffer
    
    buffer.extend(indata[:,0])
    # Se siamo in registrazione, accumulo audio
    
    if len(buffer)>=sample:
            audio=np.array(buffer)
            buffer.clear()

            audio_queue.put(audio)
    
       
          
    
def worker():
    while True:
            audio_np=audio_queue.get()
            audio_pc=preprocess_wav(audio_np) 
                        # Speaker verification
            accepted=demo15(audio_pc)
            if accepted:
                print("Utente Riconosciuto")
                segments,_=Whisper.transcribe(
                    audio_np.astype(np.float32),
                    language="it"
                )
                text="".join([seg.text for seg in segments])
                print(text)
            else:
                print("Utente non riconosciuto")
                
            audio_queue.task_done()
            
           
def run_whisper():

    threading.Thread(target=worker,daemon=True).start()

    with sd.InputStream(
          channels=1,
          samplerate=Sample,
          callback=audio_callback
      ):    
       print("listening")
       while True:
           sd.sleep(1000)


