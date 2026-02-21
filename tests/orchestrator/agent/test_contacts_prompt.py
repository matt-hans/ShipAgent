"""Tests for contact injection into agent system prompt."""


from src.orchestrator.agent.system_prompt import (
    MAX_PROMPT_CONTACTS,
    _build_contacts_section,
    build_system_prompt,
)


def test_build_contacts_section_empty():
    """Empty contact list produces no section."""
    result = _build_contacts_section([])
    assert result == ""


def test_build_contacts_section_formats_correctly():
    """Contacts are formatted as @handle — City, ST (roles)."""
    contacts = [
        {"handle": "matt", "city": "San Francisco", "state_province": "CA",
         "use_as_ship_to": True, "use_as_shipper": False},
        {"handle": "warehouse", "city": "New York", "state_province": "NY",
         "use_as_ship_to": True, "use_as_shipper": True},
    ]
    result = _build_contacts_section(contacts)
    assert "@matt" in result
    assert "San Francisco, CA" in result
    assert "ship_to" in result
    assert "@warehouse" in result
    assert "shipper" in result


def test_build_contacts_section_respects_limit():
    """Only MAX_PROMPT_CONTACTS contacts are included."""
    contacts = [
        {"handle": f"c{i}", "city": "City", "state_province": "ST",
         "use_as_ship_to": True, "use_as_shipper": False}
        for i in range(MAX_PROMPT_CONTACTS + 10)
    ]
    result = _build_contacts_section(contacts)
    assert f"@c{MAX_PROMPT_CONTACTS - 1}" in result
    assert f"@c{MAX_PROMPT_CONTACTS}" not in result


def test_build_system_prompt_includes_contacts():
    """build_system_prompt injects contacts section when provided."""
    prompt = build_system_prompt(
        contacts=[
            {"handle": "matt", "city": "SF", "state_province": "CA",
             "use_as_ship_to": True, "use_as_shipper": False},
        ],
    )
    assert "@matt" in prompt
    assert "Saved Contacts" in prompt
    assert "resolve_contact" in prompt


def test_build_system_prompt_no_contacts():
    """build_system_prompt omits contacts section when None."""
    prompt = build_system_prompt(contacts=None)
    assert "Saved Contacts" not in prompt
