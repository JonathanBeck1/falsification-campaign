"""EarningsToneFeatures Pydantic schema tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from trader.signals.earnings_tone_features import EarningsToneFeatures


def _valid_payload() -> dict:
    return {
        "schema_version": "earnings-tone-v1",
        "aggregate_tone": "bullish",
        "guidance_signal": "raised",
        "breadth": "majority_aligned",
        "confidence": "high",
        "abstain_reason": None,
    }


def test_valid_payload_parses():
    feat = EarningsToneFeatures.model_validate(_valid_payload())
    assert feat.aggregate_tone == "bullish"
    assert feat.guidance_signal == "raised"
    assert feat.confidence == "high"
    assert feat.abstain_reason is None


def test_abstain_reason_optional():
    payload = _valid_payload()
    del payload["abstain_reason"]
    feat = EarningsToneFeatures.model_validate(payload)
    assert feat.abstain_reason is None


def test_abstain_reason_can_be_string():
    payload = _valid_payload()
    payload["abstain_reason"] = "too few filings"
    feat = EarningsToneFeatures.model_validate(payload)
    assert feat.abstain_reason == "too few filings"


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("aggregate_tone", "very_bullish"),
        ("guidance_signal", "withdrawn"),
        ("breadth", "broad"),
        ("confidence", "supreme"),
        ("schema_version", "earnings-tone-v2"),
    ],
)
def test_extra_label_rejected(field: str, bad_value: str):
    payload = _valid_payload()
    payload[field] = bad_value
    with pytest.raises(ValidationError):
        EarningsToneFeatures.model_validate(payload)


def test_extra_fields_forbidden():
    payload = _valid_payload()
    payload["sneak_field"] = "should not be allowed"
    with pytest.raises(ValidationError):
        EarningsToneFeatures.model_validate(payload)


def test_missing_required_field_rejected():
    payload = _valid_payload()
    del payload["aggregate_tone"]
    with pytest.raises(ValidationError):
        EarningsToneFeatures.model_validate(payload)
