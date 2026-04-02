"""Tests for the error code catalog."""

from signalstream.app.errors import ErrorCode, ErrorInfo, error_response


class TestErrorCode:
    """Verify error catalog structure and formatting."""

    def test_all_codes_have_error_info(self):
        """Every enum member must wrap an ErrorInfo."""
        for member in ErrorCode:
            assert isinstance(member.value, ErrorInfo)

    def test_all_codes_have_http_status(self):
        """HTTP status must be a valid 3-digit code."""
        for member in ErrorCode:
            assert 200 <= member.value.http_status <= 599

    def test_all_codes_have_nonempty_message(self):
        for member in ErrorCode:
            assert len(member.value.message) > 0

    def test_all_codes_have_nonempty_action(self):
        for member in ErrorCode:
            assert len(member.value.action) > 0

    def test_code_string_matches_enum_name(self):
        """The code string inside ErrorInfo must match the enum member name."""
        for member in ErrorCode:
            assert member.value.code == member.name


class TestErrorResponse:
    """Verify error_response() builds correct dicts."""

    def test_provider_unreachable_formats(self):
        resp = error_response(ErrorCode.PROVIDER_UNREACHABLE, provider="Claude")
        assert resp["error"] is True
        assert resp["code"] == "PROVIDER_UNREACHABLE"
        assert "Claude" in resp["message"]
        assert resp["action"] == "retry"

    def test_collector_empty_formats(self):
        resp = error_response(ErrorCode.COLLECTOR_EMPTY, topic="bitcoin")
        assert "bitcoin" in resp["message"]

    def test_analysis_partial_formats(self):
        resp = error_response(
            ErrorCode.ANALYSIS_PARTIAL, completed="32", total="37"
        )
        assert "32" in resp["message"]
        assert "37" in resp["message"]
        assert resp["code"] == "ANALYSIS_PARTIAL"

    def test_job_not_found_formats(self):
        resp = error_response(ErrorCode.JOB_NOT_FOUND, job_id="abc-123")
        assert "abc-123" in resp["message"]
