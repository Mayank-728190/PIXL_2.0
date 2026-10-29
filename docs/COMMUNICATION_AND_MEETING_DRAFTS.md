# PIXL 2.0 — Communication, Meetings and Project Ownership

## 1. Current evidence

**Drafts only.** No calendar invitation, meeting link, Slack message or Granola distribution has been sent or verified from this repository. External calendar/Slack/Granola integrations have not been used here. Named attendees below come from the supplied requirements; organizer and authorized recipient lists still need confirmation.

Tracks COM-01–09 in [document 17](17_REQUIREMENTS_TRACEABILITY_MATRIX.md).

## 2. Calendar invitation draft

- **Title:** PIXL 2.0 — Product and Engineering Check-in
- **Proposed recurrence:** Tuesdays and Thursdays, 11:00–11:30 Asia/Kolkata; confirm before sending. This is twice weekly, not an ambiguous weekly recurrence.
- **Organizer:** Engineering lead or delegated project coordinator — name pending.
- **Meeting link:** Pending organizer-created Google Meet/Zoom/Teams URL. Do not send the event without a working link.
- **Required attendee:** Aniket.
- **Optional attendee:** Aayog.
- **Notes distribution:** Raj plus approved relevant team members; confirm addresses/channel permissions first.

Agenda (30 minutes):
1. P0–P3 progress and evidence, including early completions (5 min).
2. Product/design walkthrough and end-user friction (10 min).
3. Scope decisions, hardware/provisioning, assignment and payment questions (5 min).
4. Blockers, dependencies, availability and deadline risks (5 min).
5. Named actions, due dates and next milestone (5 min).

Organizer checklist:
- [ ] Confirm recurrence/timezone and actual attendee addresses.
- [ ] Create event with required/optional flags and meeting link; send invitation.
- [ ] Verify link and delivery; record actual event ID/URL in the authorized tracker.
- [ ] Share approved notes with Raj and relevant participants.

## 3. Notes and Granola distribution

Use approved meeting capture with participant consent and organizational policy. Review notes for errors, private client data, credentials, signed URLs and inappropriate recipients before sharing. Send relevant Granola notes to authorized relevant team members through the approved workspace/channel; do not make notes public or upload them to unapproved services.

Proposed target: approved notes by the next working day. Record date, meeting link/event ID, summary, decisions, action owner/due date, blockers, recipients and delivery evidence. If tooling is unavailable, prepare reviewed notes and request an authorized person to send them; keep delivery status Pending rather than claiming synchronization.

## 4. Responsiveness and availability agreement

These are proposed working norms requiring team agreement, not retroactive performance claims:

- Publish agreed working hours/timezone and Slack response expectations. Suggested acknowledgment target: within 4 working hours during declared availability; urgent incidents use the agreed escalation channel rather than assuming Slack is monitored continuously.
- Announce planned unavailability in advance where possible, especially exams, leave and other commitments. Include absence window, deadline impact, handoff owner and return time. Unexpected absence: notify as soon as practical.
- Update availability when plans change. Do not commit to a due date that conflicts with known availability without discussing a handoff/replan.
- Every assigned task has a named owner, requirement IDs, acceptance criteria and deadline. Owner proactively reports blockers with impact, attempted remedies, needed decision and next update time; do not wait for the next meeting.
- Report early completion promptly with artifact/PR, test evidence and any next task proposal. Do not wait for the scheduled check-in.
- Think as product owner/end user: identify friction, ask about ambiguous outcomes, propose options and tradeoffs, and record decisions. Do not silently invent permissions, payment rules or security guarantees.

## 5. Status update template

```markdown
### PIXL 2.0 — [date/time/timezone]
- Completed: [requirement IDs, artifact/PR and verified evidence; distinguish Specified from Implemented/Tested]
- In progress: [owner, scope, due date and remaining work]
- Next: [next task and dependencies]
- Blockers/risks: [impact, mitigation, needed help, next update; say none only after checking]
- Decisions needed: [question, options, recommendation, decision owner/deadline]
- Evidence/test results: [build/environment, actual results, report link; say Not run when applicable]
- Availability/handoff: [upcoming commitments, working hours and delegate if needed]
```

## 6. Truthful initial project update

- **Specified:** architecture documents, requirements baseline, UI/media/kiosk specifications, traceability and planned acceptance gates.
- **Implementation:** not present in this repository; source repository/runtime access required to inspect or change the existing application.
- **Tests:** no application tests run; specification review is not runtime verification.
- **Decisions:** visual approval, Android hardware/provisioning, purchase flow/currency, retention/deletion policy, live-status tuning, meeting schedule/link and named task owners remain pending.
- **External actions:** calendar invitation and notes distribution require authorized execution; drafts are not sent events/messages.
