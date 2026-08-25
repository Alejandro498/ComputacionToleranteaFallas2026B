**Conceptos Fundamentales en Tolerancia a Fallas**

* **Sistemas tolerantes a fallas:** Son sistemas diseñados para continuar operando correctamente (posiblemente a un nivel de rendimiento reducido o "degradación elegante") incluso en presencia de fallas de hardware o software, evitando una caída total del servicio.
* **Falla (*Fault*):** Es la causa raíz física, lógica o de diseño de una anomalía interna (por ejemplo, una celda de memoria defectuosa, un cable desconectado o un *bug* en el código).
* **Error (*Error*):** Es la manifestación interna de una falla; representa un estado incorrecto dentro del sistema (por ejemplo, un bit invertido en la memoria o un valor de variable corrupto). Si no se maneja, un error puede provocar una **avería/fracaso (*Failure*)**, que es cuando el sistema incumple su especificación ante el usuario.
* **Latencia de un fallo (*Fault Latency*):** Es el intervalo de tiempo que transcurre desde que la falla ocurre físicamente o se introduce en el sistema hasta que se manifiesta como un error en el estado interno.
* **Latencia de un error (*Error Latency*):** Es el tiempo transcurrido desde que se genera el error en el estado interno hasta que es detectado por los mecanismos del sistema o produce una avería visible externa.

---

**Tipos de Fallos**

* **Transitorios:** Ocurren una sola vez y desaparecen espontáneamente. Suelen ser provocados por fluctuaciones ambientales temporales (ruido electromagnético, rayos cósmicos o picos de voltaje).
* **Intermitentes:** Aparecen y desaparecen de forma recurrente sin un patrón fijo. Suelen deberse a conexiones flojas, sobrecalentamiento intermitente o condiciones de carrera (*race conditions*) en el software.
* **Permanentes:** Persisten de forma indefinida hasta que el componente afectado es reparado o reemplazado (por ejemplo, un disco duro quemado o un corte físico de cable).

---

**Métricas Clave de Rendimiento y Confiabilidad**

| Métrica | Definición | Fórmula / Relación |
| --- | --- | --- |
| **Disponibilidad (*Availability*)** | Probabilidad de que el sistema esté operativo y accesible en un instante de tiempo $t$. | $\text{Disponibilidad} = \frac{\text{MTTF}}{\text{MTTF} + \text{MTTR}}$ |
| **Confiabilidad (*Reliability*)** | Probabilidad de que el sistema funcione de manera continua y correcta durante un intervalo de tiempo específico sin interrupciones. | $R(t) = e^{-\lambda t}$ (en tasas de fallo constantes) |
| **MTTF (*Mean Time To Failure*)** | Tiempo medio hasta el fallo; promedio de tiempo que un sistema no reparable opera antes de fallar. | Promedio de vida útil antes de la avería |
| **MTTR (*Mean Time To Repair*)** | Tiempo medio de reparación; promedio de tiempo requerido para detectar, reparar y restaurar el sistema al estado operativo. | Promedio de duración de las interrupciones |