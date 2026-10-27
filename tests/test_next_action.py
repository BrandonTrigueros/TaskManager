#!/usr/bin/env python3
"""Tests del núcleo de decisión (M1) — sin base de datos.

Se pueden correr de dos formas:
    python3 tests/test_next_action.py
    pytest tests/test_next_action.py
"""

import os
import sys

# `src.common` construye el DSN al importarse: sin estas variables el import
# falla en un entorno limpio (CI). No se abre ninguna conexión.
for _var, _default in (
    ("BT_DB_HOST", "localhost"),
    ("BT_DB_PORT", "5432"),
    ("POSTGRES_USER", "test"),
    ("POSTGRES_PASSWORD", "test"),
    ("POSTGRES_DB", "test"),
):
    os.environ.setdefault(_var, _default)

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.processing.next_action import (  # noqa: E402
    DEEP_MIN_HOURS,
    NEUTRAL_EXPECTANCY,
    NEUTRAL_HORIZON_DAYS,
    OVERDUE_BOOST,
    QUICK_MAX_HOURS,
    deep_score,
    expectancy_from_stats,
    overdue_factor,
    quick_weight,
    score,
    slot_for,
)

TOL = 0.005


def _close(actual: float, expected: float) -> bool:
    return abs(actual - expected) < TOL


# ═══════════════════════════════════════════════════════════════
#  score()
# ═══════════════════════════════════════════════════════════════

def test_sin_vencimiento_usa_horizonte_neutro():
    # 0.8 × 0.8 = 0.64 ; 1 + 1×(15/30) = 1.5
    assert _close(score(0.8, 0.8, None), 0.4267)


def test_vence_hoy_no_penaliza():
    assert _close(score(0.8, 0.8, 0.0), 0.64)


def test_vencida_recibe_bonus():
    # 0.64 × (1 + 0.5·e^(-3/10)) = 0.8771
    assert _close(score(0.8, 0.8, -3.0), 0.8771)


def test_horizonte_lejano_se_satura():
    # 30 días y 300 días deben dar lo mismo (techo de 30)
    assert _close(score(0.8, 0.8, 30), score(0.8, 0.8, 300))


def test_orden_esperado_entre_vencimientos():
    vencida = score(0.8, 0.8, -1)
    hoy = score(0.8, 0.8, 0)
    sin_fecha = score(0.8, 0.8, None)
    lejana = score(0.8, 0.8, 30)
    assert vencida > hoy > sin_fecha > lejana


def test_impulsividad_cero_ignora_las_fechas():
    assert _close(score(0.8, 0.8, 30, impulsivity=0.0), 0.64)


def test_clamp_de_entradas():
    assert score(1.5, 1.5, 0) == score(1.0, 1.0, 0)
    assert score(-0.5, 0.5, 0) == 0.0


def test_expectativa_cero_anula_el_score():
    assert score(0.0, 1.0, 0) == 0.0


def test_prioridad_baja_queda_abajo():
    alta = score(0.6, 5 / 5, 5)
    baja = score(0.6, 1 / 5, 5)
    assert alta > baja


# ═══════════════════════════════════════════════════════════════
#  expectancy_from_stats()
# ═══════════════════════════════════════════════════════════════

def test_sin_historial_usa_prior_neutro():
    assert expectancy_from_stats(None) == NEUTRAL_EXPECTANCY


def test_cluster_sin_ratio_usa_prior_neutro():
    assert expectancy_from_stats({"size": 4}) == NEUTRAL_EXPECTANCY


def test_calibracion_perfecta_da_expectativa_maxima():
    assert expectancy_from_stats({"planning_ratio": 1.0}) == 1.0


def test_sobreestimar_la_mitad_baja_la_expectativa():
    # ratio 2.0 → 1/(1+1) = 0.5
    assert _close(expectancy_from_stats({"planning_ratio": 2.0}), 0.5)


def test_subestimar_tambien_penaliza_simetrico():
    assert _close(
        expectancy_from_stats({"planning_ratio": 2.0}),
        expectancy_from_stats({"planning_ratio": 0.0}),
    )


def test_ratio_invalido_no_rompe():
    assert expectancy_from_stats({"planning_ratio": "n/a"}) == NEUTRAL_EXPECTANCY


# ═══════════════════════════════════════════════════════════════
#  v1 — vencimiento decreciente y dos slots
# ═══════════════════════════════════════════════════════════════

def test_bonus_por_vencimiento_decae_con_la_edad():
    assert overdue_factor(0) == 1.0
    assert overdue_factor(-1) > overdue_factor(-10)
    assert overdue_factor(-10) > overdue_factor(-60)


def test_bonus_por_vencimiento_nunca_baja_de_uno():
    # tiende a 1.0 (nunca penaliza por vieja); con atrasos enormes exp() → 0
    assert overdue_factor(-9999) >= 1.0
    assert overdue_factor(-9999) < 1.01


def test_vencida_muy_vieja_no_supera_a_una_de_ayer():
    assert score(0.8, 0.8, -1) > score(0.8, 0.8, -40)


def test_bonus_tope_en_el_dia_cero():
    assert _close(overdue_factor(-0.001), OVERDUE_BOOST)


def test_slot_corto_es_quick():
    assert slot_for(0.25) == "quick"
    assert slot_for(QUICK_MAX_HOURS) == "quick"


def test_slot_largo_es_deep():
    assert slot_for(DEEP_MIN_HOURS) == "deep"
    assert slot_for(6.2) == "deep"


def test_slot_sin_estimacion_es_quick():
    assert slot_for(None) == "quick"


def test_slot_intermedio_queda_en_quick():
    # 0.75 < h < 1.5: no cabe en un hueco chico ni justifica un bloque
    assert slot_for(1.0) == "quick"


def test_quick_weight_premia_lo_corto():
    assert quick_weight(0.25) > quick_weight(0.75)
    assert quick_weight(None) == quick_weight(0.25)


def test_quick_weight_acotado():
    assert 1.0 <= quick_weight(QUICK_MAX_HOURS) <= 1.01
    assert quick_weight(0.05) < 1.6


def test_deep_score_atenua_la_expectativa():
    # una tarea evitada (expectancy 0.2) puntúa por encima del score puro
    assert deep_score(0.2, 0.8, 5) > score(0.2, 0.8, 5)


def test_deep_score_no_anula_lo_evitado():
    # expectativa 0 no lleva el score a 0: lo importante y evitado se propone
    assert deep_score(0.0, 0.8, 0) == 0.4


def test_deep_premia_importancia_sobre_expectativa():
    assert deep_score(0.5, 1.0, 5) > deep_score(1.0, 0.6, 5)


# ═══════════════════════════════════════════════════════════════
#  Runner sin pytest
# ═══════════════════════════════════════════════════════════════

def _run_all() -> int:
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✅ {name}")
        except AssertionError as e:
            failed += 1
            print(f"  ❌ {name}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests OK")
    print(f"NEUTRAL_HORIZON_DAYS = {NEUTRAL_HORIZON_DAYS}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
