# Práctica: Workflow manager (Apache Airflow)

Implementé un **ETL de tres tasks** con Apache Airflow 3. Es el mismo patrón que en `WorkflowManagers` (extract → transform → load), ahora como un **DAG**: Airflow guarda el estado de cada task, reintenta solo la que falla y deja el grafo para verlo en la UI.

---

## ¿Qué es Airflow?

**Apache Airflow** es un *workflow manager*. El programa que encadena los pasos es un **DAG** y cada paso es una **task**. El scheduler decide cuándo corre cada task según las dependencias. Aquí las tasks se escriben con la **TaskFlow API** (`@dag` y `@task`, importadas de `airflow.sdk`).

El valor de retorno de una task pasa a la siguiente. Por debajo eso es un **XCom**; en el código se ve como una llamada normal entre funciones.

| Concepto | En este ejemplo | Rol |
| --- | --- | --- |
| DAG | `etl_posts` | Orquesta las tres tasks |
| Task | `@task` | extraer, transformar o cargar |
| Reintento | `retries=2` en `extraer` | Vuelve a correr solo esa task si falla |
| XCom | el `return` de cada task | Pasa los posts y el resumen a la task de abajo |

---

## Propuesta del escenario

### El problema

Hay que bajar posts de una API, contarlos por usuario y guardar el resumen. Son tres pasos distintos. Si la red falla a mitad, no hace falta repetir el pipeline entero: basta con repetir la descarga.

### Por qué un workflow manager

Airflow marca cada task (success, failed, up_for_retry). El reintento está en la task de red. Transformar y cargar no se vuelven a ejecutar si no llegaron a correr, y no se reintentan solas: un error ahí es de lógica o de disco.

### Qué tipo de falla puede ocurrir

Falla **transitoria de red** (timeout). Para que se vea en la corrida, el primer intento de `extraer` lanza `ConnectionError` a propósito. El segundo intento hace el `GET` real a [jsonplaceholder.cypress.io/posts](https://jsonplaceholder.cypress.io/posts).

### Qué estrategia de tolerancia se aplica

**Reintentos de la task** (`retries=2`, espera de 2 segundos). Airflow reejecuta `extraer` y, cuando termina bien, sigue con `transformar` y `cargar`. Esas dos no tienen `retries`.

---

## Cómo está armado

| Archivo | Rol |
| --- | --- |
| `dags/etl_posts.py` | DAG `etl_posts`: extraer → transformar → cargar |
| `requirements.txt` | Airflow 3.3.2 con el archivo de constraints oficial |
| `salida/resumen_posts.json` | Resumen generado al correr (gitignorado) |

El DAG no tiene horario (`schedule=None`): se dispara a mano o con `dag.test()`.

---

## Cómo ejecutarlo

Desde esta carpeta, con un venv aparte (Airflow arrastra muchas dependencias; no lo mezcles con el `.venv` de la raíz):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python dags\etl_posts.py
```

La primera vez el script crea la base de metadata en esta carpeta. En la consola se ve el intento 1 en `up_for_retry`, el intento 2 con el `GET` (100 posts) y al final `state=success`. El resumen queda en `salida/resumen_posts.json`.

Airflow avisa que en Windows no está soportado como servicio. Este archivo igual corre `dag.test()`: al inicio adapta unas llamadas POSIX (`register_at_fork`, `fcntl`, señales) que el intérprete de Windows no trae. La UI (`airflow standalone` en el puerto 8080) es para Linux, WSL o Docker.

---

## Qué hace cada task

1. **extraer** — intento 1: timeout simulado. Intento 2: `GET` de los posts.
2. **transformar** — cuenta posts por `userId`.
3. **cargar** — escribe `salida/resumen_posts.json`.

---

## Conclusión

El DAG parte el ETL en tasks con estado propio. La tolerancia a la falla de red está en los reintentos de `extraer`: Airflow no vuelve a lanzar todo el pipeline, solo la task que falló, y cuando esa sale bien el grafo sigue hasta guardar el resumen.
