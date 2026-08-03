# Pricing UI Spec

Per BRIEF.md: "A clean, usable UI to build a cart and toggle which promotions are active, showing the itemized final price and an explanation of which promotions applied and what each one did, updating as the cart changes." Already Core in docs/scope.md — this is the concrete interaction/update behavior, not new scope.

Not "real checkout" (payment/orders) — that stays deferred (docs/scope.md). This is the cart-building and price-explanation screen the brief actually asks for.

## Update flow

No explicit "optimize" button, no client-side racing (docs/core-engine-spec.md): every cart edit or promotion toggle fires a single `POST /price` call. The backend always computes both engines and returns whichever passes the runtime sanity check (docs/optimizer-spec.md) — the frontend just displays the response, including `optimal: bool` if a "we found extra savings" style indicator is wanted later.

## Explanation display

Per docs/scope.md's Explanation trace: for each **applied** promotion (docs/core-engine-spec.md's status model), show what it did and to which lines. Final total updates live as the cart or toggles change.
