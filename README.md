# Wasla — an AI moderator for Egyptian social-commerce shops

**Wasla answers a fashion shop's DMs in Egyptian Arabic, Arabizi or English, takes the order, confirms
cash-on-delivery orders before they ship, and holds the risky ones — so fewer parcels come back
refused.** Built for the *Agents at Work* hackathon (Untap · Wesam.ai · Taalam.ai).

> The shop, **Wasla Wear**, is fictional. Every business number below is either cited, labelled
> `estimate`, or labelled as a **simulation** result. Nothing is presented as a real shop's results.

| | |
|---|---|
| **Held-out task success** | **97%** of 30 simulated customers the agent was never tuned on |
| **Safety violations** | **0** — no made-up price, no confirmation without an explicit yes |
| **One typical shop, base case** | **32 h/week** saved · **19,372 EGP/month** net · **pays for itself in 1.3 days** |

<!-- HOSTED_URL -->

---

## Try it in 30 seconds

1. Open the hosted demo (link above) or run it locally (next section).
2. Click **Play demo** in the sidebar — seven conversations play end to end: a sale, Arabizi, a website
   order with a vague address and a new delivery day, a cancellation, a high-risk order, a complaint,
   and a customer who never replies.
3. Then write as a customer, or click one of the example prompts:
   - `الهودي التقيل بكام؟` (how much is the heavy hoodie?) — price, colours and sizes come from the catalog.
   - `طولي 178 ووزني 80` (I'm 178 cm, 80 kg) — a size from the product's size chart.
   - Give a name, phone and address → the order summary arrives → reply `تمام بس خليه L` (OK but make it
     L) → it changes the order and asks again instead of confirming.
   - **New website order** — an order arrives; the confirmation goes out as a WhatsApp-style template.
   - `التيشيرت اللي جالي مقطوع وعايز فلوسي` (the t-shirt I got is torn, I want my money) — handed to a person.
   - **Skip ahead 2 hours** on an unanswered order — one reminder, then it is cancelled before it ships.
4. Open **Dashboard**, **ROI calculator**, **Agent activity** and **Needs a person** from the sidebar.

## Run it locally (under 5 minutes)

**Option A — Docker, no key needed.**
```bash
docker compose up --build        # then open http://localhost:8000
```
With no API key the app starts in **recorded-demo mode** and **Play demo** replays a real recorded
run. If port 8000 is busy: `HOST_PORT=8010 docker compose up --build`.

**Option B — live, with a free Gemini key.** Get a key at https://aistudio.google.com/apikey, then
```bash
GEMINI_API_KEY=your-key docker compose up --build     # PowerShell: $env:GEMINI_API_KEY="your-key"
```

**Option C — without Docker.**
```bash
uv sync
uv run uvicorn --factory moderator.server:create_app --port 8000
uv run python -m moderator.cli          # terminal chat; /checkout, /advance 2, /orders
```

## The SME and the workflow it replaces

A typical Egyptian online fashion shop sells through Facebook, Instagram and WhatsApp — Facebook pages
carry **61.7%** of Egyptian e-commerce and WhatsApp groups **31.8%** ([MCIT via Ahram Online][mcit]).
It pays one or two "moderators" (**5,000–8,000 EGP/month** — [Forasna][forasna]; private-sector minimum
wage 7,000 EGP — [Employsome][wage]) to:

1. **answer DMs** — price, size, stock, delivery — often hours late; and
2. **phone every cash-on-delivery order** before shipping, because **15–35%** of COD orders are refused
   at the door or never completed ([EasySell][easysell], [eGrow][egrow]), and each refusal costs
   shipping both ways (Cairo delivery from 60 EGP — [Bosta][bosta]).

| Before | With Wasla |
|---|---|
| DMs answered when a moderator is free | Every DM answered in seconds, in the customer's own style |
| Size questions → guesswork → wrong-size refusals | Size from the product's chart (height, weight, fit) |
| A person phones each website order | A confirmation template goes out at once; the agent handles the reply |
| Vague addresses ship anyway | The agent asks for building, floor and landmark before confirming |
| Risky orders ship like any other | A transparent risk score holds them for the owner, with an InstaPay suggestion |
| No numbers | A live dashboard and an ROI calculator with the shop's own numbers |

Plain COD-confirmation apps already exist (e.g. [WASP][wasp], [Cartsaver][cartsaver]) — they send a
button or an OTP. Wasla is a conversational agent across the whole funnel: DM → order → confirmation →
courier, with the shop owner in the loop.

## What the agent does

**Tools (11):** `search_products`, `get_product`, `recommend_size`, `quote_delivery`, `create_order`,
`update_order`, `confirm_order`, `cancel_order`, `schedule_delivery`, `flag_risk`, `handoff_to_human`.

**Guardrails enforced in code, not just asked of the model:**
- **No made-up numbers.** Every amount the agent writes next to a currency word must appear in a tool
  result or in the customer's own message; otherwise the reply is sent back for correction (twice at
  most, then a person takes over).
- **No confirmation without an explicit yes.** `confirm_order` only works when the customer has seen
  the current order (items, address, total) and replied with an unconditional yes (`تمام`, `أكده`,
  `a2ked`, `ok`…). "تمام بس خليه L" is not a yes; neither is a question.
- **No false claims.** If a reply says an order is confirmed or cancelled while the system says
  otherwise, the agent must correct itself before anything is sent.
- **Promises are kept.** A reply that hands the customer to a person triggers the actual handoff.
- **Order states** (`draft → pending_confirmation → confirmed → shipped`, exits `cancelled` /
  `needs_human`) are enforced by the order book.
- **Business-initiated messages are templates** (as WhatsApp Business requires): the confirmation and
  the single reminder always carry the exact summary and total.
- **Risk score** with readable reasons: first order, value, invalid Egyptian mobile, incomplete address,
  past cancellations, agent notes. High risk → held for the owner.

## Measured results (simulation)

The bench follows the method of [τ-bench][taubench] / [τ²-bench][tau2]: a language model plays the
customer from a scenario card, and the outcome is graded **by fixed rules from the final order state**
— no model judges. Cards cover 10 customer types (clear buyer, unsure of size, price shopper, change at
confirmation, vague address, reschedule, declines, never replies, complaint, off-topic) and three
writing styles (Egyptian Arabic, Arabizi, mixed). The simulated customer runs on a different model
from the agent.

- **Development set (60 cards)** — used to find and fix failures. Every failure was traced to a root
  cause (e.g. a too-strict yes check, a reply claiming a confirmation that never happened); task success
  went from 82% to 97%. [`bench/report/report.md`](bench/report/report.md)
- **Held-out set (30 cards)** — new people, areas, products, phrasings and scenarios, written after the
  fixes and run once on the agent frozen at commit `8b29e1e`, with no changes afterwards.
  [`bench/report-heldout/report.md`](bench/report-heldout/report.md)

| Held-out (30 simulated customers) | |
|---|---|
| Task success | **97%** (29/30) |
| Safety violations | **0** |
| Handled without a person | 93% |
| Median agent reply time | 3.0 s |
| Success by writing style | Egyptian Arabic 100% · Arabizi 90% · mixed 100% |
| Model calls / tokens per conversation | 4.6 / 12,205 in, 240 out |

The one miss: a customer asked whether the fabric shrinks after washing. The catalog has no fabric
information, so the agent handed her to a person instead of inventing an answer — the grader counts it
as a failure because the order was not confirmed.

LLM-simulated customers are imperfect proxies for people ([Lost in Simulation][lost]); these are
simulation results, not field results.

## Business impact and ROI for one typical shop

Measured agent quality × cited assumptions (`low` is always the conservative case):

| Per month unless noted | low | base | high |
|---|---|---|---|
| Hours saved / week | 13.9 | 32.0 | 98.9 |
| Refused COD deliveries prevented | 20 | 130 | 486 |
| Running cost: model + hosting (EGP) | 1,519 | 887 | 351 |
| **Net cost saved (EGP)** | **1,972** | **19,372** | **98,741** |
| **Pays for itself in (days)** | 13.1 | 1.3 | 0.1 |
| Extra sales from faster replies (EGP, gross, estimate) | 8,667 | 50,560 | 312,525 |

The **ROI calculator** in the app runs the same model with a shop's own numbers (orders/day,
messages/day, moderator salary, refusal rate, average order). All parameters, sources and formulas:
[`bench/report-heldout/report.md`](bench/report-heldout/report.md).

## WhatsApp

`moderator/whatsapp.py` connects the same agent to the **WhatsApp Cloud API**: Meta's webhook comes in
(signature-checked with the app secret), replies go out through the Graph API, duplicate deliveries are
ignored, and `/checkout` sent from a phone triggers a website-order confirmation to that number. The
conversations show live at `/?view=whatsapp`. To connect a number, set `WHATSAPP_TOKEN`,
`WHATSAPP_PHONE_ID`, `WHATSAPP_APP_SECRET` and `WHATSAPP_VERIFY_TOKEN`, and point the app's webhook to
`https://<your-host>/webhook/whatsapp`.

## How it's built

```
moderator/
  store/       catalog (30 products, size charts, 6 delivery zones) + SQLite order book
  agent/       tools, risk score, Egyptian-Arabic system prompt, tool-calling loop with guards
  providers/   OpenAI-compatible client, fallback chain across free Gemini models, response cache
  server.py    FastAPI: a sandbox per browser, live dashboard over server-sent events, ROI endpoint
  whatsapp.py  WhatsApp Cloud API bridge
  web/         the demo page (no framework)
  bench/       cards, simulated customer, runner, grader, impact report
replay/        the recorded demo used when there is no API key
```

- **Free-tier friendly:** a fallback chain across Gemini Flash-Lite models that waits for the first
  model to free up instead of failing, and a response cache — the recorded demo never spends quota.
- **Tests:** `uv run pytest` (150 tests, no API key needed).
- **Re-run the bench:** `uv run python -m moderator.bench.runner --cards bench/cards-heldout --out bench/results/heldout`
  (resumable), then `uv run python -m moderator.bench.report --results bench/results/heldout --cards bench/cards-heldout --out bench/report-heldout`.
- **Play a card yourself:** `uv run python -m moderator.bench.runner --human --ids clear-1,decline-2 --out bench/results/human`.

## Honesty notes

- The shop and its catalog are fictional; prices are realistic but invented.
- Business impact combines measured simulation quality with cited assumptions; estimates are labelled.
- The recorded demo and the bench use free Gemini Flash-Lite models; wording varies run to run.
- Built with Claude Code as an AI pair programmer.

## Credits

Text normalizers, the cache format and the provider-adapter pattern are adapted from the author's own
AminBench project (Egyptian-dialect tool-calling benchmark, MIT). Icons: Lucide (ISC).
Fonts: Inter, IBM Plex Sans Arabic, IBM Plex Mono.

[mcit]: https://english.ahram.org.eg/NewsContent/1/2/519406/Egypt/Society/Facebook-pages,-WhatsApp-groups-dominate-Egypt%E2%80%99s-e.aspx
[forasna]: https://forasna.com/a/%D9%88%D8%B8%D8%A7%D8%A6%D9%81-%D9%85%D9%88%D8%AF%D8%B1%D9%8A%D8%AA%D9%88%D8%B1-moderator-%D9%81%D9%8A-%D9%85%D8%B5%D8%B1
[wage]: https://employsome.com/blog/minimum-wage-egypt/
[easysell]: https://easysellapp.com/blogs/wiki/egypt-ecommerce-cod-market-entry-shopify-2026
[egrow]: https://www.egrow.com/en/blog/the-ultimate-guide-to-cash-on-delivery-e-commerce-operations-in-2026
[bosta]: https://www.bosta.com/delivery-costs-and-transit-times
[wasp]: https://apps.shopify.com/wasp-order-confirmation
[cartsaver]: https://egyptianstreets.com/2025/12/23/how-an-egyptian-app-is-tackling-cash-on-delivery-fraud-with-whatsapp/
[taubench]: https://arxiv.org/abs/2406.12045
[tau2]: https://huggingface.co/papers/2506.07982
[lost]: https://arxiv.org/abs/2601.17087
