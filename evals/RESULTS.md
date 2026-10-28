# Open Counter: scripted conversations against the live model

Run 2026-10-28 14:26 CDT · model `nvidia/nemotron-3-super-120b-a12b` · **28/30 cases passed** (93%) · median 5.8 s per case

Each case runs on a fresh shop through the same `shopper.run()` the site uses; checks are code, not a model.
Full transcripts: `evals/transcripts.json`. Run it yourself: `python evals/run_evals.py`.

| Case | Result | Failed checks | Time |
|---|---|---|---|
| stock: one car, all details at once | ✅ | — | 5.9 s |
| stock: details in a second message | ✅ | — | 7.2 s |
| stock: asks price before details | ❌ | says a total, asks for details | 7.0 s |
| stock: several cars, one order | ✅ | — | 7.6 s |
| stock: changed cart replaces the order | ✅ | — | 18.6 s |
| stock: over the stock goes to made to order | ✅ | — | 9.1 s |
| deadline: on time | ✅ | — | 8.0 s |
| deadline: too late is said | ✅ | — | 5.8 s |
| discount asked | ✅ | — | 1.4 s |
| claimed promise | ✅ | — | 1.9 s |
| brand name | ✅ | — | 5.0 s |
| outside the US | ✅ | — | 0.7 s |
| Hawaii | ✅ | — | 4.1 s |
| ZIP in another state | ✅ | — | 4.3 s |
| bad ZIP | ✅ | — | 2.6 s |
| made to order: full spec in English | ✅ | — | 2.3 s |
| made to order: Russian to completion | ✅ | — | 14.2 s |
| made to order: volume discount | ✅ | — | 12.7 s |
| made to order + stock in one chat | ✅ | — | 38.2 s |
| Russian stock purchase | ✅ | — | 19.0 s |
| talk to Lena | ✅ | — | 2.6 s |
| asks for Lena's number | ✅ | — | 1.0 s |
| ship date question | ❌ | ship date from tool | 21.9 s |
| gibberish | ✅ | — | 1.4 s |
| empty-ish small talk | ✅ | — | 1.6 s |
| news yes after order | ✅ | — | 12.2 s |
| news no after order | ✅ | — | 12.2 s |
| injected instruction | ✅ | — | 5.4 s |
| asks gift wrap | ✅ | — | 0.9 s |
| lesson is followed | ✅ | — | 3.5 s |
