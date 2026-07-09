"""Tests for IPC router — command registration, routing, error handling."""

from __future__ import annotations

from src.ipc_router import (
    ERR_EXECUTION,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
    IpcRouter,
    _error_response,
    _success_response,
)


class TestIpcRouter:
    """Tests for the IpcRouter command dispatch class."""

    def test_register_and_handle_success(self):
        """Register a handler and route a command to it."""
        router = IpcRouter()

        def ping(params: dict, shared: dict) -> dict:
            return {"pong": True, "echo": params.get("msg", "")}

        router.register("ping", ping)
        result = router.handle({"id": 1, "method": "ping", "params": {"msg": "hello"}})

        assert result["id"] == 1
        assert result["result"] == {"pong": True, "echo": "hello"}
        assert result["error"] is None

    def test_unknown_method_returns_not_found(self):
        """Routing to an unregistered method returns an error."""
        router = IpcRouter()
        result = router.handle({"id": 42, "method": "nope", "params": {}})

        assert result["id"] == 42
        assert result["result"] is None
        assert result["error"]["code"] == ERR_NOT_FOUND
        assert "Unknown method" in result["error"]["message"]

    def test_unknown_method_with_no_id(self):
        """Unknown method with missing id should still return error."""
        router = IpcRouter()
        result = router.handle({"method": "nope"})

        assert result["id"] is None
        assert result["error"]["code"] == ERR_NOT_FOUND

    def test_handler_exception_returns_execution_error(self):
        """A handler that raises should return ERR_EXECUTION."""
        router = IpcRouter()

        def failing(params: dict, shared: dict) -> dict:
            raise RuntimeError("something broke")

        router.register("fail", failing)
        result = router.handle({"id": 1, "method": "fail", "params": {}})

        assert result["id"] == 1
        assert result["result"] is None
        assert result["error"]["code"] == ERR_EXECUTION
        assert "something broke" in result["error"]["message"]

    def test_shared_state_passed_to_handler(self):
        """Shared state set via set_shared should be available to handlers."""
        router = IpcRouter()

        def check_shared(params: dict, shared: dict) -> dict:
            return {"db": shared.get("db"), "val": shared.get("val", 0)}

        router.register("check", check_shared)
        router.set_shared("db", "sqlite:///test.db")
        router.set_shared("val", 42)

        result = router.handle({"id": 1, "method": "check", "params": {}})

        assert result["result"]["db"] == "sqlite:///test.db"
        assert result["result"]["val"] == 42

    def test_register_overwrites_existing_handler(self):
        """Registering the same method twice overwrites the first handler."""
        router = IpcRouter()

        def first(params, shared):
            return {"from": "first"}

        def second(params, shared):
            return {"from": "second"}

        router.register("dup", first)
        router.register("dup", second)

        result = router.handle({"method": "dup", "params": {}})
        assert result["result"]["from"] == "second"

    def test_empty_params_defaults_to_empty_dict(self):
        """Missing params should default to an empty dict."""
        router = IpcRouter()

        def handler(params, shared):
            return {"params_type": type(params).__name__}

        router.register("test", handler)
        result = router.handle({"id": 1, "method": "test"})

        assert result["result"]["params_type"] == "dict"

    def test_default_error_code_is_execution(self):
        """_error_response without a code should default to ERR_EXECUTION."""
        resp = _error_response(1, "something failed")
        assert resp["error"]["code"] == ERR_EXECUTION

    def test_error_response_with_custom_code(self):
        """_error_response should accept a custom error code."""
        resp = _error_response(1, "validation failed", ERR_VALIDATION)
        assert resp["error"]["code"] == ERR_VALIDATION
        assert resp["error"]["message"] == "validation failed"

    def test_success_response_shape(self):
        """_success_response should return JSON-RPC 2.0 shape."""
        resp = _success_response(1, {"done": True})
        assert resp["id"] == 1
        assert resp["result"] == {"done": True}
        assert resp["error"] is None

    def test_success_response_with_none_id(self):
        """Success response with None id should be valid."""
        resp = _success_response(None, "ok")
        assert resp["id"] is None
        assert resp["result"] == "ok"
