"""No-hardware lifecycle contracts for the read-only MJPEG bridge.

The bridge intentionally keeps its latest-frame and replay state in process
memory.  These tests make that bounded policy explicit without requiring ROS
hardware or a running ROS installation in the AI service test environment.
"""

from __future__ import annotations

import importlib.util
import socket
import sys
import threading
import time
import types
from pathlib import Path

from app.security import _ReplayCache

BRIDGE_PATH = (
    Path(__file__).resolve().parents[1]
    / "ros2"
    / "smartfactory_perception_ros"
    / "smartfactory_perception_ros"
    / "vision_overlay_stream_bridge.py"
)


def _load_bridge_module(monkeypatch):
    """Load the ROS bridge with minimal test-only ROS import stubs."""

    package_name = "_test_smartfactory_perception_ros"
    package = types.ModuleType(package_name)
    package.__path__ = [str(BRIDGE_PATH.parent)]
    rclpy = types.ModuleType("rclpy")
    rclpy_executors = types.ModuleType("rclpy.executors")
    rclpy_node = types.ModuleType("rclpy.node")
    sensor_msgs = types.ModuleType("sensor_msgs")
    sensor_msgs_msg = types.ModuleType("sensor_msgs.msg")

    class Node:  # pragma: no cover - minimal ROS-free bridge stand-in
        def __init__(self, *args, **kwargs) -> None:
            self._parameters = {}

        def declare_parameter(self, name, default) -> None:
            self._parameters.setdefault(name, default)

        def get_parameter(self, name):
            return types.SimpleNamespace(value=self._parameters[name])

        def create_subscription(self, *args, **kwargs) -> None:
            return None

        def get_logger(self):
            return types.SimpleNamespace(debug=lambda *args: None, info=lambda *args: None)

        def destroy_node(self) -> bool:
            return True

    class CompressedImage:  # pragma: no cover - import-only stand-in
        pass

    rclpy_executors.ExternalShutdownException = RuntimeError
    rclpy_node.Node = Node
    sensor_msgs_msg.CompressedImage = CompressedImage
    monkeypatch.setitem(sys.modules, package_name, package)
    monkeypatch.setitem(sys.modules, "rclpy", rclpy)
    monkeypatch.setitem(sys.modules, "rclpy.executors", rclpy_executors)
    monkeypatch.setitem(sys.modules, "rclpy.node", rclpy_node)
    monkeypatch.setitem(sys.modules, "sensor_msgs", sensor_msgs)
    monkeypatch.setitem(sys.modules, "sensor_msgs.msg", sensor_msgs_msg)

    qos_profiles = types.ModuleType(f"{package_name}.qos_profiles")
    qos_profiles.build_bounded_image_qos_profile = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, f"{package_name}.qos_profiles", qos_profiles)

    module_name = f"{package_name}.vision_overlay_stream_bridge"
    spec = importlib.util.spec_from_file_location(module_name, BRIDGE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


def _frame_message(payload: bytes) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        data=payload,
        format="jpeg",
        header=types.SimpleNamespace(
            stamp=types.SimpleNamespace(sec=0, nanosec=0),
            frame_id="test_camera",
        ),
    )


def _start_stream_server(bridge):
    store = bridge.LatestCompressedFrameStore()
    node = types.SimpleNamespace(
        shutdown_event=threading.Event(),
        frame_store=store,
        sources=["tb3_1_picam"],
        default_source="tb3_1_picam",
        max_fps=30.0,
        get_logger=lambda: types.SimpleNamespace(debug=lambda *args: None),
        status_payload=lambda: {"read_only": True},
    )
    server = bridge._ThreadingHTTPServer(("127.0.0.1", 0), bridge.make_handler(node))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return node, server, thread


def _stop_stream_server(node, server, thread):
    node.shutdown_event.set()
    server.shutdown()
    server.server_close()
    thread.join(timeout=1.0)


def _open_stream(port: int) -> socket.socket:
    client = socket.create_connection(("127.0.0.1", port), timeout=1.0)
    client.sendall(
        b"GET /stream/tb3_1_picam.mjpeg?max_fps=30 HTTP/1.1\r\n"
        b"Host: localhost\r\nConnection: keep-alive\r\n\r\n"
    )
    client.settimeout(1.0)
    assert b"200 OK" in client.recv(1024)
    return client


def test_disconnected_mjpeg_client_stops_consuming_without_losing_newest_frame(monkeypatch):
    bridge = _load_bridge_module(monkeypatch)
    node, server, thread = _start_stream_server(bridge)
    client = _open_stream(server.server_address[1])
    try:
        node.frame_store.put("tb3_1_picam", _frame_message(b"first-frame"))
        assert b"first-frame" in client.recv(4096)

        client.shutdown(socket.SHUT_RDWR)
        client.close()
        for sequence_id in range(2, 8):
            node.frame_store.put(
                "tb3_1_picam", _frame_message(f"frame-{sequence_id}".encode())
            )

        deadline = time.monotonic() + 1.0
        while any(worker.is_alive() for worker in server._threads):
            if time.monotonic() >= deadline:
                raise AssertionError("disconnected MJPEG handler did not exit")
            time.sleep(0.01)

        latest = node.frame_store.latest("tb3_1_picam")
        assert latest is not None
        assert latest.sequence_id == 7
        assert latest.data == b"frame-7"
    finally:
        _stop_stream_server(node, server, thread)


def test_slow_mjpeg_client_does_not_block_latest_frame_writer(monkeypatch):
    bridge = _load_bridge_module(monkeypatch)
    node, server, thread = _start_stream_server(bridge)
    client = _open_stream(server.server_address[1])
    writer_finished = threading.Event()

    def publish_frames() -> None:
        for sequence_id in range(1, 101):
            node.frame_store.put("tb3_1_picam", _frame_message(bytes([sequence_id]) * 131_072))
        writer_finished.set()

    producer = threading.Thread(target=publish_frames)
    try:
        producer.start()
        assert writer_finished.wait(timeout=1.0), "slow stream client blocked frame writer"
        latest = node.frame_store.latest("tb3_1_picam")
        assert latest is not None
        assert latest.sequence_id == 100
        assert latest.data == bytes([100]) * 131_072
    finally:
        client.close()
        producer.join(timeout=1.0)
        _stop_stream_server(node, server, thread)


def test_mjpeg_source_transitions_to_stale_after_latest_frame_ages_out(monkeypatch):
    bridge = _load_bridge_module(monkeypatch)
    node = bridge.VisionOverlayStreamBridge(start_http_server=False)
    try:
        node._on_overlay_image("tb3_1_picam", _frame_message(b"fresh-frame"))
        assert node.status_payload()["sources"][0]["stale"] is False

        frame = node.frame_store.latest("tb3_1_picam")
        assert frame is not None
        monkeypatch.setattr(
            bridge.time,
            "monotonic",
            lambda: frame.received_monotonic_s + node.stale_after_sec + 0.001,
        )

        assert node.status_payload()["sources"][0]["stale"] is True
    finally:
        node.destroy_node()


def test_replay_cache_is_process_local_and_restarts_do_not_preserve_claims():
    """Replay protection is bounded to one AI process; durable replay is not promised."""

    first_process_cache = _ReplayCache()
    assert first_process_cache.claim("nonce-123", ttl_sec=60.0) is True
    assert first_process_cache.claim("nonce-123", ttl_sec=60.0) is False

    restarted_process_cache = _ReplayCache()
    assert restarted_process_cache.claim("nonce-123", ttl_sec=60.0) is True
