# Backlog

Deferred work, with the trigger that unblocks each item. Nothing here is in v1 scope
until its trigger is met.

---

## Current state

*Replace this whole section on each checkpoint — do not append a second one.*

**Last updated:** 2026-08-18 · **HEAD = `8221aef`** (pushed to `origin/main`)

Three full 34-contact runs have now happened, all draft-only. Review CSVs live in
`reviews/`, which is git-ignored, so the artifacts are local to whoever ran them.

### Done and committed

Everything from the previous checkpoint still holds: structural three-position
validation, retry-once, the three-branch persona default with the
platform-fabrication guard, positional length targets, subjects 2–7 words, the
CTA-family banned regex, the `repair.py` sign-off strip, the sequence-level
stat-budget WARN, and the `VOICE-ANCHOR` injection. Added since:

- **Message 2 has a defined job** (`e446c7f`). It develops one angle m1 did not cover,
  must stand alone if m1 got no reply, and its length must come from content rather
  than padding. No word floor was added. m2 median went 80.5 → 89.5 words and
  under-target dropped from 16/34 to 8/32.
- **Message 2 has its own concrete-offer CTA rule** (`46a0a06`), varied from m1's ask.
  m2 was defaulting to the banned hedge (13 of 32 bodies) because m1 and m3 carried a
  CTA rule and m2 did not.
- **Quantified commercial terms are a hard FAIL** (`a5e5cf5`, `check_commercial_terms`).
  The *existence* of a tailored offer is sayable; its *terms* are not. The vague
  bundled "financial incentives" the anchor uses still passes. 14/14 boundary tests,
  3 genuine fires and 0 false positives across 207 emails. Not auto-repaired, for the
  same reason the CTA family isn't.
- **Generation-failure fallback** (`875ff09`). On retry exhaustion the row is filled
  with the committed copy in `config/generation-failure-fallback.md`, marked
  `GENERATION_FAILED_FALLBACK`, keeps its original `generation_error`, and is counted
  and named separately in the run summary. Fallback rows are excluded from the
  validation report so they cannot inflate the pass rate. That file is deliberately
  **not** in `RULEBOOK_FILES`: a ready-made sequence in the prompt is something the
  model would echo.
- **Batch-level verbatim-opener check** (`8221aef`, WARN, called from the orchestrator).
  Flags byte-identical opening sentences reused across contacts. Caught 3 real reuses
  on replay, two of them in **m1**, not m2.

**Empty responses were never a retry gap.** They surface as `JSONDecodeError` from
`json.loads("")` and are caught by the same clause as malformed JSON, so they always
got the retry. Verified with a stub client. The `char 0` error signature cannot
distinguish a truly empty response from a bare opening code fence, but it does rule
out truncation.

### Latest 34-run (`8221aef` minus the CTA and opener commits)

8 PASS / 7 WARN / 17 FAIL / 2 generation-failure fallback. 75 of 96 generated emails
passed. Branch distribution unchanged across every run: 25 `gmv`, 9 `competitor`,
12 Pro, 22 Premium, one `platform_known=False`.

### Next task: a 34-run on the three newest changes

**The CTA rule, the verbatim-reuse rule, and the batch check have only been seen on a
5-contact sample.** None is validated at 34. Run it and read, in order:

1. **m2 CTAs.** The sample went 0/5 on the banned family, but 2 of 5 landed on
   `"Worth exploring whether…"`, an unbanned sibling hedge, and one of those stacked a
   second ask. Does that sibling spread at 34? If it does, it belongs in
   `banned-phrases.md`, not in more guidance.
2. **Batch-level findings.** Expect fewer than the 3 found on replay. Anything left is
   a real verbatim collision.
3. **Shared-prefix openers.** The batch check matches whole sentences only, so the case
   that motivated it is *not* covered: `"One thing that tends to surprise organizers…"`
   went to three contacts with divergent tails. Only the generation-side rule addresses
   that today. If prefixes still collide at 34, decide whether to match on a leading
   n-gram — that is a design call with real false-positive risk.
4. **Sign-off drift.** `model_wrote_footer` WARNs went 4 → 22 after m2 got its job
   definition, with `SIGNOFF` repairs 4 → 20. Repair catches all of it so nothing ships
   broken, but that check exists to detect prompt drift and it is firing loudly.
5. **Empty-response rate.** 4 of 34, then 2 of 34. Every failure ever seen has been a
   nameless `info@`/`contact@` contact, but most nameless contacts succeed, so treat
   that as a weak risk factor and not a cause. Two runs is thin evidence.

### Still parked

- **Placeholder sender names** in `config/senders.md` and the **unconfirmed Smartlead
  unsubscribe token** remain deliberate send-blockers. Both clear during Smartlead
  setup, still pending finance approval.
- **Mailbox-assignment timing.** Assembly needs the sender name during generation, but
  mailbox assignment currently happens at campaign creation. Documented in
  `config/senders.md`; not implemented.
- **Branches 2 and 3 have never been exercised on real data.** Every contact in the
  list routes on `gmv` or `competitor`. The `fallback: vertical/jobtitle/company-type`
  paths and the branch-3 flag remain proven only against synthetic stubs. Testing them
  needs a list with genuinely missing signals, not this one.

---

## Google Sheets review surface
**Trigger:** after copy testing is validated.

Set up a GCP service account and enable the Sheets API, put the key path in
`GOOGLE_SERVICE_ACCOUNT_JSON`, share the target sheet with the service-account email,
then build an "export review dataset to Google Sheet" step. The sheet is the artifact:
share its link in Slack for review, which fits the planned Slack review/approval flow.

**Until then:** generation writes to a local CSV.
