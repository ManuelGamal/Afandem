# AI Moderator for an Egyptian fashion shop — design

Entry for **Agents at Work, 1st edition** (ai.untap.us; Untap, Wesam.ai, Taalam.ai), Students track.
Working name: `aaw-moderator`.

## 1. Goal and constraints

**Goal:** first place. Judging is online, on four criteria: *does it work* (a live agent a judge can run end
to end), *hours saved*, *cost saved*, *revenue generated* — "measurable business impact, not demo polish".

**Deadline:** Saturday 2026-10-10, 11:59 PM Cairo time. We submit by ~6 PM that day.

**Submission:** (1) GitHub repo with a README that gets a judge running it in under five minutes,
(2) impact slides — the SME, the workflow replaced, the measured impact, (3) a 2–3 minute demo video.

**Constraints:**
- Solo build, ~5 days.
- No real SME. The shop is fictional. Every business number is either cited (section 9), labelled as an
  estimate, or labelled as a simulation result. Nothing is presented as a real shop's results.
- Free-tier models only (Gemini, Groq). Daily request limits are low and uncertain, so the design must
  survive running out.
- Reuse of the author's own MIT-licensed `amin` repo is allowed and disclosed in the README.

## 2. The SME and the workflow replaced

A fictional Cairo casual-wear brand that sells through Instagram, Facebook and WhatsApp, plus a small
Shopify-style store with cash-on-delivery (COD) checkout. This is the typical Egyptian social-commerce SME:
Facebook pages carry 61.7% of Egyptian e-commerce and WhatsApp 31.8% (MCIT), and fashion is the top
social-commerce category.

Today the shop pays one or two "moderators" (5,000–8,000 EGP/month) to:
1. answer DMs — price, size, stock, delivery cost — often hours late, and
2. phone every COD order to confirm it before shipping, because 15–35% of COD orders are refused at the
   door or never completed, and each refusal costs shipping both ways.

The agent does both jobs, in Egyptian Arabic, around the clock, and measures what it did.

**Why this is not a commodity:** OTP and button COD-confirmation apps already exist (WASP from $5/month;
Cartsaver, Egyptian). They cannot answer "هيجي عليا مقاس ايه؟" (what size fits me?), fix a vague address,
reschedule, or sell. Ours is a conversational agent covering the whole funnel — DM → order → confirmation
→ courier — which is also the shape of an "AI employee" on Wesam.ai's marketplace.

## 3. Architecture

One Python package, FastAPI server, SQLite. `docker compose up` or `uv run` starts everything.

| Unit | Purpose | Depends on |
|---|---|---|
| `store/` | Seeded fictional shop in SQLite: ~30 products (sizes, colours, stock, size chart), delivery zones and fees modelled on Bosta's public rates, policies (exchange, delivery times), customers, orders. Pure data access, no LLM. | — |
| `agent/tools.py` | The tool functions and their JSON schemas (section 4). Validate arguments (pydantic), return structured results or structured errors. | `store/` |
| `agent/loop.py` | One tool-calling loop: system prompt (Egyptian-Arabic persona and rules), conversation history, max 6 tool calls per turn. Two entry points: `reply(conversation, message)` for inbound chats and `start_confirmation(order_id)` for outbound confirmation. | `tools`, `providers/` |
| `agent/risk.py` | Deterministic risk score with human-readable reasons. | `store/` |
| `providers/` | OpenAI-compatible chat client with a fallback chain (Gemini models → Groq), retry with backoff on rate limits, and a response cache keyed by request hash. Adapted from `amin.harness.adapters`. | — |
| `events.py` | In-process event bus. Tool calls, order state changes and handoffs publish events; the dashboard subscribes via server-sent events (SSE); impact counters are computed from the event log. | — |
| `web/` | One page, Arabic RTL. Left: WhatsApp-style phone chat. Right: owner dashboard — order pipeline, risk queue, handoff queue, live impact counters, "simulate a checkout order" button, "reset sandbox" button. Plain HTML/JS served by FastAPI. | server API, SSE |
| `replay/` | Recorded conversations (model responses stored as cassettes) replayed through the same loop, so the demo and tests run with no API key. | `providers/` |
| `bench/` | Customer cards, a simulated customer, a deterministic grader, a runner, and the impact model (section 6). | `agent/`, `store/`, `providers/` |

Amin pieces to adapt (copy into this repo, attribute in the README): the OpenAI-compatible provider adapter,
the phone/money/date normalizers, and the cassette replay pattern.

## 4. Tools

All prices, stock and fees come from tools; the model never states a number it did not get from one.

| Tool | Does |
|---|---|
| `search_products(query, category?, max_price?)` | Catalogue search (Arabic, Arabizi or English query). |
| `get_product(product_id)` | Price, colours, sizes with stock, size chart. |
| `recommend_size(product_id, height_cm, weight_kg, fit_preference?)` | Size from the product's chart; says when between sizes. |
| `quote_delivery(area)` | Zone, fee and delivery window for an Egyptian area name. |
| `create_order(customer_name, phone, address, area, items[])` | Creates a `draft` order and returns its summary. Idempotent per conversation. |
| `update_order(order_id, changes)` | Change items, size, colour, address or delivery date; re-checks stock and recomputes the total. |
| `confirm_order(order_id)` | Moves to `confirmed`. Rejected with a structured error ("ask for explicit confirmation") unless (1) the agent's previous message contained this order's read-back summary and (2) the customer's latest message matches a yes lexicon (تمام، ماشي، اه، أيوة، أكيد، موافق، ok, yes, tmam, mashy, aywa, and close variants). Checked in code, not by the model. |
| `cancel_order(order_id, reason)` | Moves to `cancelled` with a reason code. |
| `schedule_delivery(order_id, date)` | Sets the delivery date within the zone's window. |
| `flag_risk(order_id, note)` | Adds an agent observation (e.g. hesitation) to the risk score. |
| `handoff_to_human(reason)` | Puts the conversation in the owner's queue and stops the agent replying in it. |

## 5. Conversation and order flow

**Order sources:**
- **(a) Chat sale.** Customer asks ("بكام الجاكيت ده؟"). Agent searches and answers price, size, colour,
  stock and delivery, suggests at most **one** matching item, collects name, phone and address, reads back a
  summary (items, size, total with delivery, window) of the `draft` order it created, and on an explicit
  yes calls `confirm_order` — so a chat sale goes `draft → confirmed` with no separate confirmation call.
- **(b) Checkout order.** The "simulate a checkout order" button (and the bench) inserts an order as
  `pending_confirmation`. The agent opens the confirmation conversation itself.

**Order states:** `draft → pending_confirmation → confirmed → shipped`; exits `cancelled` (reason code) and
`needs_human`. Transitions are enforced in `store/`, not by the model.

**Confirmation conversation outcomes:**

| Customer | Agent | Result |
|---|---|---|
| Yes | confirm | `confirmed` |
| Change size/colour | check stock, update, re-confirm | `confirmed` (updated) |
| Vague address | ask for building, street, landmark | `confirmed` once complete |
| Not home that day | reschedule within window | `confirmed` (new date) |
| No / changed mind | cancel, record reason | `cancelled` — a refusal prevented |
| No reply | one reminder; then mark unreachable | not shipped — a refusal prevented |
| Complaint / dispute / abuse / unsure | hand off | `needs_human` |

A demo clock compresses waits ("remind after 2 hours" happens in seconds in the demo).

**Risk score** (`agent/risk.py`), points with reasons shown on the dashboard: first order; order value above
a threshold; phone not a valid Egyptian mobile (010/011/012/015, via the normalizer); incomplete address;
past cancellations on the same phone; agent-flagged hesitation. High-risk orders go to the owner's review
queue with a suggested action: ask for the delivery fee upfront by InstaPay.

**Impact counters** (computed from the event log): messages handled, median agent reply time, orders
confirmed, orders cancelled or held before shipping, EGP saved (refusals prevented × cost of a failed
delivery, using the base case from section 6), revenue from accepted suggested items.

## 6. Bench and impact model

The bench separates **what is measured** (agent quality, in simulation) from **what is assumed**
(business parameters, from cited sources). The simulation never decides whether a customer would have
refused at the door; that effect comes only from cited sources.

**Customer cards** (~60, YAML): goal, script (Egyptian Arabic / Arabizi / mixed with English),
personality, hidden facts (e.g. "will not be home Thursday", "lives near the Shell station, no building
number"), and the expected end state. Categories: clear buyer; size-unsure; price shopper who leaves;
changes size or colour at confirmation; vague address; reschedule; says no at confirmation; no reply
(scripted, no LLM calls); complaint needing a human; off-topic or abusive.

**Simulated customer:** an LLM plays the card, sees only the card and the chat, and ends with a stop token
when its goal is met or abandoned. Max 12 turns.

**Grader (deterministic, from the database and transcript):**
- *Task success:* final order state, product, size, quantity, address and total match the card's
  expectation; cancelled when the customer said no; handed off when it should be.
- *Safety violations:* any price, fee or stock figure in an agent message that does not match the database;
  any confirmation without an explicit yes; any shipment to an unreachable customer. Target 0.
- *Self-service rate:* conversations resolved without handoff (excluding cards that should hand off).
- *Speed:* median reply latency and turns per conversation.
- *Dialect robustness:* success rate split by script.
- *Cost:* tokens per conversation, priced at the paid rate of the model used.

**Runner:** resumable (skips finished cards), uses the provider cache, writes `bench/results/*.jsonl` and a
summary. Budget ~60 cards × ~8 turns × ~3.5 calls ≈ 1,700 calls; spread over two days if limits require.

**Impact model:** `bench/assumptions.yaml` — every parameter has a low/base/high value and a source URL or the
label `estimate`. The fictional shop: ~40 COD orders/day, 700 EGP average order, ~150 DMs/day. Baseline:
1–2 moderators at 6,000–8,000 EGP/month; confirmation call minutes (estimate unless sourced); 25% refusal
without confirmation (cited range 15–35%); failed-delivery cost = outbound + return shipping. Confirmation
effect: conservative base (refusals halved), vendor claim (under 8%) as the high case.

`bench/report.py` produces `bench/report.md` and charts:
- **Hours saved/week** = DMs × handling minutes × self-service rate + confirmation calls avoided × call minutes.
- **Cost saved/month** = refusals prevented × failed-delivery cost + moderator hours saved × hourly wage − LLM cost.
- **Revenue/month** = suggested-item acceptance (simulation, labelled) × item price + reply-speed effect on
  conversion (cited, conservative).

## 7. Error handling

- Tools validate arguments and return structured errors; the model sees them and recovers.
- Max 6 tool calls per turn; on overflow the agent apologises and hands off.
- `create_order` is idempotent per conversation; state transitions are enforced in `store/`.
- Provider chain: on rate limit or error, back off and try the next provider. If all fail, the customer
  gets a polite fixed Arabic message and the conversation is handed off.
- Hosted demo: each browser session gets its own sandbox copy of the database, a reset button, and a
  message cap per session to protect the API key.

## 8. Testing

- pytest, deterministic: tools, order state machine, risk score, pricing and delivery fees, normalizers,
  impact formulas.
- Agent tests replay recorded cassettes, so CI uses no quota.
- The bench is the end-to-end test.
- Before submitting: fresh clone, follow the README with a timer; must be under five minutes.

## 9. Submission package

- **README:** three ways to run — (1) hosted URL, nothing to install; (2) `docker compose up` with a free
  Gemini key (link and one-minute steps); (3) replay mode, no key. A 30-second "try this" script for judges,
  the bench results table, the cited assumptions, and the Amin reuse note.
- **Slides (~8, exported to PDF):** problem with citations; the shop and the before/after workflow; how the
  agent works; screenshots; measured quality; hours / EGP / revenue at low-base-high; cost per conversation
  and what is assumed; roadmap (Wesam.ai marketplace, real WhatsApp Cloud API, a small self-hosted Egyptian
  model).
- **Video (~2:30):** 0:00 problem in numbers → 0:20 live sale in Egyptian Arabic → 1:00 checkout order whose
  confirmation fixes the address and reschedules → 1:30 risky order flagged → 1:50 dashboard counters and
  bench results → 2:15 impact numbers. Screen capture with the author's voiceover.
- **Deploy:** Docker image on a free host (Hugging Face Spaces or Render); the URL must stay up through
  judging.

## 10. Schedule and cut order

| Day (Cairo) | Work |
|---|---|
| Mon Oct 5 | Spec and implementation plan |
| Tue Oct 6 | `store/`, tools, agent loop, providers; working chat in a terminal |
| Wed Oct 7 | Confirmation mode, risk, handoff, web chat and dashboard, replay recordings |
| Thu Oct 8 | Bench (cards, simulator, grader), first run, fixes, deploy |
| Fri Oct 9 | Full bench run, impact report, README, slides |
| Sat Oct 10 | Video, fresh-clone check, submit by ~6 PM |

Cut first if behind: real WhatsApp line (stretch only) → suggested-item upsell → Arabizi cards → dashboard
polish. Never cut: chat sale → confirmation → bench → impact report.

**Open items for the author:** check the free-tier limits at aistudio.google.com/rate-limit; ask on
BrainsMingle whether the submission form is open and whether reusing one's own earlier open-source code is
allowed.

## 11. Sources

- MCIT via Ahram Online — Facebook 61.7%, WhatsApp 31.8% of e-commerce:
  https://english.ahram.org.eg/NewsContent/1/2/519406/Egypt/Society/Facebook-pages,-WhatsApp-groups-dominate-Egypt%E2%80%99s-e.aspx
- MSMEs 90% of private sector, 43% of GDP (MSMEDA): https://english.ahram.org.eg/News/534900.aspx
- Social commerce, fashion top category, 700 EGP average: https://data.stateglobe.com/egypt/social-commerce-categories-statistics
- 78% of small businesses use Facebook as main channel: https://www.udjatagency.com/ecommerce-marketing-egypt-statistics/
- COD refusal and return rates: https://easysellapp.com/blogs/wiki/egypt-ecommerce-cod-market-entry-shopify-2026 ,
  https://www.egrow.com/en/blog/the-ultimate-guide-to-cash-on-delivery-e-commerce-operations-in-2026
- COD share of transactions: https://www.egrow.com/en/blog/egypt-cod-ecommerce-2026
- Bosta delivery costs: https://www.bosta.com/delivery-costs-and-transit-times
- Private-sector minimum wage 7,000 EGP: https://employsome.com/blog/minimum-wage-egypt/
- Moderator salaries: https://forasna.com/a/%D9%88%D8%B8%D8%A7%D8%A6%D9%81-%D9%85%D9%88%D8%AF%D8%B1%D9%8A%D8%AA%D9%88%D8%B1-moderator-%D9%81%D9%8A-%D9%85%D8%B5%D8%B1
- Reply-time effect on conversion: https://www.lilachbullock.com/facebook-messenger-tricks-business-pages/
- Competitors: https://apps.shopify.com/wasp-order-confirmation ,
  https://egyptianstreets.com/2025/12/23/how-an-egyptian-app-is-tackling-cash-on-delivery-fraud-with-whatsapp/

Numbers still to source during the build (else labelled `estimate`): Bosta return fee; minutes per
confirmation call; share of DMs arriving outside working hours.
