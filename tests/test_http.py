import httpx
import pytest
import respx

from tr.http import APIClient, APIError

HOST = "https://example.testrail.io"


def make_client(**kwargs) -> APIClient:
    kwargs.setdefault("sleep_s", 0.0)
    return APIClient(host=HOST, email="qa@example.com", api_key="secret", **kwargs)


@respx.mock
def test_get_retries_after_429_then_succeeds(no_sleep):
    route = respx.get(url__startswith=f"{HOST}/index.php").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "rate"}),
            httpx.Response(200, json={"id": 42, "title": "Login with expired token"}),
        ]
    )
    body = make_client().get("get_case/42")
    assert body == {"id": 42, "title": "Login with expired token"}
    assert route.call_count == 2


@respx.mock
def test_get_retries_after_502_then_succeeds(no_sleep):
    route = respx.get(url__startswith=f"{HOST}/index.php").mock(
        side_effect=[
            httpx.Response(502, text="bad gateway"),
            httpx.Response(200, json={"id": 7}),
        ]
    )
    assert make_client().get("get_case/7") == {"id": 7}
    assert route.call_count == 2
    assert no_sleep == [1.0]


@respx.mock
def test_get_raises_api_error_after_max_retries(no_sleep):
    respx.get(url__startswith=f"{HOST}/index.php").mock(
        return_value=httpx.Response(503, text="down")
    )
    with pytest.raises(APIError) as exc:
        make_client(max_retries=3).get("get_case/7")
    assert exc.value.status == 503
    assert "down" in exc.value.body


@respx.mock
def test_get_does_not_retry_on_400(no_sleep):
    route = respx.get(url__startswith=f"{HOST}/index.php").mock(
        return_value=httpx.Response(400, text="bad field")
    )
    with pytest.raises(APIError):
        make_client().get("get_case/7")
    assert route.call_count == 1


@respx.mock
def test_paginate_follows_next_links(no_sleep):
    pages = [
        httpx.Response(
            200,
            json={
                "offset": 0,
                "limit": 2,
                "size": 5,
                "_links": {"next": "/api/v2/get_cases/34&limit=2&offset=2", "prev": None},
                "cases": [{"id": 11}, {"id": 12}],
            },
        ),
        httpx.Response(
            200,
            json={
                "offset": 2,
                "limit": 2,
                "size": 5,
                "_links": {"next": "/api/v2/get_cases/34&limit=2&offset=4", "prev": None},
                "cases": [{"id": 13}, {"id": 14}],
            },
        ),
        httpx.Response(
            200,
            json={
                "offset": 4,
                "limit": 2,
                "size": 5,
                "_links": {"next": None, "prev": None},
                "cases": [{"id": 15}],
            },
        ),
    ]
    route = respx.get(url__startswith=f"{HOST}/index.php").mock(side_effect=pages)
    result = make_client().paginate("get_cases/34", {"limit": "2"})
    assert route.call_count == 3
    assert [c["id"] for c in result["cases"]] == [11, 12, 13, 14, 15]
    assert result["size"] == 5
    assert result["pages"] == 3
    assert result["_links"] == {"next": None, "prev": None}


@respx.mock
def test_paginate_stops_at_max_pages(no_sleep):
    endless = httpx.Response(
        200,
        json={
            "size": 999,
            "_links": {"next": "/api/v2/get_cases/34&limit=2&offset=2", "prev": None},
            "cases": [{"id": 21}, {"id": 22}],
        },
    )
    route = respx.get(url__startswith=f"{HOST}/index.php").mock(return_value=endless)
    result = make_client().paginate("get_cases/34", None, max_pages=2)
    assert route.call_count == 2
    assert result["pages"] == 2
    assert len(result["cases"]) == 4


@respx.mock
def test_paginate_returns_bare_list_as_is(no_sleep):
    route = respx.get(url__startswith=f"{HOST}/index.php").mock(
        return_value=httpx.Response(200, json=[{"id": 31}, {"id": 32}])
    )
    assert make_client().paginate("get_sections/34", None) == [{"id": 31}, {"id": 32}]
    assert route.call_count == 1


@respx.mock
def test_request_line_logged_to_stderr_without_key(capsys, no_sleep):
    respx.get(url__startswith=f"{HOST}/index.php").mock(
        return_value=httpx.Response(200, json={"id": 42})
    )
    make_client().get("get_case/42")
    err = capsys.readouterr().err
    assert "-> GET get_case/42" in err
    assert "secret" not in err


@respx.mock
def test_post_sends_json_body(no_sleep):
    route = respx.post(url__startswith=f"{HOST}/index.php").mock(
        return_value=httpx.Response(200, json={"id": 900})
    )
    assert make_client().post("add_run/34", {"name": "smoke"}) == {"id": 900}
    assert route.calls[0].request.headers["content-type"] == "application/json"
