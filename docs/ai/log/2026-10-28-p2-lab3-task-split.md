# 2026-10-28 — Participant 2 — lab 3 task split
**Lab:** 3 · **Commits:** not committed

## Goal
Analyse the lab 3 assignment and split it between the participants the same way as lab 2.

## Done
- `docs/lab3/participant-1.md` (load balancer, encapsulation, 3 instances + connection budget, passive health
  checks, algorithm configs and live switching, distribution stats, diagram, SPOF) and
  `docs/lab3/participant-2.md` (artificial delay middleware, load generator, RR vs Least Connections, node loss
  during writes, scale-out 1/2/3, next bottleneck). Shared sections (agreements, lab 3 boundaries, order of work,
  joint tasks С-1…С-5, coverage of the assignment, defense theory) are identical in both files.
- Knowledge map row in `CLAUDE.md`, lab 3 line and next step in `status.md`.

## Decisions (link ADRs)
None yet — proposals to confirm in С-1: Nginx (passive checks only in open source) or HAProxy (active checks);
LB on host port 8080, backends without published ports; `backend-3` in a `scale` profile; ADR ranges 0031–0035 (P1),
0036–0040 (P2).

## Problems & fixes
- Found while planning: all lab 2 scripts hard-code 8080 / 8082 — moving them behind the LB is a task for each owner
  (П1-5, П2-7). Nginx does not retry POST/PATCH by default, and `proxy_next_upstream http_503` would drop the whole
  pool during a Redis/DB outage (the API answers 503 by design) — both flagged in П1-3 / П2-4.

## Verified (how)
Docs only; shared sections compared with `diff`.

## Not done / next steps
С-1 with Participant 1; lab 2 С-5 / С-6 still open.
