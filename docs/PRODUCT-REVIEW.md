# BUILD VERDICT

ReleaseGuard is a working production-oriented release candidate, with a deliberately bounded scope: synchronous read-only JSON transforms, one controller, PostgreSQL, and immutable published workflow arms. Final readiness depends on the exact-head CI evidence described in validation.md.

The useful complexity is in the input contract, admission fence, transactional routing/evidence/outbox, truthful raw metrics, safe fallback, encrypted retry replay, business-output contract, sample/confidence/dwell gates, and explicit failed-rollback behavior. Those features are directly needed to protect live requests.

**Broad unattended production: not yet certified. Controlled production pilot: the intended next use once the real n8n suite passes.** Sustained load, archival/retention, workflow drift checks, real installation time, and a customer deployment remain unproven. Successful synthetic CI is not customer validation.

The architecture changed from an all-in-one n8n template to **workflow pack + small self-hosted service**. The reason is concrete: the code making admission decisions must atomically own the routing revision, observation completeness, decision record, and alert queue. Putting a percentage in execution-local/static data leaves concurrency and failed rollback poorly specified. A separate universal governance framework was not introduced.

# COMMERCIAL VERDICT

There is a credible sellable problem, but **no paid demand is proven for ReleaseGuard itself**. The buyer is an automation engineer, platform operator, or agency responsible for recurring client n8n workflows where bad outputs, delays, or downstream failures have a business cost. A beginner with two hobby workflows is unlikely to value an extra service.

The strongest buying trigger is: **“A new workflow returned HTTP 200 and silently polluted results; I need to stop that release and serve a validated previous version before it reaches everyone.”** The included score/priority invariant demonstrates this exact class of failure.

| Requested independent review question | Answer grounded in this build |
|---|---|
| 1. Paid product or good template? | The JSON alone is a template. The tested service + workflow pack is a product candidate. Installation/support or a supported distribution can be sold; willingness to pay is still unknown. |
| 2. Avoid rudimentary rejection? | Submit the complete documented use case and real proof, not a webhook-to-HTTP forwarding graph. Transactional canaries, business-output checks, failure fallback, and rollback failure handling create substance. External-service dependency is still a possible Marketplace rejection reason. Adding decorative nodes would not repair that. |
| 3. High-value additions without bloat? | Shipped: input validation before metrics; per-stage failure budget; declared cross-field invariants; fresh confirmation batches; idempotent replay; Setup Doctor; live 100% baseline probes. Each addresses a specific observed failure or setup burden. |
| 4. Difference from version control, backup, deployment templates? | Those manage artifact history and movement. ReleaseGuard measures behavior on real requests, validates the returned data, and changes future routing based on evidence. It complements version history. This is not a claim that no third-party tool can implement similar logic. |
| 5. n8n architecture appropriate? | For the selected synchronous webhook scope, yes. Direct service ingress avoids an extra n8n Gateway execution; the included Gateway is useful as an n8n adapter but adds cost. The service owns durable safety; n8n owns business transforms and the entry/alert adapters. The companion dependency adds operational cost, but removes unsafe concurrent state handling from template code. |
| 6. Strongest “need this in production”? | A validly formatted but wrong business output can trigger containment while the client still receives a checked Stable response. The failure is retained for release decisions. |
| 7. Strongest “easy to build myself”? | Random split + IF errors + Slack is easy. Atomic state, stale-ticket fences, lost observations, real rollback commit failure, independent Stable baseline, retry replay, and reproducible adversarial proof are the expensive parts. Those are implemented. Setup burden remains the main reason to reject the product. |
| 8. Core now versus later? | See the implementation/defer table below. |
| 9. Packaging choice? | Template + standalone GitHub project + self-hosted service now. Avoid calling the gateway JSON a complete paid safety product. A SaaS would add hosting, data handling, tenancy, and sales costs before demand is demonstrated. |
| 10. Natural larger product? | First repeatable installation and a measured pilot; then validated-version drift protection and fleet operations; later multi-instance enforcement and optional managed control plane if buyers ask for it. |

Do not infer low competition from an unfamiliar name. The Marketplace and engineering tool ecosystem contain many deployment/versioning products. What needs validation is whether this workflow-specific behavior protection is valuable enough to justify the companion service.

Use a focused paid pilot or supported install as the first commercial experiment. Validate reduction in bad results/incident time and installation friction. Pricing is an experiment tied to those outcomes, not an invented market fact. GitHub discovery, a complete n8n template entry after readiness, and search documentation fit the distribution approach.

# UPGRADE RECOMMENDATIONS

| Capability | v0.1 status / next step |
|---|---|
| Stable/Candidate and 5→25→50→100 routing | Core implemented |
| Actual errors, p95 latency, schema/business validity | Core implemented |
| Deterministic PROMOTE/HOLD/ROLLBACK | Core implemented with sample, confidence, dwell, and fresh-batch gates |
| Read-only fallback and raw failure retention | Core implemented |
| Automatic rollback, delayed/failed commit behavior | Core implemented and adversarially exercised |
| Evidence chain, config/revision binding, alert outbox | Core implemented; independent chain anchoring is deferred |
| Replay/duplicate protection and encrypted outputs | Core implemented |
| Real n8n import/demo, setup, operations dashboard | Core build; verify with exact-head CI and measured pilot |
| Workflow published-version drift checks | Next: block promotion when the live published arm changed since registration |
| Repeatable installer/import pack | Next: reduce manual credential mapping and measure successful setup time with a new operator |
| Retention and sustained-load/soak proof | Next: preserve decision evidence, expire encrypted response cache safely, and measure real throughput |
| Tenant cohorts / business consequence segmentation | Later: only if aggregate metrics hide a real buyer's failure pattern |
| Side-effect execution/commit guard | Later: requires a concrete idempotent transactional sink; no generic “undo” promise |
| Multi-controller HA / multi-instance fleet UI | Later: requires distributed fencing and real demand |
| SaaS, billing, RBAC suites, approval frameworks | Deferred until repeat usage or a buyer requires them |

The three immediate value upgrades are **installer**, **published-workflow drift protection**, and **retention + operational soak**. They improve trust and adoption more than adding unrelated integrations or AI judgment to the release decision.

A possible sequence is v0.1 validated pilot → v0.2 repeatable install/drift/retention → v0.3 fleet operations and consequence-aware budgets → a supported managed offering after demonstrated repeat demand. Version numbers are a roadmap, not a commitment to build all tiers.

# PUBLISH VERDICT

**Do not submit the bare Gateway JSON now.** It looks like a small forwarding template because its safety logic lives in the required service. Publish the complete product use case only after the real n8n evidence is green, setup can be repeated by a new operator, and the target submission rules are verified in the current Creator Hub.

The supplied title/description/screenshots are submission materials, not an actual submission or a promise of acceptance. A real successful test matrix removes the earlier “three connected components only” weakness; it does not establish buyer demand or remove companion-service friction.

If the Creator Hub rejects a template because it requires a self-hosted service, retain the working GitHub product and tested package. Do not weaken the product into a superficial all-in-one graph just to increase node count. The distribution channel is not the product's technical validity.
