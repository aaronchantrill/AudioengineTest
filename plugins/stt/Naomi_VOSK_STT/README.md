---
id: VOSK_STT
label: VOSK STT
title: VOSK STT - Speech to Text
type: stts
description: "Allows Naomi to use VOSK for active listening"
source: https://github.com/aaronchantrill/Naomi_VOSK_STT/blob/main/README.md
meta:
  - property: og:title
    content: "VOSK STT - Speech to Text"
  - property: og:description
    content: "Allows Naomi to use VOSK for active listening"
---

# VOSK STT - Speech to Text

This plugin allows [Naomi](https://projectnaomi.com/) to use [VOSK](https://alphacephei.com/vosk/)  to convert speech to text. This module does not
currently do language model adaptation, so it is not yet suitable for special
applications or custom words, but it is already very good, at least in English.

If anyone is interested in helping me adapt the language and/or acoustic
model, the instructions are at https://alphacephei.com/vosk/adaptation

To activate this plugin, change your profile.yml file to set the active and/or
special listener engines and point VOSK to its like this:

```
active_stt:
  engine: VOSK STT
special_stt:
  engine: VOSK STT
```

If you are speaking English, this plugin should download an English language
model and associate it with VOSK automatically.

If you are not speaking English, you must also download a language model and
associate it with VOSK manually:
```
VOSK STT:
  model: /home/naomi/.config/naomi/vosk/vosk-model-small-en-us-0.15
```
<EditPageLink/>
