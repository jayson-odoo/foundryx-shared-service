# Step 1: API confirmation (27/11/2026)

Real Anthropic API, key from the login keychain, engine `claude-procedural` through
`python -m planner3d_worker.claude_cli`. Ledger: `step1-ledger.jsonl` (one line per call).
Prices: Sonnet 5.5 US$2 / US$10, Opus 5.5 US$4 / US$20 per MTok in / out.

| Run | Product | Model | Calls | In tokens | Out tokens | US$ | Wall time | Faces | Dims error mm | Scout estimate US$ |
|---|---|---|---|---|---|---|---|---|---|---|
| A (first prompt) | SRTWC286-SH WC | Opus, sdf | 3 | 20,985 | 15,868 | 0.401 | 6 min 24 s | 498,888 | 0 / 0 / 0 | 0.55 |
| A (first prompt) | SRTWT5903 tap | Sonnet | 3 | 18,975 | 6,188 | 0.100 | 54 s | 1,102 | 0 / 0 / 0 | 0.09 |
| A (first prompt) | SRTWT5903 tap | Opus | 3 | 18,790 | 7,303 | 0.221 | 1 min 15 s | 4,938 | 0 / 0 / 0 | n/a |
| B (fixed prompt) | SRTWC286-SH WC | Opus, sdf | 3 | 20,443 | 14,702 | 0.376 | 4 min 08 s | 48,332 | 0 / 0 / 0 | 0.55 |
| B (fixed prompt) | SRTWT5903 tap | Sonnet | 3 | 20,560 | 6,557 | 0.107 | 57 s | 2,114 | 0 / 0 / 0 | 0.09 |

Step 1 total: 15 calls, US$1.20.

Findings:
- Real cost is at or under the scout estimate: WC on Opus US$0.38 to 0.40 (scout 0.55), tap on Sonnet
  US$0.10 to 0.11 (scout 0.09). Per call: Sonnet US$0.02 to 0.05, Opus US$0.06 to 0.14.
- Every model is the exact catalogue size (0 mm error on all three axes).
- First prompt: the WC came out at about 500k faces with a grainy surface; the tap on Sonnet left the round
  base standing upright. The fixed prompt (triangle budget, smoothing + decimation, cylinder axis rule,
  per-part bbox in the refine turn) gives a smooth 48k-face WC and a correct tap base.
- Taps: Opus makes rounded, filleted spout and lever; Sonnet still makes them boxy. Pilot routes the tap
  category to Opus (about US$0.22 per product).
- WC run B kept 2 of 3 versions (one version failed in the sandbox and its error went to the next turn).

Images: `*_compare.png` (run A) and `*_v2_compare.png` (run B): catalogue photo, then front, side and
three-quarter renders of candidate 1.
