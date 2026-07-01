from tradebot.arena.loader import discover

ALGO = (
    "from tradebot.arena import register, Algo, Action\n"
    "@register(name={name!r}, author='t')\n"
    "class {cls}(Algo):\n"
    "    def on_bar(self, bar, ctx):\n"
    "        return Action.flat()\n"
)


def test_discover_finds_decorated_and_skips_broken(tmp_path):
    (tmp_path / "a.py").write_text(ALGO.format(name="x", cls="X"))
    (tmp_path / "broken.py").write_text("import a_module_that_does_not_exist_zzz\n")

    contestants, errors = discover([str(tmp_path)])

    assert [c.name for c in contestants] == ["x"]
    assert contestants[0].kind == "event"
    assert contestants[0].source.endswith("a.py")
    assert any("broken.py" in e.path for e in errors)


def test_duplicate_names_are_reported_and_dropped(tmp_path):
    (tmp_path / "one.py").write_text(ALGO.format(name="dup", cls="A"))
    (tmp_path / "two.py").write_text(ALGO.format(name="dup", cls="B"))

    contestants, errors = discover([str(tmp_path)])

    assert [c.name for c in contestants] == ["dup"]   # first wins
    assert any("duplicate" in e.message for e in errors)


def test_factory_makes_fresh_instances(tmp_path):
    (tmp_path / "a.py").write_text(ALGO.format(name="x", cls="X"))
    contestants, _ = discover([str(tmp_path)])
    c = contestants[0]
    assert c.make() is not c.make()      # new instance each round


def test_private_and_dunder_files_are_skipped(tmp_path):
    (tmp_path / "_helper.py").write_text("x = 1\n")
    (tmp_path / "__init__.py").write_text("")
    (tmp_path / "real.py").write_text(ALGO.format(name="r", cls="R"))
    contestants, errors = discover([str(tmp_path)])
    assert [c.name for c in contestants] == ["r"]
    assert errors == []
