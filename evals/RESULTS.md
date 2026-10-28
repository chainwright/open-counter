# Open Counter: scripted conversations against the live model

Run 2026-10-28 13:53 CDT · model `nvidia/nemotron-3-super-120b-a12b` · **29/30 cases passed** (97%) · median 5.2 s per case

Each case runs on a fresh shop through the same `shopper.run()` the site uses; checks are code, not a model.
Full transcripts: `evals/transcripts.json`. Run it yourself: `python evals/run_evals.py`.

| Case | Result | Failed checks | Time |
|---|---|---|---|
| stock: one car, all details at once | ✅ | — | 7.3 s |
| stock: details in a second message | ✅ | — | 13.2 s |
| stock: asks price before details | ✅ | — | 5.2 s |
| stock: several cars, one order | ✅ | — | 3.7 s |
| stock: changed cart replaces the order | ✅ | — | 11.5 s |
| stock: over the stock goes to made to order | ✅ | — | 1.8 s |
| deadline: on time | ✅ | — | 9.3 s |
| deadline: too late is said | ✅ | — | 8.6 s |
| discount asked | ✅ | — | 4.3 s |
| claimed promise | ✅ | — | 5.6 s |
| brand name | ✅ | — | 4.2 s |
| outside the US | ✅ | — | 0.5 s |
| Hawaii | ✅ | — | 3.4 s |
| ZIP in another state | ✅ | — | 3.0 s |
| bad ZIP | ✅ | — | 7.0 s |
| made to order: full spec in English | ✅ | — | 3.7 s |
| made to order: Russian to completion | ❌ | stripes kept | 11.5 s |
| made to order: volume discount | ✅ | — | 9.1 s |
| made to order + stock in one chat | ✅ | — | 20.6 s |
| Russian stock purchase | ✅ | — | 12.1 s |
| talk to Lena | ✅ | — | 1.5 s |
| asks for Lena's number | ✅ | — | 1.6 s |
| ship date question | ✅ | — | 6.0 s |
| gibberish | ✅ | — | 0.7 s |
| empty-ish small talk | ✅ | — | 0.5 s |
| news yes after order | ✅ | — | 11.3 s |
| news no after order | ✅ | — | 10.0 s |
| injected instruction | ✅ | — | 1.3 s |
| asks gift wrap | ✅ | — | 0.6 s |
| lesson is followed | ✅ | — | 2.8 s |
