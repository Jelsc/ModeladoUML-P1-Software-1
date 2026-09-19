import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

const root = new URL("../src/", import.meta.url);
const files = [
  "components/index.jsx",
  "components/layout/Sidebar.jsx",
  "components/layout/TopBar.jsx",
  "components/auth/Login.jsx",
  "components/auth/InvitationModal.jsx",
  "features/assistant/AssistantLauncher.jsx",
  "features/assistant/AssistantPanel.jsx",
  "features/diagram/inspector/ClassInspector.jsx",
  "features/diagram/inspector/RelationInspector.jsx",
  "features/relations/RelationModal.jsx",
  "features/canvas/ClassCard.jsx",
  "features/canvas/CollaboratorCursor.jsx",
  "features/canvas/RelationLayer.jsx",
  "features/canvas/ZoomControls.jsx",
  "features/members/MembersPanel.jsx",
  "features/deployment/DeploymentPanel.jsx",
  "features/sql/SqlEditor.jsx",
  "pages/index.jsx",
  "pages/board-canvas.jsx",
  "pages/DashboardPage.jsx",
  "pages/UserManagementPage.jsx",
  "features/canvas/useCanvasCollaboration.js",
  "features/canvas/useCanvasGestures.js",
  "lib/diagram-normalizers.js",
];
for (const file of files) assert.ok(existsSync(new URL(file, root)), `${file} is missing`);

const board = readFileSync(new URL("pages/board-canvas.jsx", root), "utf8");
const dashboard = readFileSync(new URL("pages/DashboardPage.jsx", root), "utf8");
const users = readFileSync(new URL("pages/UserManagementPage.jsx", root), "utf8");
const components = readFileSync(new URL("components/index.jsx", root), "utf8");
const assistant = readFileSync(new URL("features/assistant/AssistantLauncher.jsx", root), "utf8");
assert.match(board, /from "\.\.\/components\/index\.jsx"/);
assert.ok(components.split("\n").length <= 100, "components/index.jsx should remain a thin barrel");
assert.match(components, /features\/assistant\/AssistantLauncher/);
assert.match(components, /features\/diagram\/inspector\/ClassInspector/);
assert.match(components, /features\/relations\/RelationModal/);
assert.match(components, /features\/(members|deployment|sql)\//);
for (const exportName of [
  "Sidebar", "TopBar", "Login", "InvitationModal", "AssistantLauncher", "MicrophoneIcon",
  "AssistantPanel", "AssistantPreview", "MembersPanel", "DeploymentPanel", "SqlEditor",
  "ClassInspector", "Inspector", "RelationInspector", "RelationModal",
]) assert.match(components, new RegExp(`\\b${exportName}\\b`), `${exportName} export is missing`);
assert.doesNotMatch(components, /function\s+\w+|const\s+\w+\s*=\s*\(/);
assert.match(assistant, /function MicrophoneIcon/);
assert.match(assistant, /viewBox="0 0 24 24"/);
assert.doesNotMatch(board, /LegacyRelation(?:Modal|Layer)/);
assert.doesNotMatch(components, /LegacyRelation(?:Modal|Layer)/);
assert.match(board, /useCanvasCollaboration/);
assert.match(board, /useCanvasGestures/);
assert.ok(board.split("\n").length < 400, "BoardCanvas should remain an orchestration module");
assert.match(dashboard, /DIAGRAMS_REFRESH_EVENT/);
assert.match(users, /\/admin\/users/);
assert.doesNotMatch(board, /function (Dashboard|UserManagement)/);
assert.match(board, /features\/canvas\/RelationLayer\.jsx/);
assert.doesNotMatch(readFileSync(new URL("features/canvas/RelationLayer.jsx", root), "utf8"), /components(?:\.jsx|\/index\.jsx)/);
console.log("Frontend module structure checks passed.");
