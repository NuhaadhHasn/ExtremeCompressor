from excmp.tools import find_tools, ToolInfo


def test_find_tools_returns_all_keys():
    tools = find_tools()
    assert set(tools) >= {"7z", "precomp", "srep", "zpaqfranz", "ffmpeg", "ffprobe", "zstd"}


def test_7z_found_on_dev_machine():
    tools = find_tools()
    assert tools["7z"] is not None and tools["7z"].path.lower().endswith("7z.exe")


def test_toolinfo_fields():
    tools = find_tools()
    t = tools["7z"]
    assert isinstance(t, ToolInfo)
    assert t.name == "7z"
