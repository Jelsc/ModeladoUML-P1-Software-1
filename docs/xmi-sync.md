# Sincronización XMI (Enterprise Architect)

Código: `backend/exporters/xmi.py` (parser/exportador) y `backend/exporters/xmi_merge.py` (merge diferencial).

## Importación diferencial (`POST /diagrams/{id}/xmi/import`, `mode=merge`, por defecto)

- Nunca elimina ni sobrescribe. `POST .../xmi/validate` hace un ensayo (rollback) y devuelve el informe `merge`.
- Identidad de clases/atributos/métodos/relaciones, en orden:
  1. El ID XMI coincide con el ID que este editor exporta para el elemento guardado (derivado de su UUID).
  2. Respaldo: nombre de clase; nombre de miembro dentro de la clase; `(tipo, extremos, etiqueta)` en relaciones (varias relaciones iguales se emparejan por orden).
- Nombres ambiguos o dos elementos del XMI contra el mismo elemento guardado → se reportan en `conflicts` y se omiten.
- Diferencias de tipo o multiplicidad en elementos existentes → `conflicts`; se conserva el valor guardado. Un valor vacío sí se completa.
- Clases nuevas sin coordenadas (o que se superpondrían) se colocan en una rejilla libre.
- `mode=replace` (con `confirm=true`) conserva el comportamiento anterior de reemplazo total.

## Clases de asociación M:N

- Exportación (estructura tomada de un XMI real de EA): un único `uml:AssociationClass` con sus dos `ownedEnd`/`memberEnd` y los atributos de la clase; no se genera una `uml:Association` aparte. El conector gráfico tiene id propio, `properties subtype="Class"` y `extendedProperties associationclass`/`privatedata1`; el elemento de la clase lleva `nType="17"` y `conID` con el id del conector. El id del `AssociationClass` se deriva de la relación, así que al reimportar la relación se reconoce por id y la clase por nombre.
- Importación: lee un `uml:AssociationClass` (o el atributo `associationclass`), reconstruye `association_class_id` / `is_association` y solo vincula si la relación es asociación muchos a muchos.
- EA solo guarda un nombre: la etiqueta de la relación pasa a ser el nombre de la clase.

## Limitaciones conocidas

- Hay una muestra real de EA en `backend/tests/fixtures/ea_examen.xmi`; las pruebas comprueban que nuestra exportación cumpla sus mismas reglas estructurales. La apertura visual en EA de la exportación nueva aún debe confirmarse a mano.
- Sin columna de ID XMI en la base de datos: una clase creada en EA y renombrada allí después de importarla se verá como nueva. Una migración con `xmi_id` lo resolvería.
- No se conservan: parámetros de métodos, visibilidad, modificadores, abstracción, paquetes (los homónimos se renombran `Nombre (Paquete)`), interfaces/enumeraciones, waypoints.
- Las composiciones/agregaciones se orientan con el "todo" como destino (convención del editor).
