import pyttsx3

engine = pyttsx3.init()
voices = engine.getProperty('voices')

# Cerca voce italiana
for voice in voices:
    if 'italian' in voice.name.lower() or 'it' in voice.id.lower():
        engine.setProperty('voice', voice.id)
        print(f"Voce italiana trovata: {voice.name}")
        break

engine.say("Ciao, parlo in italiano!")
engine.runAndWait()