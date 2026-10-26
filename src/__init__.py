"""BT-Core TaskManager — paquete raíz.

Declarado explícitamente (en lugar de namespace package implícito) para que
`python3 -m src.<area>.<modulo>` resuelva siempre contra este repositorio y no
pueda capturar un `src` de terceros presente en sys.path.

Cada módulo ejecutable inserta el root del proyecto en sys.path antes de
importar `src.*`; ver `_PROJECT_ROOT` en src/processing/tasks.py.
"""
