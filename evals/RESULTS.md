# Open Counter: scripted conversations against the live model

Run 2026-10-28 16:27 CDT · model `nvidia/nemotron-3-super-120b-a12b` · **31/32 cases passed** (97%) · median 2.5 s per case

Each case runs on a fresh shop through the same `shopper.run()` the site uses; checks are code, not a model.
Full transcripts: `evals/transcripts.json`. Run it yourself: `python evals/run_evals.py`.

| Case | Result | Failed checks | Time |
|---|---|---|---|
| stock: one car, all details at once | ✅ | — | 1.8 s |
| stock: details in a second message | ✅ | — | 4.6 s |
| stock: asks price before details | ✅ | — | 3.8 s |
| stock: several cars, one order | ✅ | — | 7.0 s |
| stock: changed cart replaces the order | ✅ | — | 9.4 s |
| stock: details spread over four messages | ✅ | — | 10.9 s |
| colour and year only (Roma's chat) | ❌ | names the car | 5.9 s |
| stock: over the stock goes to made to order | ✅ | — | 4.5 s |
| deadline: on time | ✅ | — | 4.8 s |
| deadline: too late is said | ✅ | — | 1.2 s |
| discount asked | ✅ | — | 2.1 s |
| claimed promise | ✅ | — | 7.0 s |
| brand name | ✅ | — | 5.7 s |
| outside the US | ✅ | — | 1.1 s |
| Hawaii | ✅ | — | 4.0 s |
| ZIP in another state | ✅ | — | 1.2 s |
| bad ZIP | ✅ | — | 0.6 s |
| made to order: full spec in English | ✅ | — | 1.0 s |
| made to order: Russian to completion | ✅ | — | 7.3 s |
| made to order: volume discount | ✅ | — | 7.6 s |
| made to order + stock in one chat | ✅ | — | 10.3 s |
| Russian stock purchase | ✅ | — | 7.7 s |
| talk to Lena | ✅ | — | 0.7 s |
| asks for Lena's number | ✅ | — | 1.1 s |
| ship date question | ✅ | — | 2.4 s |
| gibberish | ✅ | — | 1.2 s |
| empty-ish small talk | ✅ | — | 0.4 s |
| news yes after order | ✅ | — | 2.0 s |
| news no after order | ✅ | — | 1.9 s |
| injected instruction | ✅ | — | 1.0 s |
| asks gift wrap | ✅ | — | 0.7 s |
| lesson is followed | ✅ | — | 2.5 s |
