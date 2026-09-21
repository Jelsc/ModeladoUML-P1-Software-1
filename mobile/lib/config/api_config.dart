/// Configuración pública de endpoints para el backend generado.
///
/// Esto NO es un secreto ni una API key. Para uso normal en LAN/emulador/deploy,
/// asigná [activeBackendUrl] a [deployedBackendUrl] (o la URL LAN accesible)
/// y dejá [backendHostHeader] en null.
const deployedBackendUrl =
    'https://api-gymnasio-f3d823e4.primerpacialsw.duckdns.org';

/// URL del lado del teléfono para `adb reverse tcp:8080 tcp:80`.
const usbTestBackendUrl = 'http://127.0.0.1:8080';

/// Configuración usada automáticamente al arrancar. Cambiá esto a
/// [deployedBackendUrl] para routing normal en LAN/emulador/deploy.
const activeBackendUrl = deployedBackendUrl;

/// Nginx necesita el hostname de deploy generado, mientras que el socket USB
/// usa la URL de loopback. Se aplica solo cuando [activeBackendUrl] es la URL USB.
const backendHostHeader = null;

String? hostHeaderFor(String baseUrl) =>
    baseUrl == usbTestBackendUrl ? backendHostHeader : null;
