# Reactive conditions are a separate property from triggers

`when::` is its own prop on an `#automation` block, independent of `trigger::`.
`trigger::` decides when an automation gets evaluated at all — a schedule slot,
an explicit run, eventually a block changing. `when::` decides, given that an
evaluation happened, whether its query result is worth acting on. The two
compose freely: `when::` never inspects which trigger kind it's paired with,
it only requires a `query::` to have something to evaluate.

They look collapsible at first — today the only trigger that can produce
repeated evaluations is `schedule`, so a reactive automation always reads as
`trigger:: schedule <cadence>` plus `when:: <condition>`, and it's tempting to
fold the condition into the trigger's own grammar. It doesn't collapse,
because `when::` stays meaningful once a real event trigger exists (issue
#206 slice 3, not yet built): one `block_event` is one edit, not one state
transition. A list that's already empty getting an unrelated edit shouldn't
re-fire a `becomes-empty` automation just because an event happened to land
while it was empty — the condition is still doing edge-detection on a noisy
per-evaluation signal, event-driven or polled. `matched-for`'s dwell duration
makes the same point harder to miss: "has this matched for 2h" can't be
answered by any single trigger firing, event or schedule, it inherently needs
its own clock. Folding `when::` into `trigger::` would just relocate that
clock into an awkward corner of the trigger grammar instead of removing it.

`when::` isn't one consistent shape internally, either. `becomes-empty` /
`becomes-nonempty` / `count <op> N` read the match set's *size* and gate the
whole tick — the action runs over every currently-matched block, or the run
is recorded SKIPPED and nothing runs. `matched-for <duration>` reads *each
block's own history* (a watermark row per matched block, see
`AutomationBlockMatch`) and narrows the action to whichever subset has
dwelled long enough, leaving the rest matched-but-untouched for next tick.
One property, two different granularities of "worth acting on."

It left some threads behind. `when::` with `for::` is rejected today only as
a side effect of two other rules composing (`when::` requires `query::`;
`for::` and `query::` are mutually exclusive), so the error a user sees
doesn't name the actual conflict — worth a dedicated message, since the
incompatibility isn't a technicality: `for::` is a static, re-parsed-every-
tick item list, never a live query result, so there's nothing for a reactive
condition to observe changing. And sampling cadence genuinely bounds
correctness for the whole-set conditions: `trigger:: schedule daily 6:00` +
`when:: becomes-empty` can silently miss a transition that happens and
reverses between two samples. Nothing today warns a user who pairs a sparse
cadence with an edge-detect condition; that's a gap, not a tradeoff anyone
chose on purpose.
