# Controlled demo fixtures

Window 0 owns this README; other windows may create **only** `fixtures/<their_slug>.json`.

Fixture data must be explicitly marked `source_mode: "fixture"`, must not masquerade as real API output, and must never contain secrets, private guest lists, or invented prices described as live. Real captured responses belong under ignored `raw/` and must respect platform terms/privacy.

Fixture files should be deterministic, local and small. Every fixture has an accompanying test exercising parsing into `conferge.core.schemas`. Prefer JSON records based on validated sources; imaginary records need obviously fictional labels.
