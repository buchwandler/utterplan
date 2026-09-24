from __future__ import annotations

from dataclasses import dataclass

from utterplan import PauseConfig, PlannerConfig


@dataclass(frozen=True)
class MigrationCase:
    name: str
    text: str
    config: PlannerConfig


PLAIN = PlannerConfig(language="en-us", document_format="plain")
IDENTITY = PlannerConfig(language="en-us", document_format="plain", text_preparation="identity")
AUTO = PlannerConfig(language="en-us", document_format="plain", pauses=PauseConfig(mode="auto"))
SSMD = PlannerConfig(language="en-us")
SSMD_IDENTITY = PlannerConfig(language="en-us", text_preparation="identity")

CASES = (
    MigrationCase("plain_single", "A single sentence.", PLAIN),
    MigrationCase("plain_sentences", "One sentence. Two sentences.", PLAIN),
    MigrationCase("plain_paragraphs", "First paragraph.\n\nSecond paragraph.", PLAIN),
    MigrationCase("plain_empty", "", PLAIN),
    MigrationCase("plain_whitespace", "  \n  ", PLAIN),
    MigrationCase("plain_unicode_punctuation", "Café déjà vu. Привет мир.", PLAIN),
    MigrationCase("plain_quotation", 'She said, "Hello." Then left.', PLAIN),
    MigrationCase("spokenform_numbers", "Dr. Smith bought 5 kg.", SSMD),
    MigrationCase("spokenform_date_time", "The meeting is on 2024-05-12 at 10:30.", SSMD),
    MigrationCase("spokenform_abbreviation", "Prof. Jones called at 8 p.m.", SSMD),
    MigrationCase("multilingual_preparation", 'Hello [Bonjour]{lang="fr"}.', SSMD),
    MigrationCase("clausal_comma", "When ready, begin the test.", AUTO),
    MigrationCase("parenthetical", "The battery (still warm) worked.", AUTO),
    MigrationCase("ssmd_language", 'Hello [Bonjour]{lang="fr"}.', SSMD_IDENTITY),
    MigrationCase("ssmd_pronunciation", '[GIF]{ph="dʒɪf"}.', SSMD_IDENTITY),
    MigrationCase("ssmd_voice", '[Hello]{voice="narrator"}.', SSMD_IDENTITY),
    MigrationCase(
        "ssmd_header_voice",
        """---
ssmd_version: "0.9"
voice_bindings:
  narrator: voice-a
---
[Hello]{voice="narrator"}.""",
        SSMD_IDENTITY,
    ),
    MigrationCase("ssmd_prosody", '[fast]{rate="120%" pitch="high" volume="80%"}.', SSMD_IDENTITY),
    MigrationCase("ssmd_emphasis", '[important]{emphasis="strong"}.', SSMD_IDENTITY),
    MigrationCase("ssmd_audio", '[sound]{src="clip.wav" desc="sound"}.', SSMD_IDENTITY),
    MigrationCase("ssmd_break", "Hello ...c world", SSMD_IDENTITY),
    MigrationCase("ssmd_marker", "One. @mark Two.", SSMD_IDENTITY),
    MigrationCase(
        "ssmd_pause_defaults",
        """---
ssmd_version: "0.9"
pause_defaults:
  sentence: 400ms
---
One. Two.""",
        SSMD_IDENTITY,
    ),
    MigrationCase(
        "ssmd_language_detection",
        """---
ssmd_version: "0.9"
language_detection:
  mode: auto
  languages: [de, en]
---
Hallo.""",
        SSMD_IDENTITY,
    ),
)
