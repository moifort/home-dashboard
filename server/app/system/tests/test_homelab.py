"""Home lab domain: Komodo servers and containers → cards, panel, alerts, transport."""
import pytest

from app import homelab
from app.homelab import alerts, rules
from app.homelab.infrastructure import komodo_client, node_exporter


def _server(name="pi-nas", state="Ok", mem=31.4, disk=40.0, **limits):
    return {"id": name, "name": name, "state": state, "mem_pct": mem, "disk_pct": disk,
            "mem_warning": limits.get("mem_warning"), "disk_warning": limits.get("disk_warning")}


def test_node_carries_the_figures_and_their_alarms():
    node = rules.build_node(_server(mem=31.4, disk=80.2, disk_warning=75.0), (3, 4), 52.6)
    assert node == {"name": "pi-nas", "online": True, "temp": 53, "temp_bad": False,
                    "mem_pct": 31, "mem_bad": False, "disk_pct": 80, "disk_bad": True,
                    "up": 3, "containers": 4}
    assert rules.containers_down(node) == 1 and rules.has_problem(node)


def test_node_without_figures_or_thresholds():
    node = rules.build_node(_server("pi", state="NotOk", mem=None, disk=None))
    assert node == {"name": "pi", "online": False, "temp": None, "temp_bad": False,
                    "mem_pct": None, "mem_bad": False, "disk_pct": None, "disk_bad": False,
                    "up": None, "containers": None}
    full = rules.build_node(_server(mem=92.0, disk=91.0), (2, 2), 71.0)
    assert full["disk_bad"] and full["mem_bad"] and full["temp_bad"]  # default thresholds
    assert not rules.has_problem(rules.build_node(_server(), (2, 2), 50.0))


def _node(name, online=True, disk_bad=False, disk_pct=40, temp=None, temp_bad=False, up=None, containers=None):
    return {"name": name, "online": online, "disk_bad": disk_bad, "disk_pct": disk_pct,
            "temp": temp, "temp_bad": temp_bad, "up": up, "containers": containers}


def test_panel_sorts_by_name_and_counts_every_server():
    panel = rules.build_panel([_node("pi-nas"), _node("Pi-casa"), _node("pi-dns", online=False)])
    assert [n["name"] for n in panel["nodes"]] == ["Pi-casa", "pi-dns", "pi-nas"]
    assert (panel["online"], panel["total"]) == (2, 3)


def test_panel_with_more_servers_than_columns_shows_problems_first():
    nodes = [_node(f"pi-{c}") for c in "abcdefg"] + [_node("pi-z", online=False)]
    panel = rules.build_panel(nodes)
    assert [n["name"] for n in panel["nodes"]] == ["pi-z", "pi-a", "pi-b", "pi-c", "pi-d", "pi-e"]
    assert (panel["online"], panel["total"]) == (7, 8)


def test_alerts():
    data = {"homelab": {"nodes": [_node("pi-a", online=False), _node("pi-b", online=False),
                                  _node("pi-c", disk_bad=True, disk_pct=91),
                                  _node("pi-d", disk_bad=True, disk_pct=96, temp=74, temp_bad=True),
                                  _node("pi-e", up=1, containers=3), _node("pi-f", up=2, containers=3)]}}
    assert alerts._offline(data) == ("pi-a hors ligne", "+1")
    assert alerts._disk_full(data) == ("Disque pi-d plein", "96%")
    assert alerts._hot(data) == ("pi-d chaud", "74°")
    assert alerts._container_down(data) == ("Conteneur arrêté sur pi-e", "3")
    quiet = {"homelab": {"nodes": [_node("pi-a", temp=50, up=2, containers=2)]}}
    assert all(rule.fn(quiet) is None for rule in alerts.RULES)
    assert alerts._offline({}) is None


def test_temp_urls_are_keyed_by_server_name():
    assert homelab._parse_temp_urls(" pi-nas=http://10.0.0.2:9100/metrics ; pi-dns = http://10.0.0.3:9100/metrics;;bad") == {
        "pi-nas": "http://10.0.0.2:9100/metrics", "pi-dns": "http://10.0.0.3:9100/metrics"}
    assert homelab._parse_temp_urls("") == {}


def test_exporter_page_gives_the_hottest_sensor():
    page = ('# HELP node_thermal_zone_temp Zone temperature in Celsius\n'
            'node_thermal_zone_temp{type="cpu-thermal",zone="0"} 47.712\n'
            'node_hwmon_temp_celsius{chip="thermal_thermal_zone0",sensor="temp1"} 4.82e+01\n'
            'node_cpu_seconds_total{cpu="0"} 99\n')
    assert node_exporter.parse_temp(page) == 48.2
    assert node_exporter.parse_temp("node_load1 0.4\n") is None


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
        {"id": "s1", "name": "pi-nas", "info": {
            "state": "Ok", "alerting_thresholds": {"mem_warning": 75.0, "disk_warning": 80.0},
            "stats": {"mem_used_gb": 2.0, "mem_total_gb": 8.0, "disk_used_gb": 45.0, "disk_total_gb": 50.0}}},
        {"id": "s2", "name": "pi-old", "info": {"state": "Disabled"}}]))
    servers = komodo_client.fetch_servers("http://komodo", "k", "s")
    assert servers == [{"id": "s1", "name": "pi-nas", "state": "Ok", "mem_pct": 25.0, "disk_pct": 90.0,
                        "mem_warning": 75.0, "disk_warning": 80.0},
                       {"id": "s2", "name": "pi-old", "state": "Disabled", "mem_pct": None, "disk_pct": None,
                        "mem_warning": None, "disk_warning": None}]
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


def test_fetch_containers_counts_the_running_ones_per_server(komodo):
    session = komodo(lambda url, body: _Resp(200, [
        {"server_id": "s1", "name": "a", "state": "running"}, {"server_id": "s1", "name": "b", "state": "exited"},
        {"server_id": "s2", "name": "c", "state": "running"}]))
    assert komodo_client.fetch_containers("http://komodo", "k", "s") == {"s1": (1, 2), "s2": (1, 1)}
    assert session.calls[0][:2] == ("http://komodo/read/ListAllDockerContainers", {"servers": []})


def test_fetch_containers_returns_none_when_komodo_refuses(komodo):
    komodo(lambda url, body: _Resp(403))
    assert komodo_client.fetch_containers("http://komodo", "k", "s") is None


@pytest.fixture
def reader(monkeypatch):
    """The command module with an empty cache, a scripted Komodo and exporter."""
    from app.homelab import command
    monkeypatch.setattr(command, "_cache", None)
    monkeypatch.setattr(homelab, "TEMP_URLS", {"pi-nas": "http://pi-nas:9100/metrics"})
    calls = []

    def script(servers, containers=None):
        monkeypatch.setattr(command.komodo_client, "fetch_servers", lambda *a: calls.append("list") or servers)
        monkeypatch.setattr(command.komodo_client, "fetch_containers", lambda *a: containers)
        monkeypatch.setattr(command.node_exporter, "fetch_temp", lambda url: calls.append(url) or 51.4)
    command.script, command.calls = script, calls
    return command


def test_attach_reads_komodo_once_then_serves_the_cache(reader):
    from app.homelab import query
    reader.script([_server("pi-nas"), _server("pi-dns"), _server("pi-old", state="Disabled")],
                  containers={"pi-nas": (3, 4)})
    first, second = {}, {}
    query.attach(first)
    query.attach(second)
    dns, nas = first["homelab"]["nodes"]                                 # disabled server left out
    assert (nas["name"], nas["temp"], nas["up"], nas["containers"]) == ("pi-nas", 51, 3, 4)
    assert (dns["name"], dns["temp"], dns["containers"]) == ("pi-dns", None, None)  # no exporter, no container
    assert first["homelab"]["total"] == 2 and second == first
    assert reader.calls == ["list", "http://pi-nas:9100/metrics"]        # the second render hit no network
    assert query.status()["last_homelab"]


def test_attach_drops_a_stale_panel_when_komodo_is_down(reader, monkeypatch):
    from app.homelab import query
    reader.script([_server("pi-nas")])
    reader.refresh()
    reader.script(None)                                                  # Komodo stops answering
    kept = {}
    query.attach(kept)
    assert "homelab" in kept                                             # still fresh: served from memory
    panel, read_at = reader._cache
    monkeypatch.setattr(reader, "_cache", (panel, read_at - reader.STALE_S - 1))
    stale = {}
    query.attach(stale)
    assert "homelab" not in stale
