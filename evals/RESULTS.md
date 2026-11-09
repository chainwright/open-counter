# Open Counter: scripted conversations against the live model

Run 2026-11-08 18:39 CST · model `nvidia/nemotron-3-super-120b-a12b` · **32/33 cases passed** (97%) · median 2.7 s per case

Each case runs on a fresh shop through the same `shopper.run()` the site uses; checks are code, not a model.
Full transcripts: `evals/transcripts.json`. Run it yourself: `python evals/run_evals.py`.

| Case | Result | Failed checks | Time | Slowest answer |
|---|---|---|---|---|
| stock: one car, all details at once | ✅ | — | 1.8 s | 1.8 s |
| stock: details in a second message | ✅ | — | 4.3 s | 2.9 s |
| stock: asks price before details | ✅ | — | 3.2 s | 3.2 s |
| stock: several cars, one order | ✅ | — | 4.8 s | 4.8 s |
| stock: changed cart replaces the order | ✅ | — | 9.7 s | 5.8 s |
| stock: details spread over four messages | ✅ | — | 10.8 s | 4.1 s |
| colour and year only (Roma's chat) | ❌ | names the car, says a price | 7.2 s | 3.1 s |
| stock: over the stock goes to made to order | ✅ | — | 4.2 s | 4.2 s |
| deadline: on time | ✅ | — | 5.7 s | 5.7 s |
| deadline: too late is said | ✅ | — | 3.5 s | 3.5 s |
| discount asked | ✅ | — | 3.5 s | 3.5 s |
| a build in a colour that isn't on the shelf | ✅ | — | 0.0 s | 0.0 s |
| claimed promise | ✅ | — | 2.7 s | 2.7 s |
| brand name | ✅ | — | 4.6 s | 4.6 s |
| outside the US | ✅ | — | 0.0 s | 0.0 s |
| Hawaii | ✅ | — | 0.4 s | 0.4 s |
| ZIP in another state | ✅ | — | 5.8 s | 5.8 s |
| bad ZIP | ✅ | — | 1.2 s | 1.2 s |
| made to order: full spec in English | ✅ | — | 0.0 s | 0.0 s |
| made to order: Russian to completion | ✅ | — | 2.3 s | 2.3 s |
| made to order: volume discount | ✅ | — | 1.7 s | 1.7 s |
| made to order + stock in one chat | ✅ | — | 5.8 s | 3.1 s |
| Russian stock purchase | ✅ | — | 5.4 s | 4.2 s |
| talk to Lena | ✅ | — | 0.8 s | 0.8 s |
| asks for Lena's number | ✅ | — | 1.7 s | 1.7 s |
| ship date question | ✅ | — | 5.9 s | 3.5 s |
| gibberish | ✅ | — | 0.7 s | 0.7 s |
| empty-ish small talk | ✅ | — | 0.6 s | 0.6 s |
| news yes after order | ✅ | — | 4.0 s | 2.9 s |
| news no after order | ✅ | — | 2.0 s | 1.1 s |
| injected instruction | ✅ | — | 2.0 s | 2.0 s |
| asks gift wrap | ✅ | — | 0.9 s | 0.9 s |
| lesson is followed | ✅ | — | 0.6 s | 0.6 s |
