# Terms Desk demo — ElevenLabs voiceover script (~2:05)

Voice: calm, confident, mid-pace. Paste each block as its own ElevenLabs generation, or all at once with the pauses kept.
Timestamps match the silent video (terms-desk-demo.mp4). Each block fits its window at ~150 words/min.

---

[0:00–0:08] TITLE
Freelancers offer "two percent off if you pay early" all the time. Most never check if it actually makes them money.

[0:08–0:22] OVERVIEW
This is Terms Desk. It's an agent that sits on top of PayPal Invoicing and decides, invoice by invoice, whether an early-payment discount earns you cash, or just hands margin to clients who'd pay on time anyway.

[0:22–0:36] RUN AGENT
I press Run agent. It pulls my draft invoices from PayPal, scores each client's chance of paying on time, and passes every proposal to the Skeptic.

[0:36–0:52] APPROVAL QUEUE
The Skeptic is plain math, not AI. Lumen Labs pays on time eighty-four percent of the time, so a discount would just give away about a hundred and thirty dollars. Blocked. Northwind usually pays months late, so here the discount is worth it.

[0:52–1:16] APPROVE NORTHWIND
Nothing goes out until I approve. One click, and Terms Desk creates the invoice through the PayPal Invoicing API with a two percent discount, and sends it. If the client misses the ten-day window, the discount is removed automatically. And here's the real sandbox payment: one thousand nine hundred and sixty dollars, marked paid by PayPal.

[1:16–1:50] THE SKEPTIC
You can test the rule yourself. Northwind pays on time twenty-nine percent of the time, and the discount comes out positive. Now raise that chance to eighty-four percent. The verdict flips. Even if every slow payer sped up, the discount still loses money, because you'd mostly be paying clients who were going to pay anyway.

[1:50–2:02] MONEY LEDGER
Every decision lands in the ledger: who decided, and what it was worth. Money kept, discounts paid, nothing hidden.

[2:02–2:10] END CARD
Terms Desk. Discounts that earn money, built on PayPal.

---
Notes
- Clients are fictional. The Northwind payment is a real PayPal sandbox transaction (no real money).
- Do not say PayPal's built-in conditional discount rules are used; Terms Desk enforces the window itself.
