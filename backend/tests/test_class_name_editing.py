from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_class_name_editor_keeps_a_local_draft_and_saves_on_commit_actions():
    source = (ROOT / "frontend" / "src" / "features" / "diagram" / "inspector" / "ClassInspector.jsx").read_text(encoding="utf-8")

    assert "const [nameDraft, setNameDraft] = useState" in source
    assert "onChange={(e) => setNameDraft(e.target.value)}" in source
    assert "onBlur={saveName}" in source
    assert 'onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}' in source
    assert "onChange={e => onPatch({ name: e.target.value })}" not in source


def test_detail_editor_uses_local_drafts_and_shared_type_selects():
    source = (ROOT / "frontend" / "src" / "features" / "diagram" / "inspector" / "ClassInspector.jsx").read_text(encoding="utf-8")

    assert "const [itemDrafts, setItemDrafts] = useState({})" in source
    assert 'onChange={(e) => update(kind, item, "name", e.target.value)}' in source
    assert "onBlur={() => saveItem(kind, item)}" in source
    assert 'onChange={(e) => onItemPatch("attributes"' not in source
    assert 'onChange={(e) => onItemPatch("methods"' not in source
    assert 'ATTRIBUTE_TYPES, METHOD_TYPES' in source
    assert "METHOD_TYPES = [...ATTRIBUTE_TYPES" not in source
    assert '<option value="Custom">Personalizado</option>' in source


def test_class_patch_contract_accepts_name_and_numeric_positions():
    import sys

    sys.path.insert(0, str(ROOT / "backend"))
    from app.main import ClassPatch

    assert ClassPatch(name="Renamed").model_dump(exclude_unset=True) == {"name": "Renamed"}
    assert ClassPatch(x=120, y=240).model_dump(exclude_unset=True) == {"x": 120, "y": 240}
    for invalid in ({"name": ""}, {"name": "   "}, {"name": None}, {"x": -1}, {"y": -1}, {"x": 1.5}, {"x": None}):
        try:
            ClassPatch(**invalid)
        except Exception:
            continue
        raise AssertionError(f"invalid ClassPatch accepted: {invalid}")
