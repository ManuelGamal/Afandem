# Bench and impact report — HELD-OUT set: 5 fresh runs × 30 cards, agent Gemini 3.5 Flash-Lite at d4df47b, customer Qwen3-235B

The shop is fictional. **Measured** numbers come from the simulation bench (150 simulated customer conversations, graded by fixed rules). **Business** numbers combine those measurements with the cited assumptions below; `low` is always the conservative case.

## Measured in simulation

| Metric | Value |
|---|---|
| Task success | 92.7% (mean of 5 runs; range 90%–100%; 150 conversations) |
| Safety violations (made-up prices or address details, confirming without a yes, shipping to unreachable) | 2 |
| Self-service rate (no human needed) | 96% |
| Median agent reply time | 2.54 s (135 conversations that called the live model) |
| Median customer turns | 2.0 |
| Mean model calls / tokens in / tokens out per conversation | 4.4 / 11,387 / 203 |
| Suggested-item purchases (simulation) | 0 orders, 0 EGP |

| Customer type | Success |
|---|---|
| change_at_confirmation | 100% |
| clear_buyer | 67% |
| complaint | 100% |
| declines | 100% |
| no_reply | 100% |
| off_topic | 100% |
| price_shopper | 93% |
| reschedule | 93% |
| size_unsure | 87% |
| vague_address | 87% |

| Writing style | Success |
|---|---|
| Egyptian Arabic | 92% |
| Franco (Arabic in English letters) | 92% |
| Mixed Arabic and English | 94% |

![success by category](success_by_category.png)

## Impact for one typical shop (per month unless noted)

| | low | base | high |
|---|---|---|---|
| Hours saved / week | 14.5 | 33.2 | 102.9 |
| Moderator cost saved (EGP) | 1,806 | 4,845 | 17,130 |
| Refused COD deliveries prevented | 20 | 130 | 486 |
| Failed-delivery cost saved (EGP) | 1,755 | 15,600 | 82,620 |
| Model cost (EGP) | 943 | 587 | 325 |
| Running cost: model + hosting (EGP) | 1,443 | 837 | 325 |
| **Net cost saved (EGP)** | 2,117 | 19,609 | 99,425 |
| **Pays for itself in (days)** | 12.2 | 1.2 | 0.1 |
| Return on running cost (net saved ÷ running cost) | 1× | 23× | 306× |
| Extra sales from faster replies (EGP, gross) | 9,014 | 52,580 | 325,012 |
| Extra sales from suggested items (EGP, gross; simulation rate) | 0 | 0 | 0 |
| **Extra sales total (EGP, gross)** | 9,014 | 52,580 | 325,012 |

![impact](impact.png)

## Assumptions

| Parameter | low | base | high | Source |
|---|---|---|---|---|
| cod_orders_per_day | 25 | 40 | 60 | estimate |
| chat_order_share | 0.3 | 0.5 | 0.7 | estimate |
| dms_per_day | 100 | 150 | 250 | estimate |
| average_order_egp | 600 | 700 | 900 | https://data.stateglobe.com/egypt/social-commerce-categories-statistics |
| working_days_per_month | 26 | 26 | 30 | estimate |
| moderator_salary_egp_month | 6000 | 7000 | 8000 | https://forasna.com/a/%D9%88%D8%B8%D8%A7%D8%A6%D9%81-%D9%85%D9%88%D8%AF%D8%B1%D9%8A%D8%AA%D9%88%D8%B1-moderator-%D9%81%D9%8A-%D9%85%D8%B5%D8%B1 ; https://employsome.com/blog/minimum-wage-egypt/ |
| moderator_hours_month | 208 | 208 | 208 | estimate: 8 h x 26 days |
| minutes_per_dm | 1.0 | 1.5 | 2.5 | estimate |
| minutes_per_confirmation_call | 2 | 3 | 5 | estimate |
| refusal_rate_without_confirmation | 0.15 | 0.25 | 0.35 | https://easysellapp.com/blogs/wiki/egypt-ecommerce-cod-market-entry-shopify-2026 ; https://www.egrow.com/en/blog/the-ultimate-guide-to-cash-on-delivery-e-commerce-operations-in-2026 |
| refusal_rate_with_confirmation | 0.12 | 0.125 | 0.08 | low: estimate (confirmation removes only a fifth of refusals); base: estimate (halved); high: vendor claim 'under 8%', https://www.egrow.com/en/blog/the-ultimate-guide-to-cash-on-delivery-e-commerce-operations-in-2026 |
| outbound_shipping_egp | 60 | 60 | 85 | https://www.bosta.com/delivery-costs-and-transit-times |
| return_shipping_egp | 30 | 60 | 85 | estimate (return fees are not published) |
| buying_intent_share_of_dms | 0.3 | 0.4 | 0.5 | estimate |
| conversion_uplift_from_fast_replies | 0.02 | 0.05 | 0.1 | estimate, far below the cited 40% (reply within 15 min) vs 10% (after 3 h): https://www.lilachbullock.com/facebook-messenger-tricks-business-pages/ |
| llm_usd_per_mtok_in | 0.75 | 0.3 | 0.1 | https://ai.google.dev/gemini-api/docs/pricing (checked 2026-10-05) |
| llm_usd_per_mtok_out | 3.75 | 2.5 | 0.4 | https://ai.google.dev/gemini-api/docs/pricing (checked 2026-10-05) |
| usd_to_egp | 52 | 50 | 48 | estimate; check the rate on the day you build the slides |
| hosting_egp_month | 500 | 250 | 0 | estimate: a small VPS is about $5/month (~250 EGP at ~50 EGP/USD); low assumes $10; high is a free hosting tier |

## Formulas

- Hours saved = DMs/day x minutes per DM x self-service rate x days + orders/day x minutes per confirmation call x self-service rate x days.
- Moderator cost saved = hours saved x monthly salary / monthly hours.
- Refusals prevented = orders/day x days x (refusal rate without - with confirmation); each costs outbound + return shipping.
- Model cost = (DMs/day / median turns + orders/day) x days x tokens per conversation x paid price.
- Running cost = model cost + hosting. Pays for itself in = running cost / (gross monthly savings / 30). Return = (gross savings - running cost) / running cost.
- Extra sales = DMs/day x buying share x conversion uplift x self-service x average order x days + orders/day x days x chat share x suggested-item rate x mean suggested value.

## Violation examples

- address has details the customer never gave: محطه, المترو
- address has details the customer never gave: مسجد, هاني
