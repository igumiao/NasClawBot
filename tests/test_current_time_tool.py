"""Tests for CurrentTimeTool."""

from app.tools.current_time import CurrentTimeTool


def test_current_time_schema_has_no_parameters():
    schema = CurrentTimeTool().to_openai_schema()["function"]["parameters"]

    assert schema["required"] == []
    assert schema["additionalProperties"] is False
    assert schema["properties"] == {}


def test_current_time_returns_structured_time_fields():
    response = CurrentTimeTool(timezone_name="Asia/Shanghai").run({})

    assert response.status.value == "success"
    assert response.data["timezone"] == "Asia/Shanghai"
    assert isinstance(response.data["year"], int)
    assert isinstance(response.data["month"], int)
    assert isinstance(response.data["day"], int)
    assert response.data["date"]
    assert response.data["iso"]
    assert response.data["weekday"]
    assert response.data["utc_offset"]


def test_current_time_rejects_parameters():
    response = CurrentTimeTool().run({"timezone": "UTC"})

    assert response.status.value == "error"
    assert response.error_info["code"] == "INVALID_PARAM"


def test_current_time_rejects_unknown_timezone():
    response = CurrentTimeTool(timezone_name="Mars/Base").run({})

    assert response.status.value == "error"
    assert response.error_info["code"] == "INVALID_TIMEZONE"
