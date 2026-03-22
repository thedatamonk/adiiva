# tests/test_pipeline_transport.py
def test_create_pipeline_uses_websocket_server_transport():
    """Verify pipeline uses WebsocketServerTransport, not FastAPIWebsocketTransport."""
    from src.pipeline import create_pipeline
    import inspect
    source = inspect.getsource(create_pipeline)
    assert "WebsocketServerTransport" in source
    assert "FastAPIWebsocketTransport" not in source
