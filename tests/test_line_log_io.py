"""webui/line_log_io.py's append_line() - true single-line appends with
amortized (not per-call) compaction."""

from webui import line_log_io


def _format(entry):
    return str(entry["n"])


def _parse(line):
    return {"n": int(line)}


def test_append_then_read_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(line_log_io, "_counts", {})
    path = tmp_path / "log.txt"
    line_log_io.append_line(path, {"n": 1}, _format, _parse, max_entries=100)
    line_log_io.append_line(path, {"n": 2}, _format, _parse, max_entries=100)
    assert line_log_io.read_lines(path, _parse) == [{"n": 1}, {"n": 2}]


def test_stays_uncompacted_within_the_slack_window(tmp_path, monkeypatch):
    monkeypatch.setattr(line_log_io, "_counts", {})
    monkeypatch.setattr(line_log_io, "_COMPACT_SLACK", 5)
    path = tmp_path / "log.txt"
    for n in range(7):  # over max_entries=3, but within the slack of 5
        line_log_io.append_line(path, {"n": n}, _format, _parse, max_entries=3)
    assert line_log_io.read_lines(path, _parse) == [{"n": n} for n in range(7)]


def test_compacts_once_past_max_entries_plus_slack(tmp_path, monkeypatch):
    monkeypatch.setattr(line_log_io, "_counts", {})
    monkeypatch.setattr(line_log_io, "_COMPACT_SLACK", 5)
    path = tmp_path / "log.txt"
    for n in range(9):  # 3 + 5 = 8 is the trigger point; the 9th tips it over
        line_log_io.append_line(path, {"n": n}, _format, _parse, max_entries=3)
    entries = line_log_io.read_lines(path, _parse)
    assert entries == [{"n": 6}, {"n": 7}, {"n": 8}]  # newest 3 kept


def test_lazily_counts_an_existing_file_it_didnt_create(tmp_path, monkeypatch):
    """A file already on disk (e.g. from a previous process) with no cached
    count yet must still be counted correctly, not treated as empty."""
    monkeypatch.setattr(line_log_io, "_counts", {})
    monkeypatch.setattr(line_log_io, "_COMPACT_SLACK", 0)
    path = tmp_path / "log.txt"
    path.write_text("0\n1\n2\n")

    line_log_io.append_line(path, {"n": 3}, _format, _parse, max_entries=3)

    assert line_log_io.read_lines(path, _parse) == [{"n": 1}, {"n": 2}, {"n": 3}]
