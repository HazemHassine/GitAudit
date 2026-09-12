"""Opt-in Docker isolation proof with local fixtures and no live provider requests."""

import os
from uuid import uuid4

import pytest

from maintainer_api.config import Settings
from maintainer_api.sandbox import DockerWorkspace, command

pytestmark = pytest.mark.skipif(os.environ.get("GITAUDIT_DOCKER_TESTS") != "1", reason="Opt-in local Docker isolation test")


async def test_disposable_docker_has_no_credentials_socket_or_test_network(tmp_path):
    (tmp_path / "fixture.txt").write_text("source only")
    settings = Settings(_env_file=None, audit_timeout_seconds=10)
    workspace = DockerWorkspace(settings, uuid4().hex)
    try:
        await workspace.prepare(tmp_path)
        code, output = await workspace.run(["python", "-c", '''
import os, pathlib, socket
assert pathlib.Path('/workspace/fixture.txt').read_text() == 'source only'
assert not pathlib.Path('/var/run/docker.sock').exists()
assert not any('JULES' in k or 'GITHUB' in k or 'OWNER_PASSWORD' in k for k in os.environ)
try:
 pathlib.Path('/etc/gitaudit-test').write_text('no')
 raise AssertionError('root filesystem writable')
except OSError:
 pass
s=socket.socket(); s.settimeout(1)
assert s.connect_ex(('1.1.1.1',443)) != 0
print('isolation verified')
'''])
        assert code == 0, output
        assert "isolation verified" in output
        code, output = await workspace.run(["node", "-e", "console.log('node fixture passed')"])
        assert code == 0 and "node fixture passed" in output
        code, _ = await workspace.run(["python", "-c", "import time; time.sleep(30)"])
        assert code == 124
    finally:
        await workspace.cleanup()
    code, output = await command("docker", "ps", "-aq", "--filter", f"label=gitaudit.identity={workspace.identity}")
    assert code == 0 and not output.strip()
