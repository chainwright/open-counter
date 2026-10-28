# Open Counter: scripted conversations against the live model

Run 2026-10-28 16:50 CDT · model `nvidia/nemotron-3-super-120b-a12b` · **32/33 cases passed** (97%) · median 4.7 s per case

Each case runs on a fresh shop through the same `shopper.run()` the site uses; checks are code, not a model.
Full transcripts: `evals/transcripts.json`. Run it yourself: `python evals/run_evals.py`.

| Case | Result | Failed checks | Time | Slowest answer |
|---|---|---|---|---|
| stock: one car, all details at once | ✅ | — | 2.0 s | 2.0 s |
| stock: details in a second message | ✅ | — | 5.9 s | 4.8 s |
| stock: asks price before details | ✅ | — | 5.1 s | 5.1 s |
| stock: several cars, one order | ✅ | — | 7.0 s | 7.0 s |
| stock: changed cart replaces the order | ✅ | — | 10.8 s | 7.0 s |
| stock: details spread over four messages | ✅ | — | 10.6 s | 5.1 s |
| colour and year only (Roma's chat) | ✅ | — | 20.4 s | 7.3 s |
| stock: over the stock goes to made to order | ✅ | — | 4.4 s | 4.4 s |
| deadline: on time | ✅ | — | 7.0 s | 7.0 s |
| deadline: too late is said | ✅ | — | 4.6 s | 4.6 s |
| discount asked | ✅ | — | 4.9 s | 4.9 s |
| a build in a colour that isn't on the shelf | ✅ | — | 1.4 s | 1.4 s |
| claimed promise | ✅ | — | 4.5 s | 4.5 s |
| brand name | ✅ | — | 4.8 s | 4.8 s |
| outside the US | ❌ | says US only | 7.0 s | 7.0 s |
| Hawaii | ✅ | — | 7.0 s | 7.0 s |
| ZIP in another state | ✅ | — | 4.1 s | 4.1 s |
| bad ZIP | ✅ | — | 1.1 s | 1.1 s |
| made to order: full spec in English | ✅ | — | 1.1 s | 1.1 s |
| made to order: Russian to completion | ✅ | — | 9.6 s | 7.0 s |
| made to order: volume discount | ✅ | — | 10.5 s | 5.4 s |
| made to order + stock in one chat | ✅ | — | 11.1 s | 6.3 s |
| Russian stock purchase | ✅ | — | 7.1 s | 6.1 s |
| talk to Lena | ✅ | — | 1.8 s | 1.8 s |
| asks for Lena's number | ✅ | — | 1.0 s | 1.0 s |
| ship date question | ✅ | — | 5.3 s | 4.1 s |
| gibberish | ✅ | — | 1.0 s | 1.0 s |
| empty-ish small talk | ✅ | — | 0.8 s | 0.8 s |
| news yes after order | ✅ | — | 4.7 s | 3.8 s |
| news no after order | ✅ | — | 3.2 s | 1.7 s |
| injected instruction | ✅ | — | 1.0 s | 1.0 s |
| asks gift wrap | ✅ | — | 1.8 s | 1.8 s |
| lesson is followed | ✅ | — | 2.8 s | 2.8 s |
