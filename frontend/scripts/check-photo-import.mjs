import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const modal = readFileSync(new URL("../src/features/photo-import/ImportFromPhotoModal.jsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/features/photo-import/vision.js", import.meta.url), "utf8");
const dashboard = readFileSync(new URL("../src/pages/DashboardPage.jsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/style.css", import.meta.url), "utf8");

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
assert.match(api, /FormData/);
assert.match(api, /\/vision\/detect/);
assert.match(api, /\/vision\/apply/);
assert.match(api, /120000/);
assert.match(styles, /\.photo-import-modal/);
console.log("Photo import checks passed.");
