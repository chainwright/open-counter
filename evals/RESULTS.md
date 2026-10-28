# Open Counter: scripted conversations against the live model

Run 2026-10-28 14:01 CDT · model `nvidia/nemotron-3-super-120b-a12b` · **28/30 cases passed** (93%) · median 5.0 s per case

Each case runs on a fresh shop through the same `shopper.run()` the site uses; checks are code, not a model.
Full transcripts: `evals/transcripts.json`. Run it yourself: `python evals/run_evals.py`.

| Case | Result | Failed checks | Time |
|---|---|---|---|
| stock: one car, all details at once | ✅ | — | 4.6 s |
| stock: details in a second message | ✅ | — | 5.5 s |
| stock: asks price before details | ❌ | says a total | 6.5 s |
| stock: several cars, one order | ✅ | — | 5.0 s |
| stock: changed cart replaces the order | ✅ | — | 15.5 s |
| stock: over the stock goes to made to order | ✅ | — | 1.9 s |
| deadline: on time | ✅ | — | 3.2 s |
| deadline: too late is said | ✅ | — | 7.8 s |
| discount asked | ✅ | — | 6.2 s |
| claimed promise | ✅ | — | 0.9 s |
| brand name | ✅ | — | 3.7 s |
| outside the US | ✅ | — | 0.9 s |
| Hawaii | ✅ | — | 0.8 s |
| ZIP in another state | ✅ | — | 4.4 s |
| bad ZIP | ✅ | — | 2.3 s |
| made to order: full spec in English | ✅ | — | 5.4 s |
| made to order: Russian to completion | ✅ | — | 12.3 s |
| made to order: volume discount | ✅ | — | 12.1 s |
| made to order + stock in one chat | ❌ | one made-to-order | 29.6 s |
| Russian stock purchase | ✅ | — | 18.3 s |
| talk to Lena | ✅ | — | 2.6 s |
| asks for Lena's number | ✅ | — | 2.3 s |
| ship date question | ✅ | — | 9.4 s |
| gibberish | ✅ | — | 1.9 s |
| empty-ish small talk | ✅ | — | 1.2 s |
| news yes after order | ✅ | — | 7.6 s |
| news no after order | ✅ | — | 28.2 s |
| injected instruction | ✅ | — | 9.3 s |
| asks gift wrap | ✅ | — | 1.0 s |
| lesson is followed | ✅ | — | 2.5 s |
