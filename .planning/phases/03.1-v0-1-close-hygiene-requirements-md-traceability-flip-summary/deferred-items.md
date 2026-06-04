
## tldextract `registered_domain` deprecation (discovered Plan 03.1-02 Task 3)

- **Where:** `src/artiscrapper/visit.py:358`, `src/artiscrapper/metrics.py:112` (also uses `registered_domain` per grep — needs verification)
- **What:** tldextract 5.3.1 emits `DeprecationWarning: The 'registered_domain' property is deprecated and will be removed in the next major version. Use 'top_domain_under_public_suffix' instead, which has the same behavior but a more accurate name.`
- **Action deferred to v0.2:** rename `registered_domain` → `top_domain_under_public_suffix` across visit.py + metrics.py when tldextract is bumped to 6.x. Pure rename — same behavior.
- **Why not in 03.1-02:** plan prescribes `registered_domain` explicitly per RESEARCH §5 / WR-01 lines 603-616. tldextract is still on 5.3.1; deprecation is forward-looking only. Out of plan scope (renaming both call sites would deviate from the plan's verbatim recipe).
