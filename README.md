# SupplyOps

An operational portfolio prototype for **Northstar Goods**, a fictional European consumer-products startup. SupplyOps connects purchase orders, supplier promises, physical receipts, exception investigations and employee follow-ups. It records commitments and decisions; it does not issue purchase orders, send supplier messages, select suppliers or approve spending.

## Start

Python 3.12:

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

No key or local model is needed. The project directory remains `Supplier-Confirmation-Agent`; the application is now **SupplyOps**.

## One purchase-order workspace

**Purchase Orders** is the only main workspace. It retains the compact summary indicators, order search, status filters, selectable order table and purchase-order creation. Select a purchase-order row to see its current position immediately below the table. The navy typography, teal accents and existing table style are retained.

The selected panel has one current balance table per order, with a row for each product: originally ordered quantity, latest total supplier confirmation, cumulative goods received, confirmed quantity awaiting delivery, quantity not yet confirmed, remaining quantity against the original order, original requested date and latest promised date. A short product summary distinguishes supplier commitments from actual deliveries.

The two central actions are:

- **Record supplier response or delivery** opens an inline form. Choose **Update supplier confirmation** or **Record goods received**. Documents are optional. Current values can be corrected before saving, and receipt entry supports multiple products while ignoring blank receipt quantities. After saving, the form closes, the same order remains selected, quantities and attention counts refresh, and a concise message explains the change.
- **Review and resolve issue** appears only for meaningful pending work. It opens the existing guided review inside the selected order: **Understand the issue → Assess the impact → Review findings → Decide next action**. Live Gemini runs only after an explicit assessment action; available-record reviews remain clearly labeled. Read-only tool scopes, exact calculations, freshness checks, supplier drafts, ownership, follow-up dates, corrected resolutions and documented exception approvals are preserved. Saving an employee action returns to the same order panel with updated attention and follow-up information. Nothing is sent or approved automatically.

Only one inline action panel is open. Ordinary reruns, closing/reopening panels and switching orders preserve unfinished entries. Form versions are per order, so saving one order does not invalidate another order's draft. If filters hide the selected order, an explicit notice identifies it and keeps its own details below the table; **Show selected order** restores it to the list without selecting a different order. Creating a purchase order keeps the newly created order selected and does not automatically open another page or form.

**Order activity** is collapsible and shows the chronological business timeline. Original source entries remain optional. Supporting stock, customer commitments and supplier terms remain available in their existing expandable section.

Fulfilment and attention are independent. A completed order's historical late receipt or delayed promise does not create new pending work unless the latest recorded employee follow-up remains unresolved. For PO-1039, 200 ordered/received means **Completed**, zero outstanding and **Needs attention: No**, with **Delivered 2 days late** retained as a historical note. An unresolved commercial dispute can still require attention on a completed order. The same domain attention rule feeds order lists, filters, summary counts and issue-action visibility; underlying exception records and receipts are preserved.

`presentation.py` formats business labels and the approved visual components; `operations.py` owns the records and shared attention rules; `supplier_updates.py` reuses the extracted supplier/receipt forms; `issue_workspace.py` renders the existing review inline. Workspace storage, privacy disclosures and Community Cloud defaults are unchanged.

Quantities ordered, latest quantities confirmed, physically received and still outstanding are separate fields. Original requested dates never change. Each receipt retains the expected date known when it was recorded, alongside its original requested date. A later supplier revision cannot make a late receipt appear on time. An over-receipt or unknown product is rejected with a reconciliation message; no partial update is saved.

Deterministic rules identify missing confirmations, changed quantities, delayed promises, price/payment changes, partial receipts, outstanding overdue deliveries, late receipts and possible customer coverage conflicts. A matching confirmation does not require AI or create an exception just because it has not been investigated. Stable issue identifiers and evidence fingerprints avoid repeated alerts for unchanged discrepancies. Resolving an issue records the employee's action; a fresh discrepancy can reopen it while retaining its prior history.

## Fictional operating environment

Each visitor starts with ten connected sample orders and one reference date: **10 November 2026**. All entered operational dates are interpreted within that reference-date workspace, rather than the host computer's current date.

| Order | Operating example |
| --- | --- |
| PO-1042 | 1,000 bottles ordered, 800 promised; 150 usable stock against 1,050 dated commitments. Conditional 100-unit gap; owner and supplier follow-up already recorded. |
| PO-1078 | 600 lunch boxes move from 12 to 26 November. 120 usable stock and 550 commitments before arrival create a possible 430-unit timing gap; an indicative alternative remains unapproved. |
| PO-1095 | 500 totes change from EUR 8.00 to EUR 8.80, a EUR 400.00 variance, with revised payment terms. |
| PO-1036 | Fully received through two separate on-time receipts. |
| PO-1039 | Fully received, but late against the original requested date. |
| PO-1051 | 100 of 300 brushes physically received; balance overdue. |
| PO-1060, PO-1071 | Matching confirmations with future delivery dates. |
| PO-1064, PO-1102 | Recent orders awaiting supplier confirmation. |

`operations.sample_workspace()` constructs the environment from fictional records, reusing the original three investigation cases. `samples/supplyops-workspace.json` is a generated reference copy. Existing readable supplier TXT samples remain available; the working app uses the records and calculations, not hardcoded live findings.

## Current reconciliation and resolution

Every order/product uses one current Python balance: ordered quantity, latest total supplier commitment, cumulative physical receipts, confirmed units still to arrive, units not confirmed by the supplier, total outstanding against the order, original delivery date and current promised date. Revised promises replace the earlier total; individual receipts accumulate. Example PO-1042: a revised total of 750 means 250 unconfirmed. A physical receipt of 750 against the unchanged 800-unit promise instead means 50 still promised, 200 unconfirmed and 250 outstanding. Neither action overwrites history.

Related operational alerts for one order/product appear as one supply situation, share one investigation and can share a recorded follow-up. Underlying alert records remain intact. Price and payment decisions stay separate. Main investigation facts are reconstructed from current records, including for live Gemini; recorded investigations retain their balance and evidence revision. Changed confirmations, receipts or support make prior findings outdated. Older investigations without the complete reconciliation are retained as outdated history.

The selected order detail is grouped into a compact order summary, **Needs attention**, primary contextual actions, expandable the current balance table, and **Order activity**. The timeline distinguishes initial and revised supplier promises, individual and cumulative receipts, follow-ups and closures. Original source entries remain expandable.

The action stage distinguishes supplier clarification (editable draft, owner, follow-up date, optional internal note), escalation for review (reason, owner, review date), follow-up assignment (action, owner, due date), resolution after correction (requires the reviewed discrepancies no longer be detected), and closure with documented approval (requires recorded approving person/role, decision and reason). Exception closure retains unresolved facts and does not imply physical fulfilment. SupplyOps records an authorization already obtained; it does not verify or grant approval. No action sends a message, issues an order or authorizes spending.

Usable stock is never increased automatically by receipts. A stock snapshot older than a receipt, including a same-day receipt recorded after that snapshot, requires verification before customer coverage can be assessed. A later verified snapshot is used once, plus only the confirmed units still to arrive; overdue promises do not count as available inbound.

## Supporting information

Under a selected purchase order, expand **Stock, customer commitments and supplier terms** to enter inventory, customer commitments, approved terms or alternative supply in editable business tables. No JSON or spreadsheets are required. New orders start with **no supporting records**; matching a sample SKU or supplier never imports sample evidence into a custom order. Explicitly empty customer commitments differ from unknown information.

Usable stock is a separate snapshot. Recording a receipt does not assume all arriving units are unallocated stock. Coverage uses that snapshot plus only the **undelivered** portion of the latest supplier total. It excludes overdue promises as available inbound and withholds coverage if a newer physical receipt makes the stock snapshot stale. Other demand, allocations, receipts and warehouse handling remain assumptions to check. Missing evidence is reported as unknown, not as confirmed downstream harm.

## Optional documents

Confirmations may attach text-based PDF, DOCX, UTF-8 TXT or plain-text EML emails. Receipts may attach PDF, DOCX or TXT. Email text can also be pasted into supplier notes. Maximum 5 MB per file; document reading allows 30 PDF pages, 24,000 extracted characters and 20 MB expanded DOCX content. Scanned PDFs and HTML-only emails need a text-based export; OCR is not included.

**Read document** performs reliable local extraction and, when enabled and needed, Gemini-assisted extraction. Initially extracted details and the original text remain expandable. The employee edits the confirmation table before saving; extraction itself never records a promise. Missing quantities/dates stay blank. The app rejects mismatched order/supplier references and unsupported currency comparisons instead of silently attaching another order's facts. Manual entry works without any attachment or model call.

Files and original extracted text remain in the visitor's session. Only checked business fields and attachment metadata enter operational records. Do not use the public demo with confidential business documents. Hosting/provider privacy terms still apply.

## State and local persistence

The default is an **independent, temporary session workspace**, suitable for Streamlit Community Cloud: no shared mutable database, account system or shared upload storage. Order interactions preserve events, investigations and follow-ups. A new browser session starts afresh; durable cross-session storage is not implied.

For a single-user local demonstration, explicitly enable:

```powershell
$env:SUPPLYOPS_LOCAL_PERSISTENCE="true"
streamlit run app.py
```

Or on macOS/Linux: `SUPPLYOPS_LOCAL_PERSISTENCE=true streamlit run app.py`.

This writes an atomic JSON snapshot to the relative `.local/workspace.json`, protected by `.gitignore`. Local records survive restarts after saving; attachments and original extracted text still do not. A corrupt snapshot produces an error and is not overwritten. This simple file store is single-user only: **do not enable it on public hosting or for concurrent visitors**. Default session mode does not call the file writer. To resume the local snapshot, keep the setting enabled. No database service is required.

## Gemini and safeguards

Set server environment variables or Streamlit Secrets:

```toml
GEMINI_API_KEY = "server-secret"
ENABLE_LIVE_AI = "true"
GEMINI_MODEL = "gemini-flash-latest"
```

Live AI is off by default even if a key exists without the enabling flag. Visitors never supply keys. `agent.py` retains the official `google-genai` SDK, model-directed function selection, argument validation and an explicit bounded loop. Seven scoped read-only capabilities retrieve the original PO, supplier confirmation history, receipt history, inventory, customer commitments, approved terms and alternative supply. No tool modifies records or sends communications. Source references appear in the expandable trace; progress reflects only executed reads. Correspondence is untrusted evidence, never an instruction source.

Exact Decimal/date calculations establish variances, ordered/confirmed/received/outstanding totals and conditional coverage. Limits remain four model calls and eight tool reads per investigation, 2,200 output tokens per response, a 20-second request timeout with a single SDK attempt, three live investigations and four assisted extraction requests per visitor session. Initial AI payloads and individual retrieved records have size limits; oversized history is reported unavailable rather than silently summarized as complete. Malformed/failed live output shows a clear failure without retrying on refresh; the employee may explicitly choose a labeled evidence summary.

Prepared examples and custom evidence summaries work without Gemini. Their actual Python record lookups are explicitly labeled as prepared activity, never fabricated live AI. Live findings remain fallible and must be reviewed by the responsible employee.

Session limits are **not a global spending cap**. Keep public AI disabled unless provider quotas, suitable access controls and billing monitoring are configured. Fresh sessions can bypass per-session allowances. Billing alerts should not be assumed to stop spending. Verify current provider controls and a supported fixed model before enabling public AI. No genuine live model run is claimed unless recorded in `VERIFICATION.md`.

## Verification and hosting

```sh
python -m unittest -v test_app test_reconciliation test_business_ux
```

The focused suite covers the requested A–H workflows, preservation of original dates, accumulation/replacement rules, issue history/reopening, isolation, local persistence, document readers, read-only agent boundaries and connected Streamlit forms. See `VERIFICATION.md` for results and limits.

For Streamlit Community Cloud, use the existing repository only when authorized, `app.py`, Python 3.12 and `requirements.txt`. Keep `.local/`, secrets and visitor data out of version control. Leave `SUPPLYOPS_LOCAL_PERSISTENCE` unset/false, and live AI disabled for a safe public demo. The code uses relative paths and Linux-compatible dependencies; no Windows utilities or Ollama are required. No new repository, push or deployment is part of this restructuring.
