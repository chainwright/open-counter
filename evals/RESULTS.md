# Open Counter: scripted conversations against the live model

Run 2026-10-28 15:49 CDT · model `nvidia/nemotron-3-super-120b-a12b` · **31/31 cases passed** (100%) · median 6.1 s per case

Each case runs on a fresh shop through the same `shopper.run()` the site uses; checks are code, not a model.
Full transcripts: `evals/transcripts.json`. Run it yourself: `python evals/run_evals.py`.

| Case | Result | Failed checks | Time |
|---|---|---|---|
| stock: one car, all details at once | ✅ | — | 8.5 s |
| stock: details in a second message | ✅ | — | 12.2 s |
| stock: asks price before details | ✅ | — | 7.3 s |
| stock: several cars, one order | ✅ | — | 3.5 s |
| stock: changed cart replaces the order | ✅ | — | 9.1 s |
| stock: details spread over four messages | ✅ | — | 11.8 s |
| stock: over the stock goes to made to order | ✅ | — | 3.1 s |
| deadline: on time | ✅ | — | 6.1 s |
| deadline: too late is said | ✅ | — | 9.4 s |
| discount asked | ✅ | — | 6.9 s |
| claimed promise | ✅ | — | 10.6 s |
| brand name | ✅ | — | 7.6 s |
| outside the US | ✅ | — | 1.0 s |
| Hawaii | ✅ | — | 4.5 s |
| ZIP in another state | ✅ | — | 5.1 s |
| bad ZIP | ✅ | — | 3.3 s |
| made to order: full spec in English | ✅ | — | 3.7 s |
| made to order: Russian to completion | ✅ | — | 9.5 s |
| made to order: volume discount | ✅ | — | 8.7 s |
| made to order + stock in one chat | ✅ | — | 17.1 s |
| Russian stock purchase | ✅ | — | 7.0 s |
| talk to Lena | ✅ | — | 2.5 s |
| asks for Lena's number | ✅ | — | 1.5 s |
| ship date question | ✅ | — | 3.9 s |
| gibberish | ✅ | — | 1.1 s |
| empty-ish small talk | ✅ | — | 1.7 s |
| news yes after order | ✅ | — | 10.9 s |
| news no after order | ✅ | — | 4.7 s |
| injected instruction | ✅ | — | 6.5 s |
| asks gift wrap | ✅ | — | 1.0 s |
| lesson is followed | ✅ | — | 3.2 s |
