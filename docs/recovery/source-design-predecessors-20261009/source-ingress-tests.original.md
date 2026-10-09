# Proposed source ingress acceptance tests (RED)

These are design-review tests for the proposed target-service contract in
`docs/plugin-backend/source-ingress-contract.md`. There is deliberately no
`src.services.source_ingress` implementation in this branch. They fail with an
explicit missing-feature assertion, rather than treating a skip or mocked service
as a pass. The synthetic authority fixture represents an external trusted
boundary; it does not establish real authentication or protocol readiness.

Run the named file explicitly. Its `_red.py` suffix keeps an unimplemented design
probe out of normal default collection if the design packet is later reviewed;
this is not permission to merge it, ignore it as acceptance, or declare a green
source-ingress feature. Rename/admit it into normal collection when the first
approved implementation slice is ready. Do not blanket xfail these requirements.

Use the integration owner's reviewed bounded runner and offline plugin for every
run. From the repository root, set `SHIPAGENT_VALIDATION_RUNNER` to that reviewed
runner and `SHIPAGENT_TEST_PYTHON` to the approved project virtualenv interpreter:

    python "$SHIPAGENT_VALIDATION_RUNNER" \
      --name source-ingress-contract-red --cwd "$PWD" --seconds 90 -- \
      "$SHIPAGENT_TEST_PYTHON" -m pytest -p offline_pytest \
      tests/services/source_ingress/source_ingress_contract_red.py -q

The integration owner must supply a portable, versioned harness/offline-plugin
entrypoint before integrating these probes; this design-only file ownership does
not include creating or publishing that harness. Do not bypass the offline or
resource controls, or assume an ephemeral recovery-workspace path is available in
another checkout. The observed run below used the owner's recovery harness.

Assertions observe source receipts, availability, original lifetime, isolation,
and the two differently scoped projection outputs. They never inspect private
service dictionaries, database tables or adapter call counts. Additional
concurrency, tampering, process-crash, actual protocol and end-to-end model-boundary
checks remain explicit gates in the contract, not claimed coverage here.

## Observed design-probe result

On source base `c391e8c31e52598a9473de7b0a92f6308dd37a83`, the initial bounded
offline probe reported **38 failed, zero passed** in 0.20 seconds. Every failure
was the explicit missing `src.services.source_ingress` feature assertion. The
runner used 0.915 seconds wall time, sampled a 60.973 MiB peak, hit no resource
limit, and left no surviving process.

After seam-review revisions (opaque epochs, same-ID target fingerprint drift,
closed mapping vocabulary and exact request conflicts), the second bounded run
reported **47 failed, zero passed** in 0.21 seconds, again all at the explicit
missing-feature assertion. The runner used 1.008 seconds wall time and a sampled
60.496 MiB peak, with no limit failure, forced cleanup or survivors. Ruff check
and Ruff format check passed for this test file.

This verifies collection and the missing-feature RED state only. The behavioral
assertions have not run against any implementation. No full regression suite was
run for this design packet, and none is claimed to pass because the probe is
outside default collection.
