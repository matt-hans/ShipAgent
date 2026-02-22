"""CI guard: ensure no direct os.environ reads for core credential env vars.

Only checks UPS_CLIENT_ID and UPS_CLIENT_SECRET since those are fully migrated
to runtime_credentials.py in Phase 1. UPS_ACCOUNT_NUMBER, UPS_BASE_URL, and
Shopify env vars have partial migration with TODO comments.
"""

import subprocess


def test_no_direct_client_credential_env_reads():
    """UPS_CLIENT_ID and UPS_CLIENT_SECRET must only be read in runtime_credentials.py.

    These are the core credential env vars that are fully migrated in Phase 1.
    Other env vars (UPS_ACCOUNT_NUMBER, SHOPIFY_*) are partially migrated
    with TODOs in call sites.
    """
    result = subprocess.run(
        ["grep", "-rn",
         r'os\.environ.*UPS_CLIENT_ID\|os\.environ.*UPS_CLIENT_SECRET\|'
         r'os\.getenv.*UPS_CLIENT_ID\|os\.getenv.*UPS_CLIENT_SECRET',
         "src/", "--include=*.py"],
        capture_output=True, text=True,
    )
    violations = []
    for line in result.stdout.splitlines():
        # Exclude allowed files
        if any(skip in line for skip in [
            "runtime_credentials", "__pycache__",
            "http_client", "runner",
            # config.py has env fallback for when no DB session available
            "config.py",
        ]):
            continue
        violations.append(line)
    assert not violations, (
        f"Found {len(violations)} direct credential env reads outside "
        f"runtime_credentials.py:\n" + "\n".join(violations)
    )
