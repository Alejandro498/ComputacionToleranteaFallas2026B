## 1. Prevención y Análisis Estático (Tiempo de Escritura)
Aquí el código ni siquiera se está ejecutando. Las herramientas analizan el texto puro (el código fuente) buscando patrones de error antes de compilar.

* **Linters (Reglas de Estilo y Lógica):** Buscan errores tipográficos, variables no usadas o ciclos infinitos. Es como un corrector ortográfico.
  * *Ejemplos:* ESLint (para JavaScript/TypeScript), Pylint o Flake8 (para Python), RuboCop (para Ruby).
* **Type Checkers (Verificadores de Tipos):** Se aseguran de que no intentes mezclar datos incompatibles (como sumar un texto con un número).
  * *Ejemplos:* TypeScript (el estándar de facto para JS), MyPy (para Python).
* **SAST (Pruebas de Seguridad Estática):** Escanean el código buscando vulnerabilidades (contraseñas en texto plano, inyecciones SQL accidentales).
  * *Ejemplos:* SonarQube (análisis de calidad y seguridad general), Snyk (muy enfocado en vulnerabilidades de dependencias), Semgrep.

## 2. Depuradores / Debuggers (Tiempo de Desarrollo)
Cuando el código compila pero hace algo inesperado, el depurador entra en juego para inspeccionar las entrañas del programa mientras se ejecuta.

* **Breakpoints y Call Stack (Puntos de interrupción y Pila de llamadas):** Congelan el tiempo en una línea específica y te muestran la ruta que tomó el programa para llegar ahí.
  * *Ejemplos:* Están integrados en los entornos de desarrollo (IDEs). Los más potentes son el Visual Studio Code Debugger, los depuradores de la familia IntelliJ (JetBrains), y Chrome DevTools (para la web). Para bajo nivel se usa GDB (C/C++).
* **Time-Travel Debugging (Depuración de viaje en el tiempo):** Permite "rebobinar" la ejecución para ver el estado de los datos antes de que ocurriera el error.
  * *Ejemplos:* Redux DevTools (muy usado en el ecosistema React), rr (creado por Mozilla para C/C++), o herramientas premium como Wallaby.js.

## 3. Pruebas Automatizadas (Tiempo de Validación)
Escribes código para probar tu propio código, asegurando que los cambios nuevos no rompan lo que ya funcionaba.

* **Pruebas Unitarias (La base):** Aíslan una sola función pequeña y verifican su resultado. Son rapidísimas.
  * *Ejemplos:* Jest o Vitest (JavaScript), JUnit (Java), PyTest (Python).
* **Pruebas de Integración (El medio):** Verifican que dos piezas funcionen bien juntas (ej. conectar tu código a una base de datos real).
  * *Ejemplos:* Testcontainers (levanta bases de datos temporales para probar), Supertest (para probar APIs en Node.js), Postman (automatización de flujos de API).
* **Pruebas de Mutación (Prueba de estrés):** La herramienta introduce errores a propósito en tu código (ej. cambia un `+` por un `-`) para ver si tus pruebas unitarias se dan cuenta.
  * *Ejemplos:* Stryker (para JavaScript, C# y Scala), Pitest (para Java), Mutmut (para Python).

## 4. Monitoreo y Captura en Producción (Tiempo Real)
Cuando el software ya está en manos del usuario. Se basa en tres pilares de datos y una categoría de captura directa:

* **Crash Reporting (Captura de Excepciones):** Atrapan el error exacto cuando ocurre en la pantalla del usuario.
  * *Ejemplos:* Sentry (el líder actual), Bugsnag, Crashlytics (de Firebase, muy usado en apps móviles).
* **Logs (Registros):** Un diario cronológico escrito en texto de todo lo que hace el servidor (ej. "Usuario X inició sesión").
  * *Ejemplos:* ELK Stack (Elasticsearch, Logstash, Kibana - el estándar open source), Splunk, Datadog.
* **Metrics (Métricas):** Los signos vitales del sistema en números globales (ej. "Uso de CPU al 90%").
  * *Ejemplos:* Prometheus (para recolectar) combinado con Grafana (para visualizar los tableros), New Relic.
* **Traces (Trazabilidad):** Siguen el viaje de una sola petición a través de múltiples servidores (microservicios) para ver en cuál se rompió la cadena.
  * *Ejemplos:* Jaeger, OpenTelemetry (el estándar de recolección), Datadog APM, Honeycomb.

## 5. Gestión de Incidencias y Bugs (Seguimiento y Resolución)
El flujo humano y administrativo. Donde los errores detectados se documentan, priorizan y resuelven.

* **Triage y Tracking (Clasificación y Seguimiento):** Herramientas de ticketing donde se reporta el bug y se asigna al programador.
  * *Ejemplos:* Jira (el estándar corporativo), Linear (muy popular hoy en día por su velocidad), GitHub Issues / GitLab Boards, YouTrack.
* **Gestión de Incidentes y Alarmas:** Para errores masivos en producción (ej. "se cayó el servidor de pagos"). Despiertan a los programadores en la madrugada si es necesario.
  * *Ejemplos:* PagerDuty, Opsgenie.
* **Post-mortem (Documentación):** Donde el equipo escribe por qué ocurrió el fallo y cómo evitarlo en el futuro.
  * *Ejemplos:* Confluence, Notion, o plataformas especializadas como Incident.io.