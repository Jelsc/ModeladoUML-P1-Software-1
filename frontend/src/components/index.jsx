// Stable component exports for existing consumers. Implementations live in feature modules.
export { Sidebar } from "./layout/Sidebar.jsx";
export { TopBar } from "./layout/TopBar.jsx";
export { Login } from "./auth/Login.jsx";
export { InvitationModal } from "./auth/InvitationModal.jsx";
export { AssistantLauncher, MicrophoneIcon } from "../features/assistant/AssistantLauncher.jsx";
export { AssistantPanel, AssistantPreview } from "../features/assistant/AssistantPanel.jsx";
export { MembersPanel } from "../features/members/MembersPanel.jsx";
export { DeploymentPanel } from "../features/deployment/DeploymentPanel.jsx";
export { SqlEditor } from "../features/sql/SqlEditor.jsx";
export { ClassInspector } from "../features/diagram/inspector/ClassInspector.jsx";
export { ClassInspector as Inspector } from "../features/diagram/inspector/ClassInspector.jsx";
export { RelationInspector } from "../features/diagram/inspector/RelationInspector.jsx";
export { RelationModal } from "../features/relations/RelationModal.jsx";
export * from "../features/diagram/inspector/inspector.constants.js";
