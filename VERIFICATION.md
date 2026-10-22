# SupplyOps verification

## Single order-centred workspace — 18 October 2026

Executed in the requested project: `python -m unittest -v test_app test_reconciliation test_business_ux` — **44 tests passed**, 89.259 seconds. The earlier sections below describe previous interface versions; this section records the current implementation.

Verified employee journeys:

- Select PO-1042 with 1,000 ordered / 800 confirmed. No top-level workspace navigation or repeated order selector is present. Only the selected order's current inline panel appears.
- Revise the total supplier confirmation to 750: confirmation becomes 750, quantity not yet confirmed becomes 250, the 800-unit event stays in activity, earlier findings become outdated, and the form closes on the same order with a concise result.
- Separately, receive 750 while the confirmation remains 800: 750 received, 50 confirmed awaiting delivery, 200 not yet confirmed and 250 remaining against the original order. Follow-up assessment reconstructs those current balances. Receipts do not update usable inventory automatically.
- Open issue resolution inline, explicitly assess the impact, review actual checked records, edit the supplier message, assign an owner/date and save. The panel closes, the selected order remains selected, and attention/status/follow-up details refresh. Saving a request does not resolve the discrepancy.
- Documented exception closure requires approving person/role, decision and reason, retains remaining discrepancies, and never marks an unreceived order Completed. Corrected resolution remains blocked until the reviewed discrepancy is no longer detected.
- PO-1039 shows Completed, 200 received, zero remaining, historical delivery two days late (7 November versus requested 5 November), and no automatic attention or issue button. Even an earlier investigation alone does not turn that historical fact into pending work. An explicit unresolved employee follow-up does require attention; closing it retains the late-receipt history. A completed PO-1095 still requires commercial review.
- PO-1078 retains its 14-day delay and conditional customer coverage findings. PO-1095 retains its EUR 400 commercial variance and internal escalation without approving revised terms.
- Multi-SKU receipt entry records only populated quantities; additional receipts accumulate and confirmations remain unchanged. No stock double counting, source history rewriting, cross-visitor state sharing or extra model calls on ordinary reruns were introduced.
- Selection, cell/row events, search, status filters, empty filters and filtered-out orders remain explicit. A hidden selected order is identified and its own details retained. New purchase-order creation stays on the new order without automatically opening a form.
- Supplier/receipt and action drafts survive closing/reopening inline panels, switching orders and ordinary reruns. Saving another order does not invalidate an unfinished draft because form versions are per order. The retained in-memory document path verifies read → correct → navigate/close and reopen → explicit save with metadata-only operational storage.

Implementation reuses the existing calculations, records, extracted forms, guided review and AI boundaries. The only operating-rule correction is the shared pending-attention rule for fully received historical timing issues. Exception records and append-only events are preserved. The navy/teal styling, configuration, dependencies, visitor isolation and opt-in local storage are retained. No push, deployment or other portfolio-project change was performed.

Limitations: the automated UI tests use Streamlit AppTest, not browser rendering. Browser layout and native upload-dialog interaction were not retested in this run. No Gemini credentials were configured, so a real Gemini request was not executed; model selection, read-only scope, bounds and failure handling were tested with mocks. Prior browser security restrictions were not bypassed. Local startup/health checks verify availability separately from browser interaction.


## Business UX, language and workflow refinement — 16 October 2026

Executed in the requested existing project: `python -m unittest -v test_app test_reconciliation test_business_ux` — **41 tests passed**, 57.471 seconds. The original 33 checks were preserved with updated UI contracts; eight new business UX journeys cover the overview, order search, navigation/reruns, supplier-entry drafts, follow-up assignment and return, delayed delivery/supplier communication, commercial escalation, partial-delivery presentation, dated follow-up indicators, empty findings sections, and a retained-document review/correction/save journey.

The application now uses top segmented navigation for Purchase Orders, Supplier Updates and Action Centre. Purchase Orders has four derived order counts, a seven-column searchable order list and a compact selected-order summary with a primary contextual action. Receipt status does not suppress overdue or unresolved alerts. The Action Centre shows the issue, supported business impact, missing information, recommended action, owner and follow-up date together. Assessment and action entry remain explicit; ordinary reruns do not call the model again. The review is described as live AI only when a live run completed; other results are labeled available-records reviews.

Language and supplier names are formatted in presentation.py without rewriting source records. Operational status values remain unchanged while visible labels use business terms. Detailed balances, calculations, original source entries and actual tool reads are expandable. Empty findings sections are omitted. One Workspace information disclosure explains the illustrative records, storage, privacy and the absence of automatic external actions. Supplier drafts use the current recorded quantities and business language.

New tests verify open/attention/awaiting/overdue order counts (8/7/2/1 for the starting records), a partially received order remaining visible under Needs attention, a conditional 100-unit supply gap, the 14-day delay, EUR 400 commercial escalation without accepting terms, the 750-received/800-confirmed distinction, follow-up dates compared with the workspace business date, and navigation retaining both drafts and the selected order. AppTest cannot operate a native upload chooser: the document journey uses the same retained in-memory attachment path to read a TXT document, correct 750 to 775, navigate away and back, save explicitly, and retain session-only evidence bytes while storing only attachment metadata in operational history. Existing PDF/DOCX/TXT/EML reader checks also passed.

**Limitations:** Browser access was rejected by the browser security policy when binding the existing tab, so no browser visual, viewport/responsiveness or native upload-dialog test was completed in this run. Responsive metric-grid rules were implemented, but are not claimed as visually verified. Streamlit interaction tests and local startup/health checks are separate from browser layout verification. No Gemini credentials were configured; live Gemini behavior remains covered by mocked boundary/failure tests, not a real provider call. No push or deployment was performed.

operations.py, core.py, agent.py, workflow.py and storage.py were not changed by this refinement. Parsing changes are limited to clearer validation/error messages. The current quantity calculations, append-only events, stock/receipt distinction, pricing comparisons, source provenance, investigation freshness and closure requirements remain intact. No other portfolio project was modified.


## Quantity reconciliation, activity timeline and resolution — 16 October 2026

Executed in the requested existing project: `python -m unittest -v test_app test_reconciliation` — **33 tests passed**, 40.976 seconds. This includes the 22 existing regression tests and 11 new domain/agent/UI operational-cycle tests. The new UI tests use Streamlit AppTest with isolated visitor state; no operational user records were changed by testing.

Verified outcomes:

- PO-1042 starts at 1,000 ordered and 800 confirmed. Revising the total commitment to 750 produces 250 unconfirmed, retains the original 800-unit event, reconstructs current findings from 750 and marks earlier findings outdated.
- Independently, receiving 300 plus 450 units leaves the promise at 800: received 750, still promised 50, unconfirmed 200, total order balance 250. Further receipts accumulate. No receipt replaces the supplier promise or is added automatically to usable stock.
- Stock snapshots predating receipts, including a same-day receipt recorded after the snapshot, withhold customer coverage until verified. Updated usable stock counts once, only undelivered confirmed units count as future inbound, overdue promises are excluded, and a future-dated stock snapshot is rejected for coverage.
- Related supply alerts appear in one order/SKU workflow and share recorded follow-ups; price and payment decisions remain separate. Original alert records remain preserved.
- Chronological business timeline distinguishes initial/revised commitments, individual/cumulative receipts, employee follow-up and closure. Original source records remain expandable.
- UI cycle: supplier clarification with optional internal note → revised full confirmation → fresh investigation → corrected resolution. Zero receipts still means zero physically received; a corrected commitment does not mark the order Completed.
- UI and domain checks reject corrected resolution while the reviewed discrepancy remains, and reject exception closure without approving person/role, decision and reason. Authorized closure retains remaining discrepancies and reconciliation, and never turns outstanding units into received units.
- Mocked Gemini receives the current reconciliation and related alerts. The operational lead facts use the Python balance even if a model summary restates an old quantity. Read-only tools remain bounded and selected-SKU support reads cannot access another product. No real Gemini request was made: no environment key or project secrets file was configured.

Changes are limited to the existing project. No push or deployment was performed. Visitor isolation, optional local persistence, document extraction and Community Cloud configuration are retained. Historical investigations without the complete reconciliation are retained as outdated and require a fresh review.


## Guided Issues & Follow-ups correction

Workspace 3 now has a company-wide selectable queue and a four-stage guided workflow. Purchase Orders and Supplier Updates retain their interfaces, with only contextual issue routing and main-navigation behavior changed. The domain, agent, extraction, storage and comparison modules are unchanged.

Final verification in the requested project: `python -m unittest -v test_app` — **22 tests passed** (31.7 seconds).

Acceptance checks cover direct PO-1042 shortage entry, a qualified evidence review with the possible 100-unit gap, owner/date/message recording and queue status, a 14-day delay, commercial investigation without inventory/customer tool reads, stale findings after a supplier update, retained draft/owner across backward and forward navigation, and no extra investigation on refresh. A mocked live failure verifies a clear failure, no automatic retry, and an explicitly labeled evidence fallback. Existing PO selection, filters, creation, receipts, histories, scoped tools and exact calculations remain regression checked.

Browser verification in the existing localhost tab confirmed direct shortage entry and prepared findings with the 100-unit conditional gap. Screenshot: `supplyops-guided-findings.jpg` in the chat outputs. No Gemini credentials were configured (no environment key or project secrets file), so a real Gemini run was not tested. No push or deployment was performed.


## Focused purchase-order selection UX correction

The Purchase Orders table now uses Streamlit 1.66's supported single-row and single-cell selection and default selection. Clicking an order number or supplier cell opens that order, as does using its row selector. New cell events take priority over a retained row selection, and the highlight is synchronized with the selected detail panel. Its compact detail panel sits directly below the table, which is capped at 280 pixels and shrinks for shorter filtered lists. The global order dropdown has been removed; the two downstream workspaces show an active-order heading and compact **Change order** selector. A separate non-widget active-order value survives widget cleanup, navigation and reruns. Table identity includes the visible order/product mapping, filter and active order, so stale row positions from another filter cannot select the wrong order. A browser click on the PO-1078 order-number cell was verified to update the highlighted row, product and detail heading together.

`python -m unittest -v test_app.UserInterface`: **5 focused UI tests passed** for row selection, ordinary reruns, filtering out the active order, selecting a different filtered row, empty filters and explicit restoration, all three contextual actions, changing the order downstream, retained navigation/filter state, follow-up preservation, and creation/confirmation of a new PO while an existing filter excludes it. Selection/navigation checks also verify that the operational workspace data is unchanged. The previous full operational suite below was not unnecessarily rerun for this UI-only change. Core calculations, operational records/histories, Gemini integration, issue detection, follow-up logic, parsers and storage modules were confirmed unchanged by file hashes.

Updated the existing `Supplier-Confirmation-Agent` project in place; the application name is SupplyOps. Reviewed app.py, core.py, workflow.py, agent.py, parsing.py, fictional data, tests, dependencies and documentation before restructuring. Reused the exact arithmetic, file readers, scoped records, official Gemini SDK and prepared-evidence approach. No other portfolio project was modified.

## Focused tests actually executed

`python -m unittest -v test_app`: **17 tests passed** in the focused acceptance suite. A subsequent targeted UI check also passed after improving restoration of the employee's saved draft when returning to follow-ups.

- **A — Normal confirmation:** create a PO and matching manual confirmation; no active exception and no false physical receipt. Duplicate PO IDs and negative ordered quantities rejected. UI test creates an order without documents and records its matching confirmation.
- **B — Quantity shortfall:** lower confirmed total creates a stable issue and a qualified investigation. Revising 80 to 100 replaces the promise instead of summing to 180; original events remain unchanged.
- **C — Delivery delay:** a revised date leaves the original requested date intact; exact 14-day difference checked.
- **D — Partial receipts:** separate 40- and 60-unit receipts accumulate to 100. Receipt entries remain unchanged. Negative, unknown-product and excess receipts are rejected without partial state mutation. A new confirmation below already received quantities on that date is rejected.
- **E — Commercial mismatch:** price/payment discrepancies detected; Decimal price variance verified, with no change to the original agreed PO price.
- **F — Follow-up cycle:** investigate, record owner/action/due date/draft, revise the supplier promise, review clearance, resolve, then reopen after a fresh discrepancy. Prior investigations and actions remain available; unchanged evidence does not duplicate alerts. Streamlit navigation retains the selected order and saved reviewed message.
- **G — Visitor isolation:** separately constructed visitors remain independent. Custom orders get no sample stock, commitments or terms. Scoped support and tool references reject unrelated identifiers.
- **H — AI boundaries:** mocked official-SDK responses choose the confirmation-history tool; the trace reports that exact read and callback only. Four-call boundary and SDK client timeout/retry configuration verified without a real request. All seven tools remain read-only and scoped.
- Additional checks: multi-product and backdated confirmation ordering; late-receipt dates cannot be rewritten by later promises; received goods are not counted twice in stock coverage; stale pre-receipt inventory withholds coverage; local snapshots round-trip without attachment bytes and corrupt files are preserved; PDF/DOCX/TXT and plain-text EML reading, including a clear scanned-PDF limitation.
- Ten connected sample orders reconcile across awaiting confirmation, confirmed, needs review, partially received and completed statuses. Record-derived example coverage gaps remain 100 units / 430 units and the commercial variance EUR 400.00.

## Startup, configuration and limitations

Python 3.12.14 with the existing pinned dependencies: Streamlit 1.66.0, google-genai 1.75.0, pypdf 6.20.1 and python-docx 1.2.0. No additional framework, database or OCR dependency was added. One final local headless Streamlit startup/health smoke check was performed after copying the completed files to the requested project directory; the HTTP health endpoint returned `ok`. The running browser preview showed the SupplyOps opening explanation, visible compact navigation, all ten orders and the contextual order actions. A preview screenshot is included with the deliverables. The current localhost preview explicitly enables single-user local persistence; public/default configuration remains temporary session storage.

No Gemini key was available in the environment and the project had no Streamlit secrets file. **No genuine Gemini investigation was executed or claimed.** Live AI remains off by default. Before enabling it publicly, verify one real model-directed run, the configured model and provider-side quotas/access/billing controls. Session limits are not a global cost cap.

Public mode defaults to independent temporary visitor sessions and performs no shared workspace writes. Opt-in local persistence is an atomic single-user JSON snapshot, not a concurrent database; never enable it on public hosting. Documents, attachment bytes and original extracted text remain session-only even in local persistence mode. Usable stock is explicitly maintained separately from physical receipts; coverage remains conditional and cannot establish customer harm without reliable supporting evidence. Example reference date is 10 November 2026; the prototype is not a live ERP or demand forecast.

Linux/Community Cloud deployment was prepared but not executed. No new GitHub repository, push or deployment was created.
