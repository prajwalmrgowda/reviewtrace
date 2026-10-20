# ReviewTrace

A NextLeap RAGs & Context Engineering prototype for ChatGPT customer feedback: review intelligence → weekly product pulse → sourced renewal-fee explanation → human-approved **real MCP calls to Google Docs or local notes, plus a local email draft**.

**Google Docs setup:** see [GOOGLE_DOCS_SETUP.md](GOOGLE_DOCS_SETUP.md). The API integration is implemented; a live connection requires your credentials and target document. Gmail remains unconnected.

## Run locally

Use Python **3.11+** (tested here with Python 3.14). No credentials are required for offline analysis and local destinations. Google Docs mode requires configured service-account credentials and an Editor-shared document.

```bash
python3 -m venv .venv
source .venv/bin/activate
# Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open the printed local URL, normally http://localhost:8501. Use the bundled sample or upload one UTF-8 CSV with required `date` (YYYY-MM-DD), `review_text`, `source_url`; optional `review_id`, `platform`, `rating` (1–5). Limits: 5 MB, 10,000 rows, 20,000 characters per review. Invalid rows produce actionable errors rather than silently disappearing. Duplicate text from the same source is counted once. CSV-supplied `theme` labels are accepted only from the five allowed categories. Never upload private customer data without appropriate authorization.

Choose an 8–12 week window. The sample defaults to **20 October 2026**, covering 15 August–19 October 2026. Future and older rows are excluded relative to the selected analysis date. At least three classified themes and three reviews are required for a complete pulse. At least two distinct reviews must connect renewal/cancellation with charges/refunds (not subscription cancellation alone) before the fee workflow can execute.

### Optional AI mode

Enter an OpenAI API key in the sidebar and click **Analyze with OpenAI**. This sends review text to OpenAI to assign one of five bounded category labels using `gpt-4o-mini`. The key is password-masked and is not written to disk. API calls happen only on that explicit button, not on every approval or download rerun. Cached category labels are session-local and tied to the uploaded bytes. API failure falls back to offline rules with a visible warning. No paid live API call was made during verification; the API path is tested with a mocked SDK response.

Offline mode uses deterministic keyword grouping, not semantic clustering. Outputs are deterministic templates populated from evidence. Neither mode is embedding/vector RAG; policy context is a curated snapshot of two official documents. Do not claim live retrieval, autonomous AI drafting, or semantic clustering. This is an intentionally bounded context-engineering demonstration, with an optional AI intelligence layer.

## Expanded review dataset

The default [reviews_sample.csv](reviews_sample.csv) now contains **512 reviews**: 500 exact US App Store reviews collected on 20 October 2026 plus the original 12 legacy entries. No reviews were invented, repeated to pad counts, or selected by rating/fee keywords. The new US entries are from 17–19 October, inside the 12-week window; they do not span the whole window. Apple provides updated timestamps, which may represent edits rather than original publication.

[DATASET.md](DATASET.md) explains collection, limits and evidence. [US-only CSV](data/reviews_app_store_us.csv), [UK-only CSV](data/reviews_app_store_gb.csv) (500 additional reviews, not included in the default), [original 12](data/reviews_legacy_12.csv), JSON snapshots and SHA-256 manifests are retained. The US-only dataset has one explicit renewal/refund report; the UK set has no matching recurring signal. Do not claim either source alone proves recurring renewal/refund confusion.

Recollect public feeds with `python collect_reviews.py --country us --pages 10 --output data/reviews_app_store_us.csv` (network required). This refreshes the collection files/manifest, not the merged default or derived outputs. Keep a copy of previous snapshots before recollecting. Then deliberately rebuild the default and rerun the analysis if you change sources.

Most new feedback is general praise, non-English text, or outside the five issue categories. Offline rules disclose these as unclassified instead of pretending every review supports an issue. Optional AI labeling has the same category limits and can force a category; use care interpreting that mode. Three fee reports in a nonrandom dataset do not imply a measured population trend.

## What the sample identifies

Five categories are available: billing/refunds, usage limits, upload reliability, answer accuracy, and paid access/account state. The UI ranks the top three, shows three source-linked verbatim quotes, and separately displays the fee-supporting reviews.

The specific fee pain point is **ChatGPT subscription renewal charges and cancellation/refund expectations**, supported by **APPLE_14680607843, R010 and R011**. These users report forgetting cancellation before renewal and requesting or seeking refunds. Other payment or access complaints are not counted as proof of that policy confusion. User reports establish a pain point, not a verified billing defect or refund entitlement. Three matching reports among 512 entries establish recurrence only within this convenience sample, not a frequent or population-wide problem.

The generated weekly pulse is strictly **under 250 whitespace-delimited words**, includes the top three themes/counts, exactly three verbatim excerpts with URLs, a key observation, and three product action ideas. Excerpts are contiguous segments of relevant sentences in the original text, with no invented ellipsis inside the quotes. The full review remains visible in the UI.

The explainer has **six bullets**, two official source links in a separate paragraph, and **Last checked: 2026-10-20**. That date records the policy verification, independent of the analysis end date. Changing the date picker does not pretend to re-check policy. Refresh the policy snapshot and date after reviewing both official pages when submitting in future.

## MCP approval and destinations

The interface uses theme-aware metric cards, numbered workflow tabs and persistent Google Docs connection status. The optional AI settings and technical previews are collapsed by default.

In **4. Save & export**:

1. Inspect the exact notes JSON, subject, and email body.
2. Choose local notes or Google Docs in the sidebar, verify the destination, then check the explicit approval checkbox.
3. Click **Append notes & create draft**.

Before approval, the client cannot start a server or perform a write. The client binds approval to a SHA-256 digest of the exact notes entry, subject, body, notes destination and Google document ID. A data/output change produces a new approval checkbox. After approval, `workflow.py` starts `mcp_server.py` using stdio, initializes a real MCP `ClientSession`, and invokes `append_product_notes` then `create_email_draft`. Both tools require a process-scoped approval token, validate the payload, and reject a digest mismatch. Tool responses and a 60-second workflow timeout are checked.

This is an application approval gate, not a hardened multi-tenant authorization service: a person who can change the local code/environment controls the local server. Never expose this local stdio server as an unauthenticated network service.

**The tools are real MCP tools. Notes can use a real Google Doc or a local simulation; email remains local.**

- Notes in local mode: structured JSON appended inside `internal_product_notes.md`.
- Notes in Google Docs mode: the same JSON appended through the official Docs API; a `google_doc_receipt.json` records the document link and API acknowledgment.
- Email: RFC 822 `weekly_product_pulse_draft.eml`, with `X-Unsent: 1`, no recipient, and no transport/send function.
- **Google Docs requires explicit configuration; no live connection is claimed until checked. Notion and Gmail are not connected. No email is sent automatically or manually by this app.** Opening the `.eml` in a mail client is a separate user action.

UI outputs use a separate temporary directory per Streamlit session. Download buttons remain available after completion and across reruns. A completed payload cannot be run twice in the same session. Files are ephemeral; download them before leaving. The CLI defaults to `outputs/` unless overridden. Two writes are sequential, not transactional: if draft creation fails, notes may already be appended. Inspect outputs before retrying to avoid duplicate notes. Direct approved calls intentionally append on each invocation; email creation overwrites the prior draft at its fixed path.

Google Docs is implemented using service-account authentication and the Docs scope, with destination-bound approval. Google API requests are tested with mocks; no live Doc was available for verification. Personal Google OAuth sign-in and Gmail Drafts integration are not implemented. See the setup guide for credentials, permissions, read-only connection checks and hosting restrictions.

## Submission artifacts and verification

- [Weekly product pulse](weekly_product_pulse.md)
- [Fee explainer](fee_explainer.md)
- [Notes snippet](demo_examples/notes_snippet_example.md) and [exact JSON](demo_examples/notes_entry_example.json)
- [Email draft](demo_examples/email_draft_example.eml)
- [Reviews CSV](reviews_sample.csv)
- [Requirement-by-requirement audit](ASSIGNMENT_AUDIT.md)
- [Source verification record](SOURCE_VERIFICATION.md)

Preview the sample payload without writing files:

```bash
python generate_examples.py
```

After reviewing the preview, explicitly approve regenerating local example artifacts through actual MCP:

```bash
python generate_examples.py --approve-local-demo
```

This appends a local demo notes entry to a fresh temporary document and replaces the example snapshots; no external tools or accounts are touched.

Run all checks:

```bash
python -m unittest discover -s tests -v
python -m pip check
python -m compileall -q app.py engine.py workflow.py mcp_server.py google_docs.py generate_examples.py
```

Tests cover malformed input, date windows, duplicate evidence, theme bounds, exact sourced quotes, word/bullet/link/date constraints, fee recurrence, bounded mocked LLM responses, approval denial/stale payloads, actual stdio tool discovery/calls, append behavior, RFC email contents, and Streamlit approval, execution, duplicate prevention and state reset.

## Source list (6 essential URLs)

1. Collected US App Store review feed (page 1 of 10): https://itunes.apple.com/us/rss/customerreviews/page=1/id=6448311069/sortby=mostrecent/json
2. Legacy Google Play review source: https://play.google.com/store/apps/details?gl=IN&hl=en-GB&id=com.openai.chatgpt
3. Renewal/refund complaint (R010): https://www.reddit.com/r/OpenAI/comments/1wwjyfk/chatgpt_pro_renewal_refund_request_within_minutes/
4. Renewal/refund complaint (R011): https://www.reddit.com/r/ChatGPT/comments/1x9xj3l/refunding_not_possible/
5. Official cancellation policy: https://help.openai.com/en/articles/7232927-canceling-your-chatgpt-subscription
6. Official refund policy: https://help.openai.com/en/articles/7232895-how-do-i-request-a-refund-for-my-chatgpt-subscription

The CSV preserves additional row-level URLs. It is one CSV of **mixed public app-store and social feedback**, not an app-store-only export. The default sample contains 500 newly collected US App Store reviews plus 12 legacy entries and is nonrandom. The 500 new rows preserve exact feed text, ratings and update timestamps in saved source snapshots; see DATASET.md. The original date-provenance caveat applies to the 12 legacy rows. New App Store quotes are validated against saved feed snapshots. Legacy quoted text and fee evidence were checked against retrieved public pages; legacy posting dates are not all independently verified. Dates may reflect the supplied incident date rather than publication date. See the source verification record. If the evaluator interprets “public reviews” as app-store-only, replace the sample with an independently captured app-store CSV; do not fabricate reviews or dates. Confirm ChatGPT is also the product selected in Milestone 1.

## Deploy

For Streamlit Community Cloud, publish these source files to a GitHub repository, create an app using `app.py` as the entry point, and choose Python 3.11 or newer. Dependencies are in `requirements.txt`; the `mcp` package is mandatory even for offline analysis when running the write workflow. No Google or OpenAI credentials are needed for the default local demo; Google Docs mode requires the secrets configuration in GOOGLE_DOCS_SETUP.md. Keep `.venv`, secrets, `.env`, session outputs and caches out of Git. Test MCP actions on the host: it must permit launching Python subprocesses and writing temporary files. Never use a shared fixed output directory for hosted users.

For a container or VM, install the requirements then run:

```bash
python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true
```

Use the platform's HTTPS frontend and access control if accepting sensitive uploads. Temporary output files disappear on restart or redeployment. The local environment's dependency check passed; no missing installed dependency was found. Lower bounds cover the APIs used, but only the installed environment was tested; pin versions for your deployment after its smoke test.

**Outstanding submission items:** GitHub URL, public deployment URL or ≤3-minute video with public viewing access, and confirmation of the Milestone 1 product. No deployment or video is claimed by this repository. See `ASSIGNMENT_AUDIT.md` for remaining evidence limitations.

Suggested demo: 0:00–0:40 show data/window/method; 0:40–1:20 show top themes and quotes; 1:20–2:00 show fee evidence, pulse and policy sources; 2:00–2:45 preview payload, explicitly approve, run MCP and download notes/draft; finish by stating whether notes used Google Docs or a local simulation, that email is a local draft, and that no email was sent.
