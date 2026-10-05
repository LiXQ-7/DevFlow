import pytest

from devflow.config import Config
from devflow.tools import make_tools


@pytest.fixture
def cfg(tmp_path):
    return Config(project_root=tmp_path, allow_shell=True)


@pytest.fixture
def tools(cfg):
    return {tool.name: tool for tool in make_tools(cfg)}
