from pathlib import Path
import re


ROOT = Path(__file__).parents[2]
FRONTEND_SRC = ROOT / "frontend" / "src"
COMPONENTS = "\n".join(path.read_text(encoding="utf-8") for path in FRONTEND_SRC.rglob("*.jsx"))
PAGES = COMPONENTS
API = (ROOT / "frontend" / "src" / "api.js").read_text(encoding="utf-8")
MAIN = (ROOT / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")
RELATION_LAYER = (ROOT / "frontend" / "src" / "features" / "canvas" / "RelationLayer.jsx").read_text(encoding="utf-8")
STYLES = (ROOT / "frontend" / "src" / "style.css").read_text(encoding="utf-8")
MAIN = (ROOT / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")
BOARD_CANVAS = PAGES.split("function BoardCanvas(", 1)[1].split(
    "export function BoardEditor", 1
)[0]


def test_relation_layer_has_independent_hit_targets_and_hover_context():
    assert "hoveredId" in RELATION_LAYER
    assert "relation-hit" in RELATION_LAYER
    assert "Q ${cx} ${cy}" in RELATION_LAYER
    assert "endpoint_info" in RELATION_LAYER
    assert "foreignObject" not in RELATION_LAYER
    assert "multiplicity" in RELATION_LAYER
    assert "z-index: 3" in STYLES
    assert "onHover({ relationId: relation.id, source, target })" in RELATION_LAYER


def test_inspector_uses_current_diagram_and_awaits_refreshes():
    assert "selectedClassId" in PAGES
    assert "renderedDiagram.classes.find" in PAGES and "selectedClassId" in PAGES
    assert "setSelectedClassId(null)" in PAGES
    assert "await mutate(() => request" in PAGES
    assert "ws.onmessage" in PAGES
    assert "await refresh()" in PAGES


def test_attribute_and_method_catalogs_are_explicit_and_labeled():
    assert "export const ATTRIBUTE_TYPES = [" in COMPONENTS
    assert "export const METHOD_TYPES = [" in COMPONENTS
    assert "aria-label={kind === 'attributes' ? 'Tipo de atributo' : 'Tipo de retorno'}" in COMPONENTS


def test_class_patch_calls_use_uuid_ids_and_numeric_positions():
    assert "validClassId(selectedClassId)" in PAGES
    assert "x: Number(position.x), y: Number(position.y)" in PAGES
    assert "Math.round(Number(safePatch.x))" in PAGES


def test_class_card_handles_partial_relation_hover_and_detail_payloads():
    assert "hoverContext?.source?.classId" in PAGES
    assert "endpoint?.classId" in PAGES
    assert "const diagramData = value =>" in PAGES
    assert "attributes: list(item.attributes).map" in PAGES
    assert "methods: list(item.methods).map" in PAGES


def test_auth_expiry_clears_token_and_handles_websocket_policy_close():
    assert "response.status === 401" in API
    assert "localStorage.removeItem('token')" in API
    assert "AUTH_EXPIRED_EVENT" in MAIN
    assert "event.code === 1008" in PAGES
    assert "uml:auth-expired" in API


def test_relation_layer_uses_semantic_markers_and_centered_labels():
    assert "uml-composition-filled" in RELATION_LAYER
    assert "uml-aggregation-hollow" in RELATION_LAYER
    assert "uml-inheritance-hollow" in RELATION_LAYER
    assert "uml-dependency-open" in RELATION_LAYER
    assert "markerStart={markerFor(relation, 'source')}" in RELATION_LAYER
    assert "markerEnd={markerFor(relation, 'target')}" in RELATION_LAYER
    assert "labelX = labelPoint.x + nx * 12" in RELATION_LAYER


def test_mutations_are_serialized_and_relation_create_sends_enum_values():
    assert "const mutationQueue = useRef(Promise.resolve())" in PAGES
    assert "pendingMutations.current" in PAGES
    assert "option key={x} value={x}" in COMPONENTS


def test_relation_multiplicity_controls_keep_labels_separate_from_api_values():
    assert 'MULTIPLICITY_OPTIONS = ["1", "0..1", "*", "1..*", "0..*"]' in COMPONENTS
    assert "value={CUSTOM_MULTIPLICITY}" in COMPONENTS
    assert "Personalizada" in COMPONENTS
    assert "source_multiplicity: form.source_multiplicity || null" in COMPONENTS
    assert "target_multiplicity: form.target_multiplicity || null" in COMPONENTS
    assert "onPatch({ type: e.target.value })" in COMPONENTS
    assert "RELATION_LABELS[x]" in COMPONENTS


def test_relation_inspector_shows_both_endpoint_details_and_touch_gestures():
    assert "diagram={renderedDiagram}" in PAGES
    assert "data_type" in COMPONENTS and "return_type" in COMPONENTS
    assert "activePointers" in PAGES
    assert "gesture.current" in PAGES
    assert "onLostPointerCapture" in PAGES


def test_hash_routes_keep_projects_and_admin_user_management_separate():
    assert "#/dashboard" in MAIN
    assert "#/gestion-usuarios" in MAIN
    assert "UserManagementPage" in MAIN
    assert "currentUser.role === 'admin'" in MAIN
    assert "<UserManagement onLogout={onLogout}" not in PAGES
    assert "user-management" in PAGES


def test_authenticated_invitation_socket_refreshes_dashboard_and_uses_one_modal():
    assert "/api/notifications/ws?token=" in MAIN
    assert "board.invitation" in MAIN
    assert "DIAGRAMS_REFRESH_EVENT" in MAIN and "DIAGRAMS_REFRESH_EVENT" in PAGES
    assert "seenInvitations" in MAIN
    assert "<InvitationModal" in MAIN
    assert "Abrir pizarra" in COMPONENTS
    assert "#/board/${invitation.diagramId}" in MAIN


def test_sql_editor_has_synchronized_line_number_gutter():
    assert "useRef" in COMPONENTS
    assert "sql-gutter" in COMPONENTS
    assert "sql.split('\\n').length" in COMPONENTS
    assert "onScroll={syncGutter}" in COMPONENTS


def test_sql_workspace_is_a_route_without_sql_modal_usage_and_keeps_permissions():
    assert "#/board/${sqlId}" in MAIN
    assert "SqlWorkspace" in MAIN and "SqlWorkspace" in PAGES
    assert 'className="sql-workspace"' in COMPONENTS
    assert "sql-modal" not in COMPONENTS
    assert 'setPermission("viewer")' in COMPONENTS
    assert 'permission === "viewer"' in COMPONENTS


def test_sql_editor_is_a_board_drawer_with_partial_and_expanded_states():
    sql_editor = COMPONENTS.split("export function SqlEditor(", 1)[1].split(
        "function InspectorClose(", 1
    )[0]
    assert "setSqlOpen(true)" in PAGES
    assert "sql-drawer-${drawerMode}" in COMPONENTS
    assert 'drawerMode === "partial"' in COMPONENTS
    assert 'drawerMode === "expanded"' in COMPONENTS
    assert "onClose" not in sql_editor
    assert 'aria-label="Cerrar editor SQL"' not in sql_editor
    assert '× Cerrar' not in sql_editor
    assert 'onApplied={applyDiagram}' in PAGES


def test_sql_editor_drawer_is_a_right_side_panel_without_document_overflow():
    assert "right: 0" in STYLES
    assert "width: min(55vw, 900px)" in STYLES
    assert "transform: translateX" in STYLES
    assert "border-left: 1px solid var(--line-strong)" in STYLES
    assert "overflow-x: hidden" in STYLES
    assert ".sql-workspace { height: calc(100% - 52px); min-width: 0; overflow: auto;" in STYLES


def test_sql_editor_has_no_collapsed_tab_state():
    assert 'className="sql-drawer-tab"' not in COMPONENTS
    assert ".sql-drawer-collapsed" not in STYLES


def test_sql_route_wires_initial_drawer_state_without_duplicate_board_mounts():
    board_signature = PAGES.split("function BoardCanvas(", 1)[1].split(") {", 1)[0]
    assert "initialSqlOpen = false" in board_signature
    assert "[sqlOpen, setSqlOpen] = useState(initialSqlOpen)" in PAGES
    assert "const sqlId = route.match" in MAIN
    assert "/sql$/" in MAIN
    assert "<SqlWorkspace" in MAIN
    assert "initialSqlOpen />" in PAGES
    assert "return <BoardCanvas {...props} />;" in PAGES


def test_sql_button_and_legacy_route_open_partial_without_duplicate_editors():
    assert 'setSqlDrawerMode("partial")' in PAGES
    assert "if (sqlOpen)" in PAGES
    assert "setSqlOpen(false)" in PAGES
    assert 'drawerMode={sqlDrawerMode}' in PAGES
    assert 'setSqlDrawerMode("collapsed")' not in PAGES
    assert "onDrawerModeChange={setSqlDrawerMode}" in PAGES


def test_sql_top_bar_button_toggles_panel_without_collapsed_state():
    assert "sqlOpen = false" in COMPONENTS
    assert 'aria-pressed={sqlOpen}' in COMPONENTS
    assert '{sqlOpen ? "Ocultar SQL" : "SQL Editor"}' in COMPONENTS
    assert 'onClick={onSql}' in COMPONENTS
    assert 'setSqlOpen(true)' in PAGES


def test_closed_inspector_and_mobile_canvas_do_not_expand_document_layout():
    assert "{inspectorOpen && (selectedRelation ?" in PAGES
    assert "min-width: 600px" not in STYLES
    assert "overflow-x: hidden" in STYLES


def test_inspectors_can_close_and_selection_reopens_them():
    assert "InspectorClose" in COMPONENTS
    assert "onClose" in COMPONENTS
    assert "Cerrar" in COMPONENTS
    assert "setInspectorOpen(true)" in PAGES
    assert "inspector-open" in PAGES

def test_collaboration_cursor_and_live_class_contract():
    assert "export const canvasPoint" in PAGES
    assert "canvas.scrollLeft" in PAGES and "canvas.scrollTop" in PAGES
    assert "sendEphemeral('cursor.move'" in PAGES
    assert "sendEphemeral('class.move'" in PAGES
    assert "String(event.user_id) === String(currentUser.id)" in PAGES
    assert "presence.leave" in PAGES
    assert "collaborator-cursor" in PAGES
    assert "requestAnimationFrame" in PAGES
    assert "visualFrame.current" in PAGES
    assert "setVisualPositions({ ...livePositions.current })" in PAGES
    assert "transform: `translate3d" in PAGES
    assert "setTimeout(() => { delete remoteCursorPositions.current" in PAGES


def test_collaboration_motion_is_frame_bounded_and_pointerup_only_persists():
    assert "setDiagram(current => ({ ...current, classes:" not in PAGES
    assert "setDiagram(current => current &&" not in PAGES
    assert "const EPHEMERAL_EVENT_INTERVAL_MS = 16" in PAGES
    assert "}, EPHEMERAL_EVENT_INTERVAL_MS);" in PAGES
    drag_body = PAGES.split("function drag(e, item)", 1)[1].split("const hoverContext", 1)[0]
    assert "request(`/classes/${item.id}`, json('PATCH'" in drag_body
    move_body = drag_body.split("const move =", 1)[1].split("const up =", 1)[0]
    assert "PATCH" not in move_body
    assert "PATCH" in drag_body.split("const up =", 1)[1]


def test_board_canvas_calls_all_hooks_before_loading_return():
    loading_return = BOARD_CANVAS.index('if (!diagram)')
    hooks_after_loading = [
        match.group(0)
        for match in re.finditer(
            r"\buse(?:State|Effect|Ref|Memo|Callback|LayoutEffect|Reducer|Context)\s*\(",
            BOARD_CANVAS[loading_return:],
        )
    ]
    assert not hooks_after_loading, (
        "BoardCanvas must not call hooks after its conditional loading return: "
        + ", ".join(hooks_after_loading)
    )
