import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tdd_enforcer import is_test_file, is_impl_file, suggest_test_path, find_test_file


# --- is_test_file ---

def test_is_test_file_python():
    assert is_test_file(Path("tests/test_user.py"))
    assert is_test_file(Path("test_service.py"))


def test_is_test_file_js():
    assert is_test_file(Path("__tests__/UserService.test.ts"))
    assert is_test_file(Path("src/api.spec.js"))


def test_is_test_file_dart():
    assert is_test_file(Path("test/widget_test.dart"))


def test_is_not_test_file():
    assert not is_test_file(Path("src/user.py"))
    assert not is_test_file(Path("lib/widget.dart"))
    assert not is_test_file(Path("internal/server.go"))


# --- is_impl_file ---

def test_is_impl_file_basic():
    assert is_impl_file(Path("src/service.py"))
    assert is_impl_file(Path("lib/widget.dart"))
    assert is_impl_file(Path("internal/handler.go"))


def test_is_impl_file_skip_names():
    assert not is_impl_file(Path("setup.py"))
    assert not is_impl_file(Path("conftest.py"))
    assert not is_impl_file(Path("main.dart"))


def test_is_impl_file_generated():
    assert not is_impl_file(Path("user.g.dart"))
    assert not is_impl_file(Path("api.generated.ts"))
    assert not is_impl_file(Path("msg.pb.go"))


def test_is_impl_file_skip_dirs():
    assert not is_impl_file(Path("node_modules/pkg/index.js"))
    assert not is_impl_file(Path("build/output.dart"))


def test_is_impl_file_wrong_extension():
    assert not is_impl_file(Path("readme.md"))
    assert not is_impl_file(Path("config.yaml"))


# --- suggest_test_path ---

def test_suggest_python_src():
    result = suggest_test_path(Path("src/user.py"))
    assert result == str(Path("tests/test_user.py"))


def test_suggest_dart_lib():
    result = suggest_test_path(Path("lib/widget.dart"))
    assert result == str(Path("test/widget_test.dart"))


def test_suggest_ts_src():
    result = suggest_test_path(Path("src/api.ts"))
    assert result == str(Path("tests/api.test.ts"))


def test_suggest_go_internal():
    result = suggest_test_path(Path("internal/handler.go"))
    assert result == str(Path("tests/handler_test.go"))


def test_suggest_kotlin():
    result = suggest_test_path(Path("src/UserService.kt"))
    assert result == str(Path("tests/UserServiceTest.kt"))


def test_suggest_swift():
    result = suggest_test_path(Path("app/Auth.swift"))
    assert result == str(Path("tests/AuthTests.swift"))


def test_suggest_no_impl_dir():
    result = suggest_test_path(Path("standalone/module.py"))
    assert result == str(Path("standalone/test_module.py"))


def test_suggest_nested_path():
    result = suggest_test_path(Path("src/features/auth/login_service.py"))
    assert result == str(Path("tests/features/auth/test_login_service.py"))


# --- find_test_file ---

def test_find_test_file_in_tests_dir(tmp_path):
    impl = tmp_path / "service.py"
    impl.write_text("class Service: pass")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_service.py"
    test_file.write_text("def test_service(): pass")
    assert find_test_file(impl)


def test_find_test_file_sibling(tmp_path):
    impl = tmp_path / "handler.py"
    impl.write_text("def handle(): pass")
    test_file = tmp_path / "test_handler.py"
    test_file.write_text("def test_handle(): pass")
    assert find_test_file(impl)


def test_find_test_file_not_found(tmp_path):
    impl = tmp_path / "lonely.py"
    impl.write_text("def lonely(): pass")
    assert not find_test_file(impl)


def test_find_test_file_deep_nested(tmp_path):
    """Test finds tests 4+ levels up."""
    impl_dir = tmp_path / "src" / "features" / "auth" / "login"
    impl_dir.mkdir(parents=True)
    impl = impl_dir / "service.py"
    impl.write_text("class Service: pass")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_service.py"
    test_file.write_text("def test_service(): pass")
    assert find_test_file(impl)


def test_find_test_file_monorepo(tmp_path):
    """Test finds tests in monorepo packages/*/test layout."""
    pkg_src = tmp_path / "packages" / "auth" / "src"
    pkg_src.mkdir(parents=True)
    impl = pkg_src / "handler.py"
    impl.write_text("def handle(): pass")
    test_dir = tmp_path / "packages" / "auth" / "test"
    test_dir.mkdir(parents=True)
    test_file = test_dir / "test_handler.py"
    test_file.write_text("def test_handle(): pass")
    assert find_test_file(impl)
