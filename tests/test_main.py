import os

import main
from cinecompass import config


def test_cmd_profile_backs_up_previous_file(tmp_path, monkeypatch):
    profile_path = tmp_path / "profile.md"
    profile_path.write_text("старая версия\n", encoding="utf-8")
    os.utime(profile_path, (1_700_000_000, 1_700_000_000))

    monkeypatch.setattr(config, "PROFILE_FILE", profile_path)
    monkeypatch.setattr(main.library, "load_library", lambda: [])
    monkeypatch.setattr(main.semantic, "load_cache", lambda: {})
    monkeypatch.setattr(main.taste, "build_profile", lambda _items, _cache: {})
    monkeypatch.setattr(main.markdown, "taste_profile_markdown", lambda _p: "context")
    monkeypatch.setattr(main.prompts, "profile_prompt", lambda _ctx: "prompt")
    monkeypatch.setattr(main.llm, "generate", lambda _prompt, op="profile": "новая версия")

    main.cmd_profile(None)

    assert profile_path.read_text(encoding="utf-8") == "новая версия\n"
    backups = list(tmp_path.glob("profile_*.md"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "старая версия\n"
