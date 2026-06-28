# Extraction Risk Matrix

## Risk Scale
- Low: display-only or pure UI movement with focused tests.
- Medium: UI movement plus state/view-model shaping.
- High: data writes, runtime services, replay identity, readiness/scoring, process control, or broker-adjacent language.

## Matrix

| Area | Current Location | Risk | Why | Recommended Timing | Required Proof |
| --- | --- | --- | --- | --- | --- |
| Gateway page | `app.py` 499-610 | Low | Display-only navigation and labels. | R002 | `tests.test_autonomy_gateway`, object-name preservation. |
| Argus Machine console shell | `app.py` 611-881 | Low | Placeholder data, disabled controls, no service calls. | R002 | Gateway tests plus locked-order assertions. |
| Argus placeholder data | `app.py` 237-339 | Low | Static data for display-only shell. | R002 | Ladder population test. |
| Trade Plan Ladder display | `app.py` 745-765, 849-881 | Low/Medium | Display-only now, but future real TradePlan data increases risk. | R002/R006 | Ladder field tests and safety-language checks. |
| Navigation rail | `app.py` 882-969 | Medium | Page routing has side effects for Watchlist refresh and Replay autoload. | After R002 | Navigation tests. |
| Daily Workflow pure step logic | `app.py` 4869-5249 | Medium | Mostly pure, but user-facing sequence and blocker text matter. | R003 | Daily Workflow tests for every state. |
| Daily Workflow dialog | `app.py` 2985-3077, 4750-5301 | Medium | Action buttons route into real app methods. | R003 | Daily Workflow GUI tests and quick-action assertions. |
| Theme/QSS | `app.py` 5251-5286, 6084-6140, 7558-7772 | Medium | Visual states are safety language; bad colors/copy can mislead. | R004 | Screenshot proof plus GUI tests. |
| Watermark/common components | `app.py` 341-388 | Low | Generic widgets. | R004 or cleanup | compileall and touched UI tests. |
| Research report panels | `app.py` 6273-7541 | Medium | Mostly read-only but large surface and report DTO assumptions. | Later | report-focused smoke/compile checks. |
| Replay/story helpers | `app.py` 3127-3354, 5669-5966 | Medium/High | Replay identity/audit text must remain exact. | Later | replay/navigation tests and identity text checks. |
| Watchlist Center view model | `app.py` 1028-1082, 1669-1744 | Medium/High | Table shaping is near review and entry-plan writes. | Later | watchlist and Daily Workflow tests. |
| Candidate table/detail | `app.py` 2005-2185, 2301-2397 | High | Candidate selection, news stack, row states, entry-plan fields. | Later | dashboard GUI tests. |
| Entry-plan persistence | `app.py` 2398-2493 | High | Writes operator discipline state. | After service boundary | entry-plan tests. |
| Review decisions | `app.py` 2494-2599 | High | Writes review state and affects watchlist workflow. | After service boundary | review workflow tests. |
| Watchlist report generation | `app.py` 2600-2624 | High | Writes watchlist/report and triggers manual capture. | After service boundary | storage/watchlist tests. |
| Scanner execution | `app.py` 2229-2293 | High | Provider calls, news fetch, scoring, runtime state. | After service boundary | scanner/provider/scoring tests. |
| Capture save/load/autocapture | `app.py` 3354-3872 | High | Capture identity, scheduling, raw capture files, replay state. | Much later | capture/replay/storage tests. |
| Evidence/active monitor process | `app.py` 1243-1900 | High | Starts/stops background process and updates evidence runtime files. | Later | active monitor/evidence tests. |
| Readiness/outcome research | `app.py` 3094-3126, 4284-4749 | Medium/High | Read-only UI but readiness language is protected. | Later | outcome/readiness tests. |
| Score breakdown identity/persistence | `app.py` 4101-4169 | High | Historical identity and score explanation integrity. | Later | score-breakdown tests. |

## Protected-Path Review Rule
Every extraction task must confirm changed paths against its allowed list before commit. Any change to scoring, readiness, replay identity, storage/schema, broker/order behavior, package files, or generated data is a stop condition unless Steven explicitly approved it.

## R002 Risk Conclusion
R002 is the lowest-risk/highest-value first move. It removes a visible UI island from `app.py` while preserving safety labels and existing tests. It also avoids all high-risk service, persistence, scoring, replay, and broker areas.
