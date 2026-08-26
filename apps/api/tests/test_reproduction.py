from maintainer_api.reproduction import StackDetector


def test_stack_detector_python(tmp_path):
    (tmp_path / "pyproject.toml").touch()
    stack, cmd = StackDetector.detect(str(tmp_path))
    assert stack == "python"
    assert cmd == "python3 -m pytest"

def test_stack_detector_node(tmp_path):
    (tmp_path / "package.json").touch()
    stack, cmd = StackDetector.detect(str(tmp_path))
    assert stack == "node"
    assert cmd == "npm test"

def test_stack_detector_go(tmp_path):
    (tmp_path / "go.mod").touch()
    stack, cmd = StackDetector.detect(str(tmp_path))
    assert stack == "go"
    assert cmd == "go test ./..."

def test_stack_detector_rust(tmp_path):
    (tmp_path / "Cargo.toml").touch()
    stack, cmd = StackDetector.detect(str(tmp_path))
    assert stack == "rust"
    assert cmd == "cargo test"

def test_stack_detector_makefile(tmp_path):
    (tmp_path / "Makefile").touch()
    stack, cmd = StackDetector.detect(str(tmp_path))
    assert stack == "makefile"
    assert cmd == "make test"

def test_stack_detector_unknown(tmp_path):
    stack, cmd = StackDetector.detect(str(tmp_path))
    assert stack == "unknown"
    assert cmd == "echo No supported test suite detected"
