from granola_mcp.server import ListMeetingsInput, _build_list_args


def test_date_uses_created_at_half_open_los_angeles_range() -> None:
    args = _build_list_args(
        ListMeetingsInput(date="2026-07-15", timezone="America/Los_Angeles")
    )

    assert "--created-since" in args
    assert args[args.index("--created-since") + 1] == "2026-07-15T07:00:00Z"
    assert "--created-until" in args
    assert args[args.index("--created-until") + 1] == "2026-07-16T07:00:00Z"
    assert "--updated-since" not in args


def test_explicit_created_and_updated_filters_are_independent() -> None:
    args = _build_list_args(
        ListMeetingsInput(
            created_since="2026-07-15T09:00:00-07:00",
            updated_until="2026-07-20",
            timezone="America/Los_Angeles",
        )
    )

    assert args[args.index("--created-since") + 1] == "2026-07-15T16:00:00Z"
    assert args[args.index("--updated-until") + 1] == "2026-07-21T07:00:00Z"


def test_date_rejects_a_second_created_range() -> None:
    params = ListMeetingsInput(date="2026-07-15", created_since="2026-07-14")

    try:
        _build_list_args(params)
    except ValueError as exc:
        assert "date cannot be combined" in str(exc)
    else:
        raise AssertionError("expected conflicting filters to be rejected")


def test_created_range_rejects_reversed_bounds() -> None:
    params = ListMeetingsInput(
        created_since="2026-07-16T00:00:00Z",
        created_until="2026-07-15T00:00:00Z",
    )

    try:
        _build_list_args(params)
    except ValueError as exc:
        assert "created_since must be before created_until" in str(exc)
    else:
        raise AssertionError("expected reversed bounds to be rejected")
