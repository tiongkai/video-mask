"""Tests for annotate/process refactors and gui_helpers utilities."""


def test_annotate_main_accepts_args():
    """annotate.main() must accept an optional args parameter."""
    import inspect
    import annotate
    sig = inspect.signature(annotate.main)
    params = sig.parameters
    assert "args" in params, "annotate.main() must have an 'args' parameter"
    assert params["args"].default is None, "args must default to None"


def test_process_main_accepts_args():
    """process.main() must accept an optional args parameter."""
    import inspect
    # Import carefully — process.py calls _find_ffmpeg() at module level
    # which calls sys.exit(1) if ffmpeg is not found.
    try:
        import process as process_mod
    except SystemExit:
        import pytest
        pytest.skip("ffmpeg not available in this environment")
    sig = inspect.signature(process_mod.main)
    params = sig.parameters
    assert "args" in params, "process.main() must have an 'args' parameter"
    assert params["args"].default is None, "args must default to None"


def test_queue_writer_puts_to_queue():
    """QueueWriter.write() should put text into the queue."""
    import queue as q_mod
    import gui_helpers

    q = q_mod.Queue()
    writer = gui_helpers.QueueWriter(q)
    writer.write("hello world")
    assert not q.empty()
    assert q.get_nowait() == "hello world"


def test_queue_writer_flush_is_noop():
    """QueueWriter.flush() must exist and not raise."""
    import queue as q_mod
    import gui_helpers

    q = q_mod.Queue()
    writer = gui_helpers.QueueWriter(q)
    writer.flush()  # must not raise


def test_queue_writer_write_multiple():
    """Multiple writes each appear as separate queue items."""
    import queue as q_mod
    import gui_helpers

    q = q_mod.Queue()
    writer = gui_helpers.QueueWriter(q)
    writer.write("line1\n")
    writer.write("line2\n")
    assert q.get_nowait() == "line1\n"
    assert q.get_nowait() == "line2\n"
    assert q.empty()


def test_queue_writer_write_returns_length():
    """QueueWriter.write() returns the number of characters written (sys.stdout protocol)."""
    import queue as q_mod
    import gui_helpers

    q = q_mod.Queue()
    writer = gui_helpers.QueueWriter(q)
    result = writer.write("hello")
    assert result == 5
