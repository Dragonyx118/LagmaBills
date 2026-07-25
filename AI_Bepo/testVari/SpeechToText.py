# sudo apt-get install python3-pyaudio portaudio19-dev flac
# pip install SpeechRecognition
# arecord -l  # lista dispositivi di registrazione
# whisper è lento = panelli down = = testo = r.recognize_whisper(audio, model="tiny", language="italian")
import speech_recognition as sr

r = sr.Recognizer()

with sr.Microphone() as source:
    print("Parla...")
    audio = r.listen(source)

try:
    #testo = r.recognize_google(audio, language="it-IT")
    testo = r.recognize_whisper(audio, model="tiny", language="italian") 
    print(f"Hai detto: {testo}")
except sr.UnknownValueError:
    print("Non ho capito")
except sr.RequestError:
    print("Errore di connessione con il servizio")