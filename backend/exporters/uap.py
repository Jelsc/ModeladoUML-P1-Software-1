import json

from .validator import entity_route_path
from .cardinality import relation_owned_columns


UAP_VERSION = "1.0"


def _json_literal(value):
    raw = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return raw.replace("\\", "\\\\").replace('"', '\\"')


def _java_value(field_type, field):
    value = f"input.get(\"{field}\")"
    if field_type == "String":
        return f"{value}.asText()"
    if field_type in {"Integer", "Long", "Double", "Float", "BigDecimal"}:
        method = {"Integer": "intValue", "Long": "longValue", "Double": "doubleValue", "Float": "floatValue", "BigDecimal": "decimalValue"}[field_type]
        return f"{value}.{method}()"
    if field_type == "Boolean":
        return f"{value}.booleanValue()"
    if field_type == "LocalDate":
        return f"java.time.LocalDate.parse({value}.asText())"
    if field_type == "OffsetDateTime":
        return f"java.time.OffsetDateTime.parse({value}.asText())"
    return f"{value}.asText()"


def _id_type(item):
    identifier = next(
        (attribute for attribute in item["attributes"] if attribute["generated_name"] == "id"),
        None,
    )
    return _schema_type(identifier.get("type") if identifier else "integer")


def _writable_attributes(item, owned_columns=None):
    owned_columns = owned_columns or set()
    return [
        attribute for attribute in item["attributes"]
        if attribute["generated_name"] != "id" and attribute["generated_name"] not in owned_columns
    ]


def _input_schema(item, include_id=False, owned_columns=None):
    properties = {}
    if include_id:
        properties["id"] = {"type": _id_type(item), "writeable": True}
    for attribute in _writable_attributes(item, owned_columns):
        properties[attribute["generated_name"]] = {
            "type": _schema_type(attribute.get("type")),
            "writeable": True,
        }
    return {"type": "object", "properties": properties, "additionalProperties": False}


def _schema_type(value):
    value = str(value or "string").lower()
    if value in {"int", "integer", "long"}:
        return "integer"
    if value in {"float", "double", "decimal", "number"}:
        return "number"
    if value in {"boolean", "bool"}:
        return "boolean"
    return "string"


def metadata(diagram):
    title = diagram.get("title") or "Generated UML service"
    classes = diagram["classes"]
    tools = []
    schema_entities = []
    owned_columns = relation_owned_columns(diagram)
    for item in classes:
        name = item["generated_name"]
        path = entity_route_path(name)
        fields = [{"name": "id", "type": _id_type(item), "readOnly": True}]
        fields += [{"name": a["generated_name"], "type": _schema_type(a.get("type")), "readOnly": False}
                   for a in _writable_attributes(item, owned_columns.get(item["name"]))]
        schema_entities.append({"name": name, "originalName": item["name"], "path": path,
                                "fields": fields, "createInput": _input_schema(item, owned_columns=owned_columns.get(item["name"])),
                                "updateInput": _input_schema(item, owned_columns=owned_columns.get(item["name"]))})
        for operation, method, suffix, mutation in (
            ("list", "GET", "", False), ("get", "GET", "/{id}", False),
            ("create", "POST", "", True), ("update", "PUT", "/{id}", True),
            ("delete", "DELETE", "/{id}", True),
        ):
            tools.append({"id": f"{name.lower()}.{operation}", "name": f"{operation.title()} {name}",
                          "operation": operation, "entity": name, "method": method,
                          "path": path + suffix, "inputSchema": _input_schema(item, include_id=operation == "update", owned_columns=owned_columns.get(item["name"])) if operation in {"create", "update"} else {"type": "object"},
                          "output": {"type": "array" if operation == "list" else "object"},
                          "permissions": ["public-mvp"], "sideEffects": mutation,
                          "requiresConfirmation": mutation})
    return {
        "manifest": {"protocol": "UAP", "version": UAP_VERSION, "service": "generated-spring-backend",
                     "domain": title, "name": title, "links": {"schema": "/uap/v1/schema", "tools": "/uap/v1/tools",
                       "permissions": "/uap/v1/permissions", "businessRules": "/uap/v1/business-rules", "syncState": "/uap/v1/sync/state", "syncChanges": "/uap/v1/sync/changes", "syncPush": "/uap/v1/sync/push"}},
        "schema": {"version": UAP_VERSION, "entities": schema_entities},
        "tools": {"version": UAP_VERSION, "tools": tools},
        "permissions": {"version": UAP_VERSION, "authentication": "none", "permissions": ["public-mvp"],
                         "note": "Local MVP is unauthenticated; production deployments must add authentication and authorization."},
        "businessRules": {"version": UAP_VERSION, "rules": [], "note": "No UML methods are executable UAP tools."},
    }


def _entity_cases(diagram):
    cases = []
    helpers = []
    for item in diagram["classes"]:
        name = item["generated_name"]
        service = f"{name.lower()}Service"
        owned = relation_owned_columns(diagram).get(item["name"], set())
        fields = _writable_attributes(item, owned)
        setters = []
        allowed = []
        for attr in fields:
            field = attr["generated_name"]
            java_type = {"int": "Integer", "integer": "Integer", "long": "Long", "float": "Float", "double": "Double", "decimal": "BigDecimal", "number": "BigDecimal", "boolean": "Boolean", "bool": "Boolean", "date": "LocalDate", "datetime": "OffsetDateTime", "string": "String"}.get(str(attr.get("type", "string")).lower(), "String")
            allowed.append(f'"{field}"')
            setters.append(f'        if (input.has("{field}")) entity.set{field[0].upper() + field[1:]}({_java_value(java_type, field)});')
        allowed_expr = ", ".join(allowed)
        apply = "\n".join(setters) or "        // This entity has no writable scalar fields."
        cases.append(f'''            case "{name.lower()}.list": {{ rejectUnknown(input, Set.of()); return ok({service}.findAll()); }}
            case "{name.lower()}.get": {{ rejectUnknown(input, Set.of("id")); return get{ name }({service}, input); }}
             case "{name.lower()}.create": {{ rejectUnknown(input, Set.of({allowed_expr})); {name} entity = new {name}(); apply{ name }(input, entity); {name} saved = {service}.save(entity); recordMutation("{name}", saved.getId().toString(), "create", mapper.valueToTree(saved)); return ok(saved); }}
              case "{name.lower()}.update": {{ Long id = id(input); rejectUnknown(input, Set.of("id"{', ' if allowed_expr else ''}{allowed_expr})); {name} entity = {service}.findById(id).orElseThrow(() -> new UapException("NOT_FOUND", "Entity not found")); apply{ name }(input, entity); {name} saved = {service}.save(entity); recordMutation("{name}", saved.getId().toString(), "update", mapper.valueToTree(saved)); return ok(saved); }}
              case "{name.lower()}.delete": {{ Long recordId = id(input); {service}.delete(recordId); recordMutation("{name}", recordId.toString(), "delete", input); return ok(Map.of("deleted", true)); }}
''')
        helpers.append(f'''    private String get{ name }({name}Service service, JsonNode input) {{ return service.findById(id(input)).map(this::ok).orElseThrow(() -> new UapException("NOT_FOUND", "Entity not found")); }}
    private void apply{ name }(JsonNode input, {name} entity) {{
{apply}
    }}
''')
    return "\n".join(cases), "\n".join(helpers)


def dispatcher_source(diagram, package="com.generated.uml"):
    metadata_json = metadata(diagram)
    entity_imports = f"import {package}.models.*;\nimport {package}.services.*;" if diagram["classes"] else ""
    injections = "\n".join(f"    private final {item['generated_name']}Service {item['generated_name'].lower()}Service;" for item in diagram["classes"])
    constructor_args = ", ".join(f"{item['generated_name']}Service {item['generated_name'].lower()}Service" for item in diagram["classes"])
    assignments = "\n".join(f"        this.{item['generated_name'].lower()}Service = {item['generated_name'].lower()}Service;" for item in diagram["classes"])
    cases, helpers = _entity_cases(diagram)
    return f'''package {package}.uap;

 import com.fasterxml.jackson.databind.JsonNode;
 import com.fasterxml.jackson.databind.ObjectMapper;
 import com.fasterxml.jackson.databind.node.ObjectNode;
 {entity_imports}
 import org.springframework.stereotype.Service;
import java.util.*;

@Service
public class UapService {{
 {injections}
     private final SyncStore sync;
    private final ObjectMapper mapper;
     public UapService({constructor_args}{', ' if constructor_args else ''}ObjectMapper mapper, SyncStore sync) {{
{assignments}
         this.mapper = mapper;
         this.sync = sync;
    }}
    public String metadata(String resource) {{
        String value = switch (resource) {{
            case "manifest" -> "{_json_literal(metadata_json['manifest'])}";
            case "schema" -> "{_json_literal(metadata_json['schema'])}";
            case "tools" -> "{_json_literal(metadata_json['tools'])}";
            case "permissions" -> "{_json_literal(metadata_json['permissions'])}";
            case "business-rules" -> "{_json_literal(metadata_json['businessRules'])}";
            default -> throw new UapException("UNKNOWN_RESOURCE", "Unknown UAP resource");
        }};
        return value;
    }}
    public String invoke(String toolId, JsonNode input, boolean confirmation) {{
        if (toolId == null || !toolId.matches("[a-z0-9_]+\\\\.(list|get|create|update|delete)")) throw new UapException("UNKNOWN_TOOL", "Unknown UAP tool");
        String operation = toolId.substring(toolId.indexOf('.') + 1);
        if (!operation.equals("list") && !operation.equals("get") && !confirmation) throw new UapException("CONFIRMATION_REQUIRED", "Mutation requires explicit confirmation");
        try {{
            switch (toolId) {{
 {cases}
                default: throw new UapException("UNKNOWN_TOOL", "Unknown UAP tool");
            }}
        }} catch (UapException e) {{ throw e; }} catch (Exception e) {{ throw new UapException("INVALID_INPUT", "Invalid tool input"); }}
    }}
    private String ok(Object data) {{ try {{ return mapper.writeValueAsString(Map.of("ok", true, "data", data)); }} catch (Exception e) {{ throw new UapException("SERIALIZATION_ERROR", "Could not serialize result"); }} }}
    private Long id(JsonNode input) {{ if (input == null || !input.has("id") || !input.get("id").canConvertToLong() || input.get("id").asLong() <= 0) throw new UapException("INVALID_ID", "A positive numeric id is required"); return input.get("id").asLong(); }}
     private void rejectUnknown(JsonNode input, Set<String> allowed) {{ if (input == null || !input.isObject()) throw new UapException("INVALID_INPUT", "Input must be an object"); Iterator<String> names = input.fieldNames(); while (names.hasNext()) {{ String field = names.next(); if (!allowed.contains(field)) throw new UapException("UNKNOWN_FIELD", "Unknown field: " + field); }} }}
     private void recordMutation(String entity, String recordId, String operation, JsonNode payload) {{ String eventId = UUID.randomUUID().toString(); sync.record(eventId, eventId, entity, recordId, operation, recordId, payload); }}
      public String syncState() {{ return sync.state(); }}
      public String syncChanges(long since) {{ return sync.changes(since); }}
     public String syncPush(JsonNode body) {{
         List<Map<String,Object>> results = new ArrayList<>();
         if (body == null || !body.isObject() || !body.has("operations") || !body.get("operations").isArray() || body.get("operations").size() > 50) throw new UapException("INVALID_INPUT", "operations must be a bounded array");
         for (JsonNode op : body.get("operations")) {{
              String operationId = op.path("operationId").asText(""); String clientRecordId = op.path("clientRecordId").asText(op.path("localId").asText("")); String entity = op.path("entity").asText(""); String operation = op.path("operation").asText(""); String recordId = op.path("serverId").asText(op.path("recordId").asText(""));
             try {{
                  if (!operationId.matches("[A-Za-z0-9._-]{{1,100}}") || !clientRecordId.matches("[A-Za-z0-9._-]{{1,100}}") || !entity.matches("[A-Za-z0-9_]{{1,80}}") || (!operation.equals("create") && !recordId.matches("[A-Za-z0-9._-]{{1,100}}"))) throw new UapException("INVALID_INPUT", "Invalid sync identity");
                 if (!Set.of({', '.join(json.dumps(item['generated_name']) for item in diagram['classes'])}).contains(entity)) throw new UapException("UNKNOWN_ENTITY", "Unknown sync entity");
                 if (!Set.of("create", "update", "delete").contains(operation)) throw new UapException("UNKNOWN_OPERATION", "Unknown sync operation");
                  Map<String,Object> replay = sync.replay(operationId, clientRecordId); if (sync.seen(operationId) || replay != null) {{ results.add(replay); continue; }}
                  long current = sync.currentVersion(entity, recordId); if (!operation.equals("create") && op.has("baseVersion") && !op.get("baseVersion").isNull() && op.get("baseVersion").asLong() != current) {{ results.add(Map.of("operationId", operationId, "clientRecordId", clientRecordId, "status", "conflict", "error", "Stale baseVersion", "serverVersion", current)); continue; }}
                 JsonNode payload = op.path("payload"); if (!payload.isObject()) throw new UapException("INVALID_INPUT", "payload must be an object");
                 ObjectNode input = payload.deepCopy(); if (!operation.equals("create")) input.put("id", Long.parseLong(recordId));
                  JsonNode persisted = mapper.readTree(invoke(entity.toLowerCase() + "." + operation, input, true)); JsonNode serverRecord = persisted.path("data"); String serverId = serverRecord.path("id").asText(recordId); long version = sync.record(operationId, clientRecordId, entity, serverId, operation, serverId, serverRecord); results.add(Map.of("operationId", operationId, "clientRecordId", clientRecordId, "serverId", serverId, "status", "synced", "serverVersion", version, "serverRecord", serverRecord, "record", serverRecord));
             }} catch (UapException e) {{ results.add(Map.of("operationId", operationId, "status", "failed", "error", e.getMessage())); }} catch (Exception e) {{ results.add(Map.of("operationId", operationId, "status", "failed", "error", "Invalid sync operation")); }}
         }}
         try {{ return mapper.writeValueAsString(Map.of("results", results)); }} catch (Exception e) {{ throw new UapException("SERIALIZATION_ERROR", "Could not serialize sync result"); }}
     }}
 {helpers}
 }}
 '''


def sync_store_source(package="com.generated.uml"):
    return f'''package {package}.uap;
import com.fasterxml.jackson.databind.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import jakarta.annotation.PostConstruct;
import java.util.*;
@Component
public class SyncStore {{
    private final JdbcTemplate jdbc; private final ObjectMapper mapper;
    public SyncStore(JdbcTemplate jdbc, ObjectMapper mapper) {{ this.jdbc = jdbc; this.mapper = mapper; }}
      @PostConstruct public void init() {{ jdbc.execute("CREATE TABLE IF NOT EXISTS uap_sync_state (state_id SMALLINT PRIMARY KEY, generation VARCHAR(100) NOT NULL, created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP)"); jdbc.update("INSERT INTO uap_sync_state(state_id, generation) SELECT 1, ? WHERE NOT EXISTS (SELECT 1 FROM uap_sync_state WHERE state_id = 1)", UUID.randomUUID().toString()); jdbc.execute("CREATE TABLE IF NOT EXISTS uap_sync_ledger (operation_id VARCHAR(100) PRIMARY KEY, client_record_id VARCHAR(100), entity_name VARCHAR(80) NOT NULL, record_id VARCHAR(100) NOT NULL, operation VARCHAR(20) NOT NULL, payload_json TEXT NOT NULL, version BIGINT NOT NULL, updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP)"); try {{ jdbc.execute("ALTER TABLE uap_sync_ledger ADD COLUMN client_record_id VARCHAR(100)"); }} catch (Exception ignored) {{ }} jdbc.update("UPDATE uap_sync_ledger SET client_record_id = operation_id WHERE client_record_id IS NULL"); jdbc.execute("CREATE UNIQUE INDEX IF NOT EXISTS uap_sync_client_identity ON uap_sync_ledger(entity_name, client_record_id)"); }}
    public boolean seen(String id) {{ return !jdbc.queryForList("SELECT operation_id FROM uap_sync_ledger WHERE operation_id = ?", id).isEmpty(); }}
     public long currentVersion(String entity, String recordId) {{ List<Map<String,Object>> rows = jdbc.queryForList("SELECT COALESCE(MAX(version),0) version FROM uap_sync_ledger WHERE entity_name = ? AND record_id = ?", entity, recordId); return ((Number) rows.get(0).get("version")).longValue(); }}
     public long record(String operationId, String clientRecordId, String entity, String recordId, String operation, String serverId, JsonNode payload) {{ if (seen(operationId)) return jdbc.queryForObject("SELECT version FROM uap_sync_ledger WHERE operation_id = ?", Long.class); List<Map<String,Object>> mapped = jdbc.queryForList("SELECT version FROM uap_sync_ledger WHERE entity_name = ? AND client_record_id = ?", entity, clientRecordId); if (!mapped.isEmpty()) return ((Number) mapped.get(0).get("version")).longValue(); Number next = jdbc.queryForObject("SELECT COALESCE(MAX(version),0)+1 FROM uap_sync_ledger", Number.class); jdbc.update("INSERT INTO uap_sync_ledger(operation_id, client_record_id, entity_name, record_id, operation, payload_json, version) VALUES (?, ?, ?, ?, ?, ?, ?)", operationId, clientRecordId, entity, serverId, operation, payload.toString(), next.longValue()); return next.longValue(); }}
     public void record(String operationId, String entity, String recordId, String operation, JsonNode payload) {{ record(operationId, operationId, entity, recordId, operation, recordId, payload); }}
     public Map<String,Object> replay(String operationId, String clientRecordId) {{ List<Map<String,Object>> rows = jdbc.queryForList("SELECT entity_name, record_id, payload_json, version FROM uap_sync_ledger WHERE operation_id = ? OR client_record_id = ?", operationId, clientRecordId); if (rows.isEmpty()) return null; Map<String,Object> row = rows.get(0); try {{ return new LinkedHashMap<>(Map.of("operationId", operationId, "clientRecordId", clientRecordId, "serverId", row.get("record_id"), "status", "synced", "serverVersion", row.get("version"), "serverRecord", mapper.readTree((String) row.get("payload_json")), "record", mapper.readTree((String) row.get("payload_json")))); }} catch (Exception e) {{ throw new UapException("SYNC_READ_FAILED", "Could not replay sync operation"); }} }}
      public String state() {{ try {{ Map<String,Object> row = jdbc.queryForMap("SELECT generation FROM uap_sync_state WHERE state_id = 1"); Number cursor = jdbc.queryForObject("SELECT COALESCE(MAX(version),0) FROM uap_sync_ledger", Number.class); return mapper.writeValueAsString(Map.of("generation", row.get("generation"), "cursor", cursor.longValue(), "serverTime", java.time.Instant.now().toString())); }} catch (Exception e) {{ throw new UapException("SYNC_READ_FAILED", "Could not read sync state"); }} }}
      public String changes(long since) {{ try {{ List<Map<String,Object>> changes = new ArrayList<>(); for (Map<String,Object> row : jdbc.queryForList("SELECT operation_id, entity_name, client_record_id, record_id, operation, payload_json, version FROM uap_sync_ledger WHERE version > ? ORDER BY version ASC", since)) {{ Map<String,Object> item = new LinkedHashMap<>(); item.put("operationId", row.get("operation_id")); item.put("entity", row.get("entity_name")); item.put("clientRecordId", row.get("client_record_id")); item.put("serverId", row.get("record_id")); item.put("recordId", row.get("record_id")); item.put("operation", row.get("operation")); item.put("payload", mapper.readTree((String) row.get("payload_json"))); item.put("version", row.get("version")); changes.add(item); }} long cursor = changes.isEmpty() ? since : ((Number) changes.get(changes.size()-1).get("version")).longValue(); return mapper.writeValueAsString(Map.of("cursor", cursor, "changes", changes)); }} catch (Exception e) {{ throw new UapException("SYNC_READ_FAILED", "Could not read sync changes"); }} }}
}}
'''


def controller_source(package="com.generated.uml"):
    return f'''package {package}.uap;
import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
@RestController
@RequestMapping("/uap/v1")
public class UapController {{
    private final UapService service;
    public UapController(UapService service) {{ this.service = service; }}
    @GetMapping(value="/manifest", produces=MediaType.APPLICATION_JSON_VALUE) public String manifest() {{ return service.metadata("manifest"); }}
    @GetMapping(value="/schema", produces=MediaType.APPLICATION_JSON_VALUE) public String schema() {{ return service.metadata("schema"); }}
    @GetMapping(value="/tools", produces=MediaType.APPLICATION_JSON_VALUE) public String tools() {{ return service.metadata("tools"); }}
    @GetMapping(value="/permissions", produces=MediaType.APPLICATION_JSON_VALUE) public String permissions() {{ return service.metadata("permissions"); }}
     @GetMapping(value="/business-rules", produces=MediaType.APPLICATION_JSON_VALUE) public String businessRules() {{ return service.metadata("business-rules"); }}
      @GetMapping(value="/sync/state", produces=MediaType.APPLICATION_JSON_VALUE) public String state() {{ return service.syncState(); }}
      @GetMapping(value="/sync/changes", produces=MediaType.APPLICATION_JSON_VALUE) public String changes(@RequestParam(defaultValue="0") long since) {{ return service.syncChanges(Math.max(0, since)); }}
     @PostMapping(value="/sync/push", produces=MediaType.APPLICATION_JSON_VALUE) public String push(@RequestBody JsonNode body) {{ return service.syncPush(body); }}
    @PostMapping(value="/tools/{{toolId}}/invoke", produces=MediaType.APPLICATION_JSON_VALUE) public ResponseEntity<String> invoke(@PathVariable String toolId, @RequestParam(defaultValue="false") boolean confirmation, @RequestBody(required=false) JsonNode input) {{ return ResponseEntity.ok(service.invoke(toolId, input, confirmation)); }}
    @ExceptionHandler(UapException.class) public ResponseEntity<String> error(UapException e) {{ return ResponseEntity.status(e.code.equals("UNKNOWN_TOOL") || e.code.equals("UNKNOWN_RESOURCE") ? 404 : 400).body("{{\\"ok\\":false,\\"error\\":{{\\"code\\":\\"" + e.code + "\\",\\"message\\":\\"" + e.getMessage().replace("\\\"", "'") + "\\"}}}}"); }}
}}
'''


def exception_source(package="com.generated.uml"):
    return f'''package {package}.uap;
public class UapException extends RuntimeException {{ public final String code; public UapException(String code, String message) {{ super(message); this.code = code; }} }}
'''
