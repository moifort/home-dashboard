"""Home lab domain: Komodo records → hourly columns, panel, alerts, transport."""
import pytest

from app.homelab import alerts, rules
from app.homelab.infrastructure import komodo_client

NOW = 1_800_000_000_000  # any instant, in ms
H = rules.HOUR_MS


def _record(age_ms, cpu, mem_used=2.0, disk_used=10.0):
    return {"ts": NOW - age_ms, "cpu_perc": cpu, "mem_used_gb": mem_used, "mem_total_gb": 8.0,
            "disk_used_gb": disk_used, "disk_total_gb": 100.0}


def test_hourly_max_keeps_the_peak_of_each_hour():
    cols = rules.hourly_max([(NOW - 60_000, 12.4), (NOW - 120_000, 87.6),   # last hour
                             (NOW - H - 1, 30), (NOW - 23 * H - 1, 5),
                             (NOW - 24 * H - 1, 99)], NOW)                 # too old
    assert len(cols) == 24
    assert cols[23] == 88 and cols[22] == 30 and cols[0] == 5
    assert cols[1:22] == [None] * 21


def test_node_reads_disk_from_the_latest_record():
    server = {"name": "pi-nas", "state": "Ok", "disk_warning": 75.0}
    node = rules.build_node(server, [_record(5 * H, 40, disk_used=50.0), _record(60_000, 10, mem_used=6.0, disk_used=80.0)], NOW)
    assert node["online"] and node["disk_pct"] == 80 and node["disk_bad"]
    assert node["cpu"][23] == 10 and node["cpu"][18] == 40
    assert node["mem"][23] == 75 and node["mem"][18] == 25


def test_node_without_records_or_threshold():
    node = rules.build_node({"name": "pi", "state": "NotOk"}, [], NOW)
    assert node == {"name": "pi", "online": False, "cpu": [None] * 24, "mem": [None] * 24,
                    "disk_pct": None, "disk_bad": False}
    full = rules.build_node({"name": "pi", "state": "Ok"}, [_record(0, 1, disk_used=91.0)], NOW)
    assert full["disk_bad"]  # falls back to DISK_WARN_PCT


def _node(name, online=True, disk_bad=False, disk_pct=40):
    return {"name": name, "online": online, "disk_bad": disk_bad, "disk_pct": disk_pct}


def test_panel_sorts_by_name_and_counts_every_server():
    panel = rules.build_panel([_node("pi-nas"), _node("Pi-casa"), _node("pi-dns", online=False)])
    assert [n["name"] for n in panel["nodes"]] == ["Pi-casa", "pi-dns", "pi-nas"]
    assert (panel["online"], panel["total"]) == (2, 3)


def test_panel_with_more_servers_than_columns_shows_problems_first():
    nodes = [_node(f"pi-{c}") for c in "abcde"] + [_node("pi-z", online=False)]
    panel = rules.build_panel(nodes)
    assert [n["name"] for n in panel["nodes"]] == ["pi-z", "pi-a", "pi-b", "pi-c"]
    assert (panel["online"], panel["total"]) == (5, 6)


def test_alerts():
    data = {"homelab": {"nodes": [_node("pi-a", online=False), _node("pi-b", online=False),
                                  _node("pi-c", disk_bad=True, disk_pct=91),
                                  _node("pi-d", disk_bad=True, disk_pct=96)]}}
    assert alerts._offline(data) == ("pi-a hors ligne", "+1")
    assert alerts._disk_full(data) == ("Disque pi-d plein", "96%")
    quiet = {"homelab": {"nodes": [_node("pi-a")]}}
    assert alerts._offline(quiet) is None and alerts._disk_full(quiet) is None
    assert alerts._offline({}) is None


class _Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise komodo_client.requests.HTTPError(str(self.status_code))

    def json(self):
        return self._body


class _Session:
    def __init__(self, handler):
        self.handler, self.calls = handler, []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, json, headers))
        return self.handler(url, json)


@pytest.fixture
def komodo(monkeypatch):
    def install(handler):
        session = _Session(handler)
        monkeypatch.setattr(komodo_client, "_session", session)
        monkeypatch.setattr(komodo_client, "_legacy_route", False)
        return session
    return install


def test_fetch_servers_sends_the_key_pair(komodo):
    session = komodo(lambda url, body: _Resp(200, [
        {"id": "s1", "name": "pi-nas", "info": {"state": "Ok", "alerting_thresholds": {"disk_warning": 75.0}}},
        {"id": "s2", "name": "pi-old", "info": {"state": "Disabled"}}]))
    servers = komodo_client.fetch_servers("http://komodo", "k", "s")
    assert servers == [{"id": "s1", "name": "pi-nas", "state": "Ok", "disk_warning": 75.0},
                       {"id": "s2", "name": "pi-old", "state": "Disabled", "disk_warning": None}]
    url, body, headers = session.calls[0]
    assert url == "http://komodo/read/ListServers" and body == {}
    assert headers == {"X-Api-Key": "k", "X-Api-Secret": "s"}


def test_fetch_servers_falls_back_to_the_komodo_1_route(komodo):
    def handler(url, body):
        if url.endswith("/read"):
            assert body == {"type": "ListServers", "params": {}}
            return _Resp(200, [])
        return _Resp(404)
    session = komodo(handler)
    assert komodo_client.fetch_servers("http://komodo", "k", "s") == []
    komodo_client.fetch_servers("http://komodo", "k", "s")
    assert [u for u, *_ in session.calls] == ["http://komodo/read/ListServers", "http://komodo/read",
                                              "http://komodo/read"]  # the fallback is remembered


def test_fetch_servers_returns_none_when_komodo_is_down(komodo):
    komodo(lambda url, body: _Resp(500))
    assert komodo_client.fetch_servers("http://komodo", "k", "s") is None


def test_fetch_history_pages_until_the_window_is_covered(komodo):
    since = NOW - 24 * H

    def handler(url, body):
        assert url == "http://komodo/read/GetHistoricalServerStats"
        assert body["server"] == "s1" and body["granularity"] == "1-min"
        first = NOW - body["page"] * 200 * 60_000
        stats = [{"ts": first - i * 60_000, "cpu_perc": 1.0} for i in range(200)]
        return _Resp(200, {"stats": stats, "next_page": body["page"] + 1})
    session = komodo(handler)
    records = komodo_client.fetch_history("http://komodo", "k", "s", "s1", since)
    assert len(session.calls) == 8          # 1 440 minutes, 200 per page
    assert len(records) == 1440 and all(r["ts"] > since for r in records)


def test_fetch_history_keeps_what_it_read_before_an_error(komodo):
    def handler(url, body):
        if body["page"]:
            return _Resp(500)
        return _Resp(200, {"stats": [{"ts": NOW - 60_000, "cpu_perc": 3.0}] * 200, "next_page": 1})
    komodo(handler)
    assert len(komodo_client.fetch_history("http://komodo", "k", "s", "s1", NOW - 24 * H)) == 200


def test_attach_builds_the_panel_and_skips_disabled_servers(monkeypatch):
    from app.homelab import query
    monkeypatch.setattr(query.komodo_client, "fetch_servers", lambda *a: [
        {"id": "s1", "name": "pi-nas", "state": "Ok", "disk_warning": None},
        {"id": "s2", "name": "pi-old", "state": "Disabled", "disk_warning": None}])
    monkeypatch.setattr(query.komodo_client, "fetch_history", lambda *a: [])
    data = {}
    query.attach(data)
    assert [n["name"] for n in data["homelab"]["nodes"]] == ["pi-nas"]
    assert data["homelab"]["total"] == 1

    monkeypatch.setattr(query.komodo_client, "fetch_servers", lambda *a: None)
    data = {}
    query.attach(data)
    assert "homelab" not in data
