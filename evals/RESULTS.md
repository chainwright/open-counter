# Open Counter: scripted conversations against the live model

Run 2026-10-31 20:03 CDT · model `nvidia/nemotron-3-super-120b-a12b` · **31/33 cases passed** (94%) · median 4.1 s per case

Each case runs on a fresh shop through the same `shopper.run()` the site uses; checks are code, not a model.
Full transcripts: `evals/transcripts.json`. Run it yourself: `python evals/run_evals.py`.

| Case | Result | Failed checks | Time | Slowest answer |
|---|---|---|---|---|
| stock: one car, all details at once | ✅ | — | 2.9 s | 2.9 s |
| stock: details in a second message | ✅ | — | 6.1 s | 4.9 s |
| stock: asks price before details | ✅ | — | 3.0 s | 3.0 s |
| stock: several cars, one order | ✅ | — | 4.1 s | 4.1 s |
| stock: changed cart replaces the order | ✅ | — | 12.3 s | 7.0 s |
| stock: details spread over four messages | ✅ | — | 10.6 s | 3.0 s |
| colour and year only (Roma's chat) | ❌ | says a price, no stalling | 9.3 s | 5.0 s |
| stock: over the stock goes to made to order | ✅ | — | 4.1 s | 4.1 s |
| deadline: on time | ✅ | — | 4.7 s | 4.7 s |
| deadline: too late is said | ❌ | warns | 3.3 s | 3.3 s |
| discount asked | ✅ | — | 5.1 s | 5.1 s |
| a build in a colour that isn't on the shelf | ✅ | — | 1.2 s | 1.2 s |
| claimed promise | ✅ | — | 5.0 s | 5.0 s |
| brand name | ✅ | — | 4.4 s | 4.4 s |
| outside the US | ✅ | — | 0.0 s | 0.0 s |
| Hawaii | ✅ | — | 5.4 s | 5.4 s |
| ZIP in another state | ✅ | — | 2.7 s | 2.7 s |
| bad ZIP | ✅ | — | 1.2 s | 1.2 s |
| made to order: full spec in English | ✅ | — | 1.3 s | 1.3 s |
| made to order: Russian to completion | ✅ | — | 8.3 s | 5.4 s |
| made to order: volume discount | ✅ | — | 6.9 s | 5.8 s |
| made to order + stock in one chat | ✅ | — | 11.7 s | 6.6 s |
| Russian stock purchase | ✅ | — | 8.4 s | 7.0 s |
| talk to Lena | ✅ | — | 1.6 s | 1.6 s |
| asks for Lena's number | ✅ | — | 0.8 s | 0.8 s |
| ship date question | ✅ | — | 5.1 s | 3.3 s |
| gibberish | ✅ | — | 0.9 s | 0.9 s |
| empty-ish small talk | ✅ | — | 0.7 s | 0.7 s |
| news yes after order | ✅ | — | 2.5 s | 1.3 s |
| news no after order | ✅ | — | 4.8 s | 3.4 s |
| injected instruction | ✅ | — | 1.6 s | 1.6 s |
| asks gift wrap | ✅ | — | 1.2 s | 1.2 s |
| lesson is followed | ✅ | — | 1.0 s | 1.0 s |
