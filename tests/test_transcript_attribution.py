from granola_mcp.server import _format_transcript_markdown


def test_transcript_markdown_uses_granola_nested_speaker_and_keeps_source() -> None:
    markdown = _format_transcript_markdown(
        [
            {
                "source": "system",
                "start_timestamp": "2026-07-22T16:31:21Z",
                "text": "Thanks for that.",
                "detectedSpeaker": {"participantName": "Gary Grossman"},
            }
        ]
    )

    assert "**Gary Grossman**" in markdown
    assert "source: system" in markdown


def test_transcript_markdown_does_not_infer_identity_for_unnamed_channel() -> None:
    markdown = _format_transcript_markdown(
        [
            {
                "source": "system",
                "start_timestamp": "2026-07-22T16:31:21Z",
                "text": "Hello.",
            }
        ]
    )

    assert "**system audio**" in markdown
    assert "Participant" not in markdown
    assert "You" not in markdown


def test_transcript_markdown_falls_back_to_legacy_speaker_name() -> None:
    markdown = _format_transcript_markdown(
        [
            {
                "source": "system",
                "start_timestamp": "2026-07-22T16:31:21Z",
                "text": "Hello.",
                "detected_speaker_name": "Gary",
            }
        ]
    )

    assert "**Gary**" in markdown
