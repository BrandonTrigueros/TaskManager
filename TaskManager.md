## PARTE 1: TaskManager (El Cerebro Operativo)

### 1.1. Módulo de Ingesta (Input Layer)

**REQ-T1 (Multi-source):** Webhook persistente para recibir:

- **Telegram:** Texto, audio (transcripción) y fotos (OCR).
- **Local CLI:** Envío rápido desde la terminal de Linux con comando.

**REQ-T2 (OCR de Pizarras/Cuadernos):** Integración con modelo de visión para extraer tareas de fotos de la pizarra del cuarto o libretas de la UCR.

**REQ-T3 (Transcripción de Audio):** Integración con modelo de voz a texto para convertir mensajes de voz en Telegram en tareas escritas.

### 1.2. Procesamiento e Inteligencia (Logic Layer)

**REQ-T4 (Diferenciación de Cambios):** La IA debe ser capaz de detectar cambios entre envíos sucesivos de la misma hoja.
Es probable que yo mande una hoja con 5 tareas escritas a mano y el dia siguiente mande la misma hoja pero con una tarea tachada y una nueva agregada. La IA debe saber que la tarea tachada ya no es no es relevante o fue completada, y que la nueva tarea es una adición. Además de no agregar tareas repetidas cada vez que mando la misma hoja.

**REQ-T5 (Linking de Tareas):** La IA debe detectar si una tarea nueva tiene palabras clave o contexto similar a tareas existentes, la IA debe crear un "link" entre ellas (ej. "Esta tarea parece relacionada con 'Actualizar firmware X220', ¿querés vincularlas?"). Se puede crear un grafo de tareas relacionadas para facilitar la navegación y gestión de proyectos complejos. Clusters visibles en un grafo de tareas relacionadas pueden ser una señal para la IA de que hay un proyecto en marcha, lo que puede activar la categorización automática por proyecto (REQ-T5). Por ejemplo, si detecta varias tareas relacionadas con "X220", podría sugerir categorizarlas bajo un proyecto común llamado "Mantenimiento X220". Esto ayuda a mantener el sistema organizado y a identificar áreas de enfoque sin necesidad de etiquetado manual.

**REQ-T6 (Categorización Latente):** Clasificación automática por proyecto (ej. "Lab 2" → Empotrados; "Correcciones al paper" → Computer Vision; "HPE" → Trabajo). Multiples tareas linkeadas pasado un umbral de similitud pueden formar un "cluster" que se categoriza como un proyecto.

**REQ-T7 (Estimación usando contexto):** La IA debe usar el contexto de tareas similares para estimar horas. Por ejemplo, si una tarea nueva es similar a una tarea anterior que tomó 3 horas, la IA puede sugerir una estimación inicial basada en esa referencia. Además, la IA puede ajustar esta estimación considerando factores adicionales como la complejidad percibida o la cantidad de subtareas relacionadas.


### 1.3. Almacenamiento y Sincronización (Storage Layer)

**REQ-T8 (Vista Maestra):** Generar un archivo `MASTER_LOG.md` actualizado a modo de dasboard principal. Este archivo debe contener lista de tareas con su ID, título, proyecto, prioridad, horas estimadas, estado y origen. Luego deben existir archivos individuales por proyecto (ej. `EMPOTRADOS.md`, `COMPUTERVISION.md`) que se actualizan automáticamente con las tareas correspondientes. Luego deben existir archivos individuales por tarea (ej. `TASK_123.md`) que contienen la descripción detallada, metadatos y un historial de cambios. Los archivos deben seguir el linking de Obsidian para que se puedan navegar las tareas como si fuera un grafo. Además, cada tarea debe tener un bloque de metadatos con su ID, proyecto, prioridad, horas estimadas, estado y origen.

**REQ-T9 (Markdown Sync):** Exportación automática de la "Vista Maestra" con todos los archivos generados (vault de Obsidian) a archivos `.md` en un repositorio local para consulta rápida en Obsidian o Vim.

**REQ-T10 (Telegram Answering):** Integración con Telegram para responder automáticamente a consultas sobre tareas y estado del sistema. Además de recordatorios de altas prioridades.

**REQ-T11 (Telegram Task Update):** Permitir que el usuario actualice el estado de una tarea (ej. marcar como completada) directamente desde Telegram, lo que a su vez actualiza el `MASTER_LOG.md` y los archivos relacionados.

**REQ-T12 (Telegram Reminders):** El sistema debe enviar recordatorios automáticos a Telegram para tareas de alta prioridad o próximas a su fecha de vencimiento.

### Flow parte 1:
1. **Ingesta:** El usuario envía una tarea por Telegram o CLI.
2. Pre-procesamiento: Si es una foto, se aplica OCR. Si es audio, se transcribe.
3. **Procesamiento:** La IA analiza el contenido, detecta cambios, sugiere vinculaciones y categoriza.
4. **Almacenamiento:** Se actualiza el `MASTER_LOG.md` y los archivos individuales por proyecto y tarea.
5. **Sincronización:** Los archivos se exportan a un repositorio local para consulta en Obsidian o Vim.
6. **Interacción:** El sistema responde a consultas en Telegram sobre el estado de las tareas y envía recordatorios de tareas de alta prioridad.
