---
name: audio-guide
version: 1.0.0
description: "Step-by-step instructions for dubbing audio/video from a source language into a target language using Seed Audio 1.0 (ByteDance TA2A mode with @Audio1 reference). Covers the full pipeline: transcribe → analyze → translate-for-dubbing → build prompt → set API params → loop for duration match. Use this when users want to dub a clip into another language, match lip-sync, preserve emotion/pacing/voice character, handle multi-speaker content, chain long-form content (>2 min), or work with special cases like singing, whispering, or noisy environments."
metadata:
  requires:
    bins: []
---

# Seed Audio 1.0 Dubbing Prompt Guide

**CRITICAL — Before starting, first read [`../audio-guide.md`](../audio-guide.md) fully.** The guide contains the complete pipeline, reference templates, and parameter configurations.

## When to use this skill

Trigger when the user wants to:

- Dub an audio/video clip from one language to another
- Match output duration to source duration
- Preserve voice character, emotion arc, pacing, pauses, breaths, and room tone
- Handle lip-sync critical dubbing (video with on-screen speakers)
- Dub multi-speaker content (up to 3 speakers per pass)
- Chain dubbing for content longer than 2 minutes (chunk + stitch)
- Handle special cases: singing, whispering, shouting, narration, noisy environments
- Fine-tune with the `speed` parameter loop for exact duration matching

## What this skill does NOT cover

- Pure text-to-speech (TTS) without a voice reference clip — use arkcli models / Seed Audio TTS workflows
- Audio generation from scratch (no source clip) — use arkcli +gen
- Audio transcription without dubbing — use arkcli +understand (ASR)
- Model lifecycle, endpoint management, or billing for Seed Audio

## Core pipeline (5 steps)

The full guide at [`../audio-guide.md`](../audio-guide.md) details each step:

1. **Analyze source** — extract transcript, speaker count, voice descriptors, emotion arc, pace, duration, pauses, room tone
2. **Translate for dubbing** — meaning-first, syllable-count-aware translation (not literal); use contractions, preserve emotional markers and pause structure
3. **Build the Seed Audio prompt** — use the core template (`@Audio1 Dub this exact voice into {target_language}…`) or extended/multi-speaker templates
4. **Set API parameters** — `audio_urls`, `output_format`, `sample_rate`, `speed`, `pitch`, `volume`, `multilingual`
5. **Duration matching loop** — compare output duration to source, adjust `speed` by ±0.05 increments or adjust text length

## Quick template reference (from guide)

### Basic single-speaker dub
```
@Audio1 Dub this voice into {lang}, same voice character,
same emotion, same pacing, same room tone. Speak:
"{translated_text}"
```

### Multi-speaker dub
```
@Audio1 = Speaker A voice, @Audio2 = Speaker B voice
Dub both to {target_lang}. Preserve each voice exactly.
SpeakerA (@Audio1 voice, {emotion}) says: "{line1}"
SpeakerB (@Audio2 voice, {emotion}) says: "{line2}"
```

### Lip-sync dub
```
@Audio1 Dub to {lang}. Match syllable count and rhythm
exactly for lip-sync. Same voice, emotion, pace.
"{translated_text_syllable_matched}"
(set speed parameter to fine-tune duration)
```

## Long-form content (>2 min)

Seed Audio max is 2 minutes per generation. For longer content:

1. Split source at natural break points (sentences, pauses, scene changes) — each chunk ≤ 1.5 minutes
2. Dub each chunk independently using the same reference voice and prompt template
3. Stitch chunks together using the stitch workflow

## Common pitfalls

| Problem | Fix |
|---------|-----|
| Output runs over | Tighten translation or increase `speed` up to ~1.15× |
| Output ends early | Expand translation or decrease `speed` down to ~0.90× |
| Voice mismatch | Ensure `@Audio1` tag is in prompt; verify clean reference clip (single speaker, ≤30s) |
| Flat emotion | Add explicit emotion descriptors and emotional arc in prompt |
| Multi-speaker voices blend | Use separate reference clips per speaker, tag clearly with `@Audio1`/`@Audio2` |

## Sources

See original guide at [`../audio-guide.md`](../audio-guide.md) for full references (fal.ai, ByteDance Seed blog, Segmind API docs).