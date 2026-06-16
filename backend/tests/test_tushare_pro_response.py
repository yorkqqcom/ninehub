"""Tushare Pro raw response parsing (iteration-200)."""

from app.services.tushare.pro_response import parse_permission_info


def test_parse_permission_from_msg_with_required_points() -> None:
    payload = {
        "code": -2002,
        "msg": "抱歉，您没有接口访问权限，该接口需要至少2000积分才可以调取",
        "data": None,
    }
    info = parse_permission_info(payload)
    assert info["is_permission_error"] is True
    assert info["api_live_min_points"] == 2000
    assert info["interface_level"] == 2000
    assert info["min_points_source"] == "api_live_msg"


def test_parse_permission_from_structured_data() -> None:
    payload = {
        "code": -2002,
        "msg": "权限不足",
        "data": {"interface_level": 5000, "min_point": 5000},
    }
    info = parse_permission_info(payload)
    assert info["api_live_min_points"] == 5000
    assert info["interface_level"] == 5000
    assert info["min_points_source"] == "api_live"


def test_parse_permission_interface_level_only() -> None:
    payload = {
        "code": -2002,
        "msg": "无权限",
        "data": {"interface_level": 120},
    }
    info = parse_permission_info(payload)
    assert info["api_live_min_points"] == 120
    assert info["interface_level"] == 120


def test_non_permission_error() -> None:
    payload = {"code": -1, "msg": "参数错误", "data": None}
    info = parse_permission_info(payload)
    assert info["is_permission_error"] is False
    assert info["api_live_min_points"] is None
