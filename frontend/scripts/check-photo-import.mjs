import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const modal = readFileSync(new URL("../src/features/photo-import/ImportFromPhotoModal.jsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/features/photo-import/vision.js", import.meta.url), "utf8");
const dashboard = readFileSync(new URL("../src/pages/DashboardPage.jsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/style.css", import.meta.url), "utf8");
const chat = readFileSync(new URL("../src/features/chat/ChatPanel.jsx", import.meta.url), "utf8");
const board = readFileSync(new URL("../src/pages/board-canvas.jsx", import.meta.url), "utf8");
const nginxProd = readFileSync(new URL("../../infra/nginx/templates/default.prod.conf.template", import.meta.url), "utf8");
const nginxBootstrap = readFileSync(new URL("../../infra/nginx/templates/default.prod-bootstrap.conf.template", import.meta.url), "utf8");

assert.match(dashboard, /Generar desde foto/);
assert.match(modal, /PHOTO_IMPORT_STATES/);
assert.match(modal, /PICK/);
assert.match(modal, /REVIEW/);
assert.match(modal, /APPLYING/);
assert.match(modal, /role="dialog" aria-modal="true"/);
assert.match(modal, /accept="image\/jpeg,image\/png,image\/webp,image\/heic,image\/heif"/);
assert.match(modal, /URL\.createObjectURL/);
assert.match(modal, /URL\.revokeObjectURL/);
assert.match(modal, /type="checkbox"/);
assert.match(modal, /Crear diagrama revisado/);
assert.match(modal, /diagramId \? "Revisá la propuesta/);
assert.match(modal, /!diagramId && <label>Nombre del proyecto/);
assert.match(modal, /Agregar al diagrama actual/);
assert.match(api, /FormData/);
assert.match(api, /\/vision\/detect/);
assert.match(api, /\/vision\/apply/);
assert.match(api, /600000/);
for (const config of [nginxProd, nginxBootstrap]) {
  assert.equal((config.match(/proxy_connect_timeout 30s;/g) || []).length, 2);
  assert.equal((config.match(/proxy_send_timeout 600s;/g) || []).length, 2);
  assert.equal((config.match(/proxy_read_timeout 600s;/g) || []).length, 2);
}
assert.match(api, /diagrams\/\$\{encodeURIComponent\(diagramId\)\}\/vision\/apply/);
assert.match(chat, /current\.id === "diseno" && canImportPhoto/);
assert.match(board, /canImportPhoto=\{!readOnly\}/);
assert.match(board, /<ImportFromPhotoModal diagramId=\{id\}/);
assert.match(dashboard, /<ImportFromPhotoModal onClose=/);
assert.doesNotMatch(dashboard, /diagramId=/);
assert.match(styles, /\.photo-import-modal/);
console.log("Photo import checks passed.");
