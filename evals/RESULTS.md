# Open Counter: scripted conversations against the live model

Run 2026-10-28 16:47 CDT · model `nvidia/nemotron-3-super-120b-a12b` · **30/33 cases passed** (91%) · median 4.6 s per case

Each case runs on a fresh shop through the same `shopper.run()` the site uses; checks are code, not a model.
Full transcripts: `evals/transcripts.json`. Run it yourself: `python evals/run_evals.py`.

| Case | Result | Failed checks | Time | Slowest answer |
|---|---|---|---|---|
| stock: one car, all details at once | ✅ | — | 1.5 s | 1.5 s |
| stock: details in a second message | ✅ | — | 7.3 s | 6.0 s |
| stock: asks price before details | ✅ | — | 3.4 s | 3.4 s |
| stock: several cars, one order | ✅ | — | 7.0 s | 7.0 s |
| stock: changed cart replaces the order | ❌ | every answer within 8 s | 23.7 s | 9.6 s |
| stock: details spread over four messages | ✅ | — | 14.8 s | 5.0 s |
| colour and year only (Roma's chat) | ✅ | — | 9.8 s | 4.4 s |
| stock: over the stock goes to made to order | ✅ | — | 6.7 s | 6.7 s |
| deadline: on time | ✅ | — | 4.3 s | 4.3 s |
| deadline: too late is said | ✅ | — | 1.3 s | 1.3 s |
| discount asked | ✅ | — | 5.0 s | 5.0 s |
| a build in a colour that isn't on the shelf | ✅ | — | 1.5 s | 1.5 s |
| claimed promise | ✅ | — | 5.3 s | 5.3 s |
| brand name | ✅ | — | 7.0 s | 7.0 s |
| outside the US | ✅ | — | 1.4 s | 1.4 s |
| Hawaii | ✅ | — | 2.4 s | 2.4 s |
| ZIP in another state | ✅ | — | 5.8 s | 5.8 s |
| bad ZIP | ✅ | — | 1.4 s | 1.4 s |
| made to order: full spec in English | ✅ | — | 1.6 s | 1.6 s |
| made to order: Russian to completion | ❌ | Russian | 7.4 s | 5.4 s |
| made to order: volume discount | ✅ | — | 7.2 s | 6.3 s |
| made to order + stock in one chat | ❌ | every answer within 8 s | 15.5 s | 9.1 s |
| Russian stock purchase | ✅ | — | 8.0 s | 6.1 s |
| talk to Lena | ✅ | — | 3.4 s | 3.4 s |
| asks for Lena's number | ✅ | — | 1.0 s | 1.0 s |
| ship date question | ✅ | — | 6.5 s | 4.2 s |
| gibberish | ✅ | — | 1.0 s | 1.0 s |
| empty-ish small talk | ✅ | — | 1.1 s | 1.1 s |
| news yes after order | ✅ | — | 4.6 s | 3.0 s |
| news no after order | ✅ | — | 4.2 s | 3.0 s |
| injected instruction | ✅ | — | 1.3 s | 1.3 s |
| asks gift wrap | ✅ | — | 1.0 s | 1.0 s |
| lesson is followed | ✅ | — | 6.3 s | 6.3 s |
