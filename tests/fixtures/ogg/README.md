Two small real Ogg Vorbis files, kept so the balrogg tests run against real
bitstreams rather than ones this project synthesised.

| file | bytes | source | licence |
|---|---:|---|---|
| `invalid_keypress.ogg` | 5,353 | MathJax 2.7 `extensions/a11y` (the copy shipped with Anaconda) | Apache-2.0 |
| `fallbackring.ogg` | 14,611 | Android SDK `platforms/android-33/data/res/raw` | Apache-2.0 |

Measured 2026-10-06 with balrogg 1.4, restored byte-identically: `invalid_keypress`
5,353 -> 2,642 (-5), `fallbackring` 14,611 -> 12,085 (-5).
