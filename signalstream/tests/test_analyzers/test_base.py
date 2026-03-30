"""Tests for signalstream.analyzers.base."""
from __future__ import annotations

import pytest

from signalstream.analyzers.base import BaseAnalyzer
from signalstream.llm.providers.base import BaseProvider


class TestBaseAnalyzer:
    def test_cannot_instantiate_directly(self) -> None:
        from unittest.mock import MagicMock
        mock_provider = MagicMock(spec=BaseProvider)
        with pytest.raises(TypeError):
            BaseAnalyzer(provider=mock_provider, model="test")  # type: ignore[abstract]

    def test_stores_provider_and_model(self) -> None:
        from unittest.mock import MagicMock

        mock_provider = MagicMock(spec=BaseProvider)

        class ConcreteAnalyzer(BaseAnalyzer):
            def analyze(self, *args, **kwargs):
                return []

        analyzer = ConcreteAnalyzer(provider=mock_provider, model="test-model")
        assert analyzer._provider is mock_provider
        assert analyzer._model == "test-model"
