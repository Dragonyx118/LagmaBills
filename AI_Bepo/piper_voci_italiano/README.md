---
license: cc-by-4.0
task_categories:
- text-to-speech
language:
- it
datasets:
- kirys79/piper_italiano
pipeline_tag: text-to-speech
---

# Piper Italiano

Sto cercando di creare nuove voci e nuovi checkpoint per PiperTTS in italiano.

La fonte per il train è il **[Multilingual LibriSpeech (MLS)](https://www.openslr.org/94/)** rilasciato sotto licenza Creative Commons

A questo [link](https://huggingface.co/datasets/kirys79/piper_italiano/) troverete i dataset estratti dalla suddetta fonte e messi nel formato richiesto per addestrare i modelli di [PiperTTS](https://github.com/rhasspy/piper).


I modelli in questo report saranno tutti forniti di checkpoint per permettervi di fare finetune
Lo speaker è lo speaker ID nel dataset di MLS
Il tipo indica se il modello è da zero (From Scratch o un Fine Tune)

| Nome | Tipo | Speaker | Note  |
| :----|------| -------:| :-----|
|Aurora | From Scratch | 6807 | Marcato accento - fa pause enfatiche...
|Leonardo| From Scratch | 1595 | Probabile voce di Riccardo (modello originale di piper) ma ad una maggiore qualità
|Giorgio| Fine Tune | 8181 | Esperimento di Fine tune basato su Leonardo
