# DESIGN.md — Decisiones de diseño

> Documento de **por qué**, no de qué. El *qué* está en
> [ARCHITECTURE.md](ARCHITECTURE.md) (mecanismo del Grafo Vivo), el *uso* en
> [README.md](README.md) y el *para qué* en [PRODUCT.md](PRODUCT.md).
>
> Última revisión: 2026-10-26

---

## Principio rector: determinista, no agéntico

**El LLM nunca decide *qué* hacer. Solo decide *cómo etiquetar* un dato que ya
existe.**

Todo el flujo —parsear el mensaje, elegir el comando, abrir la conexión,
ejecutar el SQL— es código explícito y auditable. El modelo interviene en cuatro
puntos acotados, siempre con entrada y salida JSON:

| Punto | Entrada | Salida | Fallback si falla |
|---|---|---|---|
| `classify.py` | título + contexto del grafo | `project_tag`, `priority` | `Personal` / prioridad 3 / 1h |
| `ocr.py` | imagen | texto o JSON | error explícito a stderr |
| `vision_diff.py` | tarea pendiente + texto OCR | nueva / ya completada | no modifica estado |
| `transcribe.py` | audio | texto | error explícito a stderr |

Ninguno de los cuatro puede crear, borrar o modificar una tarea. Eso lo hace
`tasks.py` con SQL parametrizado.

### Quién decide qué

| Decisión | Dueño |
|---|---|
| ¿Qué comando se ejecutó? | `bot.py` / `cli.py` — parsing explícito |
| ¿Qué tarea se crea? | El usuario que escribió el mensaje |
| ¿Cómo se llama el proyecto? | DeepSeek (acotado, con taxonomía cerrada) |
| ¿Qué tareas se vinculan? | SQL + pgvector (cosine similarity determinista) |
| ¿Qué se consolida de noche? | Umbrales numéricos en `graph.py` |
| ¿Se borra algo? | Nunca automático — se archiva (`status='archived'`) |

---

## Por qué se descartó el Gateway agéntico (OpenClaw)

Se evaluó y se removió del repo. La razón no fue "no funcionaba", fue que **no
había forma de saber qué iba a hacer antes de que lo hiciera**.

Problemas concretos observados:

1. **Routing no determinista.** El agente elegía la herramienta desde lenguaje
   natural. Un mensaje ambiguo ("ponle 4 a la del lab") podía disparar `update`,
   `add` o nada. Con un router explícito, o matchea el comando o no matchea.
2. **Costo por turno.** Cada interacción pagaba un razonamiento completo para
   decidir algo que un `if` resuelve gratis.
3. **Superficie de fallo compuesta.** Fallo de red + fallo de schema + fallo de
   selección de herramienta, todos en el mismo turno.

4. **No testeable.** Un test determinista se escribe como
   `python3 -m src.processing.tasks add --title "X"` y verifica el JSON de
   stdout. Con un agente, el test verifica que el LLM *eligió bien* — que es un
   test estocástico y caro.
5. **Secretos en contexto.** El frontmatter de la skill declaraba `env:
   ["DB_DSN"]`, lo que empuja credenciales hacia el contexto del prompt.

### Lo que sí se conservó de esa etapa

El **contrato de composabilidad**: cada módulo es un ejecutable independiente
que imprime JSON a stdout. `bot.py` no importa lógica de negocio; invoca
subprocesos:

```python
_run(["src.processing.classify", text])      # → JSON a stdout
_run(["src.processing.tasks", "add", ...])   # → JSON a stdout
```

Eso da el 90 % del beneficio de un sistema de herramientas —composición,
aislamiento de fallos, testeabilidad por CLI— **sin** un orquestador
probabilístico. Si algún día se quiere exponer a un agente externo, la capa de
herramientas ya existe; solo falta el manifiesto.

### Cuándo sí valdría la pena un agente

Si el conjunto de acciones dejara de ser finito y enumerable. Hoy son ~12
comandos con sintaxis fija. El día que haya que responder preguntas abiertas
("¿qué debería hacer esta semana?") el LLM aporta; para ejecutar comandos, no.

---

## Los cuatro contratos del sistema

1. **JSON a stdout, siempre.** Todo módulo ejecutable imprime un objeto JSON
   parseable. Errores y texto humano van a stderr. Esto permite que `bot.py`
   componga sin acoplarse.

2. **La base de datos es la única fuente de verdad.** No hay estado en memoria
   entre ejecuciones. `heartbeat` reconstruye el grafo desde `tasks` cada ciclo;
   si el proceso muere, no se pierde nada.

3. **El LLM es una función pura con fallback.** Entrada acotada, salida
   validada, y si la API falla el sistema sigue funcionando con valores por
   defecto en vez de romperse.

4. **Configuración falla ruidoso.** `common.py` lanza `KeyError` si falta
   `BT_DB_HOST`. Preferimos un crash inmediato en el arranque a un default
   silencioso que escriba en la base equivocada.

---

## Capacidades actuales

Los requerimientos originales (`REQ-T1..T12` del port standalone) quedaron
obsoletos: varios se implementaron con otra solución, y aparecieron capacidades
que no estaban en la lista (embeddings, co-ocurrencia, health score, geofencing
en schema). Esta es la matriz vigente.

| Capacidad | Módulo | Estado |
|---|---|---|
| Ingesta por CLI | `ingest/cli.py` | ✅ |
| Ingesta por app Android | `android/` → `api/server.py` | ✅ |
| Ingesta por foto de pizarra | `bot.py` → `ocr.py` → `vision_diff.py` | ✅ |
| Ingesta por audio | `bot.py` → `shared/transcribe.py` | ✅ |
| Ingesta por CLI | `ingest/cli.py` | ✅ |
| Clasificación proyecto + prioridad | `processing/classify.py` | ✅ |
| Estimación anclada a horas reales | `classify.py` + `graph.cluster_stats_for_task` | ✅ |
| Embeddings 768d (Ollama) | `knowledge/embeddings.py` | ✅ |
| Linking semántico top-5 | `graph.rebuild_semantic_links` | ✅ |
| Co-ocurrencia conductual (HeLa-Mem) | `knowledge/co_occurrence.py` | ✅ |
| Comunidades + intervalos de confianza | `graph.detect_communities` | ✅ |
| Sesgo de planificación por proyecto | `graph.planning_bias_by_project` | ✅ |
| Consolidación nocturna | `graph.consolidate_sleep` | ✅ |
| Health score (CogniFold) | `graph.structural_debt_report` | ✅ |
| Detección de recordatorios (24 h) | `heartbeat --action reminders` | ✅ |
| Export a Obsidian | `shared/export_md.py` | ✅ |
| Búsqueda semántica | `bot.py` → `/search` | ✅ |
| Tareas relacionadas | `bot.py` → `/relacionadas` | ✅ |
| Geofencing | columnas en `db/schema.sql` | ⚠️ solo almacenamiento, sin disparador |
| Entrega push de recordatorios | `heartbeat` imprime a stderr | ⚠️ requiere cron/systemd que lea esa salida |

El ciclo completo de 6 capas lo ejecuta `heartbeat --action graph` (llama a
`graph.run_full_cycle`). `--action sleep` agrega la consolidación, y `--action
all` la incluye una sola vez al día a la hora de `HEARTBEAT_SLEEP_HOUR`
(default 3). Requiere `numpy` y `scipy` — declarados en `requirements.txt`;
sin `scipy`, la Capa 3 falla en cuanto hay ≥3 tareas enlazadas.

---

## Deuda técnica conocida

| Ítem | Impacto |
|---|---|
| Geofencing sin lógica de disparo | Las columnas existen pero nada las consulta |
| Recordatorios sin entrega | `heartbeat` los imprime; falta que la app los consulte |
| Intérprete en 3.12.3 (Ubuntu) | Ver *Postura de seguridad*: falta el bloqueo de CA que llega en 3.12.16 |

Resuelto (2026-10-26): `.venv` recreado desde cero con `python3 -m venv`;
rutas del `README.md` (`src/ingest/cli.py`, `src/ingest/bot.py`, contenedor
`taskmanager_pg`) corregidas.

---

## Postura de seguridad

El entorno no se actualiza "a la última versión" a ciegas: se actualiza lo que
corrige algo y se documenta lo que queda abierto.

### Baseline actual

| Componente | Versión | Estado |
|---|---|---|
| Ubuntu | 24.04.4 LTS (WSL2) | 78 paquetes al día (28 de seguridad) |
| Python (intérprete) | 3.12.3 `ubuntu0.17` | soportado hasta 2028-10; falta backport de CVE-2026-115557 |
| pip (venv) | 26.2.2 | al día, con `cert` fijado al bundle del sistema |
| certifi | 2026.10.23 | sin la CA emSign |
| `filelock` | 4.2.4 | por encima del parche (4.2.1) |
| `virtualenv` | no instalado | inmune a los 36 hallazgos de oct-2026 |
| Node.js | 24.22.1 | al día (línea LTS 24.x) |
| `ca-certificates` | `20260816` | root emSign eliminado del bundle |

### Decisiones

1. **No se instala Python 3.15.2 ni se compila 3.12.16.** Se usa el intérprete
   de Ubuntu y se depende de sus backports. Razón: 3.12 tiene soporte hasta
   2028 y mezclar intérpretes rompe el supuesto de despliegue (contenedor
   `python:3.12`).

2. **`pip` se ancla al bundle del sistema.** Su `certifi` vendorizado
   (`2026.10.19`) todavía incluía el root de emSign. Mitigación aplicada en
   `.venv/pip.conf`:

   ```ini
   [global]
   cert = /etc/ssl/certs/ca-certificates.crt
   ```

   Ese bundle ya no contiene la CA comprometida (*4 added, 5 removed* durante
   el upgrade). `common.py` ya usaba ese mismo `cafile` para Gemini/DeepSeek,
   así que las dos rutas TLS del proyecto quedan cubiertas.

3. **`pip-audit` como verificación, no como gate.** `pip-audit` sobre el venv:
   *No known vulnerabilities found*. Se corre a demanda porque un gate en CI
   sobre un proyecto de un solo desarrollador genera ruido más que valor.

4. **Auditoría del intérprete diferida, no ignorada.** Cuando Ubuntu publique
   `python3.12 ubuntu0.18` (o python-build-standalone compilado 3.12.16, que
   aún no existe en uv), `apt full-upgrade` cierra el último ítem sin migrar
   nada.
