# pip install openai-whisper # per windows
# con whisper (offline)
import speech_recognition as sr

r = sr.Recognizer()

with sr.Microphone() as source:
    print("Parla...")
    audio = r.listen(source)

testo = r.recognize_whisper(audio, language="italian")
print(f"Hai detto: {testo}")