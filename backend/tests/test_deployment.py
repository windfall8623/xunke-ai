"""Deployment invariants for loopback scoring across an API-only outage.

These checks read Compose YAML only. Real container restart acceptance is a
separate deployment test; no Docker daemon or application services are touched.
"""

from pathlib import Path

import pytest
import yaml


DEPLOY = Path(__file__).resolve().parents[2] / "deploy"


class ComposeLoader(yaml.SafeLoader):
    pass


ComposeLoader.add_constructor(
    "!override", lambda loader, node: loader.construct_sequence(node)
)


def configuration(filename="compose.yaml"):
    return yaml.load(
        (DEPLOY / filename).read_text(encoding="utf-8"), Loader=ComposeLoader
    )


def network_owner(services, name):
    visited = set()
    while services[name].get("network_mode", "").startswith("service:"):
        assert name not in visited, "Network namespace dependencies must not cycle"
        visited.add(name)
        name = services[name]["network_mode"].split(":", 1)[1]
    return name


def test_api_outage_does_not_stop_the_scorers_namespace_owner():
    services = configuration()["services"]
    owner = network_owner(services, "eval-scorer")
    assert owner not in {"api", "eval-scorer"}, (
        "Scorer restart must not require the unavailable API container to run"
    )
    assert network_owner(services, "api") == owner
    holder = services[owner]
    assert not holder.get("depends_on"), (
        "The holder must outlive API and database outages"
    )
    assert "api" in holder["networks"]["default"]["aliases"]
    for name in ("api", "eval-scorer"):
        assert services[name]["depends_on"][owner]["condition"] == "service_started"
        assert services[name]["depends_on"][owner]["restart"] is True
        assert not services[name].get("ports")
        assert not services[name].get("networks")


def test_namespace_holder_is_inert_without_credentials_or_data_mounts():
    services = configuration()["services"]
    assert "control-network" in services
    holder = services["control-network"]
    assert holder["image"] == services["api"]["image"]
    assert holder["command"] == ["python", "-c", "import signal; signal.pause()"]
    assert holder["healthcheck"] == {"disable": True}
    assert holder["restart"] == "unless-stopped"
    assert holder["read_only"] is True
    assert holder["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in holder["security_opt"]
    for key in (
        "environment",
        "env_file",
        "volumes",
        "volumes_from",
        "ports",
        "pid",
        "privileged",
    ):
        assert not holder.get(key), f"The namespace holder must not inherit {key}"


def test_loopback_control_and_scorer_data_isolation_are_preserved():
    services = configuration()["services"]
    scorer = services["eval-scorer"]
    assert scorer["environment"]["EVAL_CONTROL_URL"] == "http://127.0.0.1:8000/api/v1"
    assert "EVAL_WORKER_TOKEN" in scorer["environment"]
    assert not any(key.startswith("MYSQL_") for key in scorer["environment"])
    assert not scorer.get("volumes") and not scorer.get("env_file")
    assert not scorer.get("pid") and not scorer.get("privileged")
    assert scorer["image"] != services["api"]["image"]
    assert scorer["depends_on"]["api"]["condition"] == "service_healthy"
    assert services["api"]["depends_on"]["mysql"]["condition"] == "service_healthy"
    nginx = (DEPLOY / "nginx-app.conf").read_text(encoding="utf-8")
    assert "location = /api/v1/internal { return 404; }" in nginx
    assert "location ^~ /api/v1/internal/ { return 404; }" in nginx
    assert "http://api:8000" in nginx


@pytest.mark.parametrize("filename", ["compose.local.yaml", "compose.judge.yaml"])
def test_deployment_overrides_do_not_replace_the_control_namespace(filename):
    services = configuration(filename)["services"]
    assert "control-network" not in services
    for name in ("api", "eval-scorer"):
        override = services.get(name, {})
        assert not {"network_mode", "networks", "ports", "depends_on"} & override.keys()
    assert not services.get("eval-scorer", {}).get("volumes")
