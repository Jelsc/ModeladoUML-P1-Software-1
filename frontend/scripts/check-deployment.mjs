import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/features/deployment/DeploymentPanel.jsx", import.meta.url), "utf8");

assert.match(source, /Conexión a base de datos/);
assert.match(source, /Descargar colección Postman/);
assert.match(source, /role="dialog"/);
assert.match(source, /aria-modal="true"/);
assert.match(source, /event\.key === "Escape"/);
assert.match(source, /showPassword \? credentials\.password/);
assert.match(source, /postgresql_uri\.replace\(credentials\.password/);
assert.match(source, /aria-hidden=\{credentialsOpen \|\| undefined\}/);
assert.match(source, /navigator\.clipboard\.writeText/);
assert.match(source, /aria-live="polite"/);
assert.match(source, /requestAnimationFrame\(\(\) => credentialsTrigger\.current\?\.focus\(\)\)/);
assert.match(source, /URL\.createObjectURL/);
assert.match(source, /finally \{\s*URL\.revokeObjectURL\(url\)/);

console.log("deployment checks passed");
