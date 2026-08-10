# Pricing UI Spec

Per BRIEF.md: "A clean, usable UI to build a cart and toggle which promotions are active, showing the itemized final price and an explanation of which promotions applied and what each one did, updating as the cart changes." Already Core in docs/scope.md — this is the concrete interaction/update behavior, not new scope.

Not "real checkout" (payment/orders) — that stays deferred (docs/scope.md). This is the cart-building and price-explanation screen the brief actually asks for.

## Two-page layout (2026-08 revision)

The UI is split into two views on a hand-rolled history-API router (no router dependency):

- **Shop (`/`)**: catalog + cart building. Never calls `POST /price` and shows no totals — only catalog unit prices. A card already in the cart replaces its Add button with a quantity stepper showing the count, so the grid answers "how many of this do I have?" without opening the drawer; stepping the last unit down removes the line.
- **Checkout (`/checkout`)**: owns the update flow below. Prices on arrival and on every deal change; deal cards, breakdown panel, and explanations live here. An empty cart shows an empty state and makes no call.

Cart and deal state live at the app level so they survive navigation (in-memory only — refresh clears them). Unknown paths render the shop.

## Deal states (2026-08 revision)

There is **no opting in**. Every deal is claimed on the shopper's behalf and the optimizer picks the best allowed combination; the switches exist to override that pick, not to enable deals. Each card is in exactly one of three states, all derived from the server's response — never computed client-side:

| State | Source | Appearance | Interaction |
|---|---|---|---|
| Applied | `promotion_statuses[id] == "applied"` | Caramel edge, switch on, shows the cents saved | Switching off excludes it |
| Qualifies | `availability[id].eligible`, not applied | Normal card, switch off, "qualifies" | Switching on pins it |
| Not eligible | `!availability[id].eligible` | Dimmed, inert, shows `gap` as "spend $X more after deals to unlock" | None |

Only the third state dims, so "greyed out" means exactly one thing: your cart does not qualify. This split is why `POST /price` carries `promotion_availability` at all — `promotion_statuses` alone collapses the first two "not applied" cases into one value once everything is claimed by default.

The switch reflects what **applied**, not what was claimed, so it can never disagree with the receipt beside it. Mutual exclusion therefore needs no client-side rule: pinning a deal makes the server drop whatever it displaces, and the rival's switch turns itself off in the next response.

### Automatic vs. explicit selection

Two modes, because re-optimizing over the whole catalog after every click makes switches move on their own, which reads as the UI fighting the shopper:

- **Automatic** (`selection === null`, the default): every deal is claimed and the server picks the best allowed combination.
- **Explicit**: the first manual switch freezes whatever was applied into a selection, and every later edit is a plain add/remove on that set. `claimed_promotion_ids` is then exactly the selection.

The point of freezing is that **switching a deal off is purely subtractive**. Claiming only the selection means a rival the shopper never turned on cannot be substituted in — it simply becomes `available` (un-greyed, switch off) and waits to be chosen. Switching a deal *on* additionally pins it and drops its conflicts from the selection, so the rival cannot lurk and reappear on a later switch-off.

Deals still change *state* freely as the cart or the applied set moves — a threshold deal un-greys the moment the cart clears its bar, and shortfalls recompute against the new cascade. What never changes without a click is which switches are **on**.

A reset control appears whenever a selection is in force, labelled with what the override costs against the automatic best. That figure is known only when the automatic best was priced for the *current* cart; after a cart edit the control shows without a figure rather than quoting a stale saving.

## Update flow

No explicit "optimize" button, no client-side racing (docs/core-engine-spec.md): arriving at checkout or changing a deal fires a single debounced `POST /price` call. The backend always computes both engines and returns whichever passes the runtime sanity check (docs/optimizer-spec.md) — the frontend just displays the response.

## Explanation display

Per docs/scope.md's Explanation trace: for each **applied** promotion (docs/core-engine-spec.md's status model), show what it did and to which lines. Final total updates live as the cart or deals change.
