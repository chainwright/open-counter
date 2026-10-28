# Open Counter: scripted conversations against the live model

Run 2026-10-28 16:05 CDT · model `nvidia/nemotron-3-super-120b-a12b` · **30/32 cases passed** (94%) · median 4.8 s per case

Each case runs on a fresh shop through the same `shopper.run()` the site uses; checks are code, not a model.
Full transcripts: `evals/transcripts.json`. Run it yourself: `python evals/run_evals.py`.

| Case | Result | Failed checks | Time |
|---|---|---|---|
| stock: one car, all details at once | ✅ | — | 6.1 s |
| stock: details in a second message | ✅ | — | 7.0 s |
| stock: asks price before details | ❌ | says a total | 1.1 s |
| stock: several cars, one order | ✅ | — | 6.2 s |
| stock: changed cart replaces the order | ✅ | — | 13.8 s |
| stock: details spread over four messages | ✅ | — | 12.6 s |
| colour and year only (Roma's chat) | ❌ | no stalling | 6.7 s |
| stock: over the stock goes to made to order | ✅ | — | 3.6 s |
| deadline: on time | ✅ | — | 4.1 s |
| deadline: too late is said | ✅ | — | 5.1 s |
| discount asked | ✅ | — | 1.5 s |
| claimed promise | ✅ | — | 4.8 s |
| brand name | ✅ | — | 4.3 s |
| outside the US | ✅ | — | 0.9 s |
| Hawaii | ✅ | — | 0.6 s |
| ZIP in another state | ✅ | — | 4.6 s |
| bad ZIP | ✅ | — | 5.2 s |
| made to order: full spec in English | ✅ | — | 2.1 s |
| made to order: Russian to completion | ✅ | — | 11.8 s |
| made to order: volume discount | ✅ | — | 11.7 s |
| made to order + stock in one chat | ✅ | — | 14.0 s |
| Russian stock purchase | ✅ | — | 6.3 s |
| talk to Lena | ✅ | — | 1.8 s |
| asks for Lena's number | ✅ | — | 1.3 s |
| ship date question | ✅ | — | 3.1 s |
| gibberish | ✅ | — | 0.9 s |
| empty-ish small talk | ✅ | — | 0.8 s |
| news yes after order | ✅ | — | 5.9 s |
| news no after order | ✅ | — | 5.9 s |
| injected instruction | ✅ | — | 4.9 s |
| asks gift wrap | ✅ | — | 0.8 s |
| lesson is followed | ✅ | — | 0.8 s |
