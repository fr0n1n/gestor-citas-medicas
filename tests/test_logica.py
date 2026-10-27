"""Pruebas de la logica de dominio.

Solo usan la biblioteca estandar, asi que corren sin instalar nada:

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.enums import EstadoEvento
from app.enums import EstadoTransporte
from app.logica import (
    Urgencia,
    falta_pedir_ambulancia,
    toca_confirmar_ambulancia,
    aplicar_cambio_estado,
    clave_orden_agenda,
    dias_esperando,
    en_horizonte,
    fecha_limite_requisito,
    mes_anterior,
    mes_siguiente,
    rejilla_mes,
    requiere_atencion,
    toca_reclamar,
    transicion_valida,
    urgencia,
)

HOY = date(2026, 3, 17)


class TestFechaLimiteRequisito(unittest.TestCase):
    def test_resta_la_antelacion_a_la_fecha_de_la_cita(self):
        # "Analitica 15 dias antes" de una cita el 20 de marzo.
        self.assertEqual(
            fecha_limite_requisito(date(2026, 3, 20), 15),
            date(2026, 3, 5),
        )

    def test_cruza_el_cambio_de_mes(self):
        self.assertEqual(
            fecha_limite_requisito(date(2026, 3, 10), 15),
            date(2026, 2, 23),
        )

    def test_sin_fecha_de_cita_no_hay_fecha_limite(self):
        # El caso importante: cita solicitada esperando llamada.
        self.assertIsNone(fecha_limite_requisito(None, 15))

    def test_sin_antelacion_no_hay_fecha_limite(self):
        self.assertIsNone(fecha_limite_requisito(date(2026, 3, 20), None))

    def test_la_fecha_manual_tiene_prioridad(self):
        self.assertEqual(
            fecha_limite_requisito(date(2026, 3, 20), 15, date(2026, 3, 1)),
            date(2026, 3, 1),
        )

    def test_la_fecha_manual_vale_aunque_la_cita_no_tenga_fecha(self):
        self.assertEqual(
            fecha_limite_requisito(None, None, date(2026, 3, 1)),
            date(2026, 3, 1),
        )

    def test_antelacion_cero_es_el_mismo_dia(self):
        self.assertEqual(
            fecha_limite_requisito(date(2026, 3, 20), 0),
            date(2026, 3, 20),
        )


class TestUrgencia(unittest.TestCase):
    def test_clasificacion(self):
        casos = [
            (None, Urgencia.SIN_FECHA),
            (date(2026, 3, 16), Urgencia.VENCIDO),
            (date(2026, 3, 17), Urgencia.HOY),
            (date(2026, 3, 20), Urgencia.PROXIMO),
            (date(2026, 3, 24), Urgencia.PROXIMO),  # justo en el limite
            (date(2026, 3, 25), Urgencia.FUTURO),
        ]
        for fecha, esperado in casos:
            with self.subTest(fecha=fecha):
                self.assertEqual(urgencia(fecha, HOY, dias_aviso=7), esperado)

    def test_requiere_atencion_ignora_lo_ya_hecho(self):
        self.assertFalse(requiere_atencion(date(2026, 3, 1), True, HOY))

    def test_requiere_atencion_avisa_de_lo_vencido(self):
        self.assertTrue(requiere_atencion(date(2026, 3, 1), False, HOY))

    def test_requiere_atencion_ignora_lo_lejano(self):
        self.assertFalse(requiere_atencion(date(2026, 6, 1), False, HOY))

    def test_requiere_atencion_ignora_lo_que_no_tiene_fecha(self):
        # Un requisito de una cita sin fecha no puede vencer todavia.
        self.assertFalse(requiere_atencion(None, False, HOY))


class TestSalaDeEspera(unittest.TestCase):
    def test_cuenta_los_dias_de_espera(self):
        self.assertEqual(dias_esperando(date(2026, 1, 1), HOY), 75)

    def test_sin_fecha_de_solicitud_no_se_puede_contar(self):
        self.assertIsNone(dias_esperando(None, HOY))

    def test_una_solicitud_futura_no_da_dias_negativos(self):
        self.assertEqual(dias_esperando(date(2026, 4, 1), HOY), 0)

    def test_reclama_tras_el_umbral(self):
        self.assertTrue(
            toca_reclamar(
                EstadoEvento.SOLICITADA, date(2026, 1, 1), HOY, dias_alerta=30
            )
        )

    def test_no_reclama_si_se_pidio_hace_poco(self):
        self.assertFalse(
            toca_reclamar(
                EstadoEvento.SOLICITADA, date(2026, 3, 10), HOY, dias_alerta=30
            )
        )

    def test_no_reclama_una_cita_ya_confirmada(self):
        self.assertFalse(
            toca_reclamar(EstadoEvento.CONFIRMADA, date(2026, 1, 1), HOY)
        )

    def test_reclama_si_no_sabemos_cuando_se_pidio(self):
        # Preferimos un aviso de mas a perder la cita de vista.
        self.assertTrue(toca_reclamar(EstadoEvento.SOLICITADA, None, HOY))


class TestAmbulancia(unittest.TestCase):
    def test_avisa_cuando_se_acerca_y_sigue_sin_pedir(self):
        self.assertTrue(
            falta_pedir_ambulancia(EstadoTransporte.PENDIENTE, date(2026, 3, 20), HOY, 7)
        )

    def test_avisa_el_mismo_dia_de_la_cita(self):
        self.assertTrue(
            falta_pedir_ambulancia(EstadoTransporte.PENDIENTE, HOY, HOY, 7)
        )

    def test_no_avisa_si_la_cita_esta_lejos(self):
        self.assertFalse(
            falta_pedir_ambulancia(EstadoTransporte.PENDIENTE, date(2026, 5, 1), HOY, 7)
        )

    def test_no_avisa_si_la_cita_ya_paso(self):
        self.assertFalse(
            falta_pedir_ambulancia(EstadoTransporte.PENDIENTE, date(2026, 3, 16), HOY, 7)
        )

    def test_no_avisa_sin_fecha(self):
        # Sin dia asignado no se puede pedir la ambulancia todavia.
        self.assertFalse(
            falta_pedir_ambulancia(EstadoTransporte.PENDIENTE, None, HOY, 7)
        )

    def test_no_avisa_si_ya_esta_pedida_o_no_hace_falta(self):
        for estado in (
            EstadoTransporte.SOLICITADO,
            EstadoTransporte.CONFIRMADO,
            EstadoTransporte.NO_NECESITA,
        ):
            with self.subTest(estado=estado):
                self.assertFalse(
                    falta_pedir_ambulancia(estado, date(2026, 3, 20), HOY, 7)
                )


class TestConfirmarAmbulancia(unittest.TestCase):
    def test_recuerda_confirmar_el_dia_antes(self):
        self.assertTrue(
            toca_confirmar_ambulancia(EstadoTransporte.SOLICITADO, date(2026, 3, 18), HOY, 1)
        )

    def test_y_tambien_el_mismo_dia(self):
        self.assertTrue(
            toca_confirmar_ambulancia(EstadoTransporte.SOLICITADO, HOY, HOY, 1)
        )

    def test_no_antes_de_tiempo(self):
        self.assertFalse(
            toca_confirmar_ambulancia(EstadoTransporte.SOLICITADO, date(2026, 3, 25), HOY, 1)
        )

    def test_solo_si_esta_pedida_pero_sin_confirmar(self):
        for estado in (
            EstadoTransporte.PENDIENTE,
            EstadoTransporte.CONFIRMADO,
            EstadoTransporte.NO_NECESITA,
        ):
            with self.subTest(estado=estado):
                self.assertFalse(
                    toca_confirmar_ambulancia(estado, date(2026, 3, 18), HOY, 1)
                )


class TestOrdenAgenda(unittest.TestCase):
    def test_las_citas_sin_fecha_van_al_final(self):
        fechas = [date(2026, 5, 1), None, date(2026, 1, 1), None]
        ordenadas = sorted(fechas, key=clave_orden_agenda)
        self.assertEqual(
            ordenadas, [date(2026, 1, 1), date(2026, 5, 1), None, None]
        )

    def test_horizonte(self):
        self.assertTrue(en_horizonte(date(2026, 3, 20), HOY, 14))
        self.assertTrue(en_horizonte(HOY, HOY, 14))
        self.assertTrue(en_horizonte(date(2026, 3, 31), HOY, 14))
        self.assertFalse(en_horizonte(date(2026, 4, 1), HOY, 14))
        self.assertFalse(en_horizonte(date(2026, 3, 16), HOY, 14))
        self.assertFalse(en_horizonte(None, HOY, 14))


class TestCalendario(unittest.TestCase):
    def test_semanas_completas_que_empiezan_en_lunes(self):
        semanas = rejilla_mes(2026, 3)
        for semana in semanas:
            self.assertEqual(len(semana), 7)
            self.assertEqual(semana[0].weekday(), 0)  # lunes
            self.assertEqual(semana[6].weekday(), 6)  # domingo

    def test_contiene_todos_los_dias_del_mes(self):
        dias = {d for semana in rejilla_mes(2026, 3) for d in semana}
        self.assertIn(date(2026, 3, 1), dias)
        self.assertIn(date(2026, 3, 31), dias)

    def test_febrero_bisiesto(self):
        dias = {d for semana in rejilla_mes(2024, 2) for d in semana}
        self.assertIn(date(2024, 2, 29), dias)

    def test_navegacion_entre_meses(self):
        self.assertEqual(mes_anterior(2026, 1), (2025, 12))
        self.assertEqual(mes_anterior(2026, 3), (2026, 2))
        self.assertEqual(mes_siguiente(2026, 12), (2027, 1))
        self.assertEqual(mes_siguiente(2026, 3), (2026, 4))


class TestTransiciones(unittest.TestCase):
    def test_camino_normal(self):
        self.assertTrue(
            transicion_valida(
                EstadoEvento.POR_SOLICITAR, EstadoEvento.SOLICITADA
            )
        )
        self.assertTrue(
            transicion_valida(EstadoEvento.SOLICITADA, EstadoEvento.CONFIRMADA)
        )
        self.assertTrue(
            transicion_valida(EstadoEvento.CONFIRMADA, EstadoEvento.REALIZADA)
        )

    def test_no_se_puede_realizar_lo_que_no_se_ha_pedido(self):
        self.assertFalse(
            transicion_valida(
                EstadoEvento.POR_SOLICITAR, EstadoEvento.REALIZADA
            )
        )

    def test_quedarse_igual_siempre_vale(self):
        for estado in EstadoEvento:
            with self.subTest(estado=estado):
                self.assertTrue(transicion_valida(estado, estado))


class TestAplicarCambioEstado(unittest.TestCase):
    def test_al_solicitar_se_anota_la_fecha_y_se_borra_la_de_la_cita(self):
        r = aplicar_cambio_estado(
            EstadoEvento.POR_SOLICITAR,
            EstadoEvento.SOLICITADA,
            fecha=date(2026, 4, 1),
            solicitada_en=None,
            hoy=HOY,
        )
        self.assertEqual(r.solicitada_en, HOY)
        self.assertIsNone(r.fecha)

    def test_al_solicitar_no_se_pisa_una_fecha_de_solicitud_existente(self):
        r = aplicar_cambio_estado(
            EstadoEvento.CONFIRMADA,
            EstadoEvento.SOLICITADA,
            fecha=date(2026, 4, 1),
            solicitada_en=date(2026, 1, 5),
            hoy=HOY,
        )
        self.assertEqual(r.solicitada_en, date(2026, 1, 5))

    def test_confirmar_con_fecha_no_avisa(self):
        r = aplicar_cambio_estado(
            EstadoEvento.SOLICITADA,
            EstadoEvento.CONFIRMADA,
            fecha=date(2026, 4, 1),
            solicitada_en=date(2026, 1, 5),
            hoy=HOY,
        )
        self.assertIsNone(r.aviso)
        self.assertEqual(r.fecha, date(2026, 4, 1))

    def test_confirmar_sin_fecha_avisa(self):
        r = aplicar_cambio_estado(
            EstadoEvento.SOLICITADA,
            EstadoEvento.CONFIRMADA,
            fecha=None,
            solicitada_en=date(2026, 1, 5),
            hoy=HOY,
        )
        self.assertIsNotNone(r.aviso)

    def test_aplazar_borra_la_fecha(self):
        r = aplicar_cambio_estado(
            EstadoEvento.CONFIRMADA,
            EstadoEvento.APLAZADA,
            fecha=date(2026, 4, 1),
            solicitada_en=None,
            hoy=HOY,
        )
        self.assertIsNone(r.fecha)
        self.assertIsNotNone(r.aviso)

    def test_una_transicion_imposible_falla(self):
        with self.assertRaises(ValueError):
            aplicar_cambio_estado(
                EstadoEvento.POR_SOLICITAR,
                EstadoEvento.REALIZADA,
                fecha=None,
                solicitada_en=None,
                hoy=HOY,
            )


class TestNombreDia(unittest.TestCase):
    """Los rotulos de cada jornada en la pantalla de citas."""

    def test_cada_dia_de_una_semana(self):
        from app.logica import nombre_dia

        lunes = date(2026, 9, 21)
        esperados = [
            "lunes", "martes", "miércoles", "jueves",
            "viernes", "sábado", "domingo",
        ]
        for i, esperado in enumerate(esperados):
            with self.subTest(dia=esperado):
                self.assertEqual(nombre_dia(lunes + timedelta(days=i)), esperado)

    def test_hay_uno_por_cada_dia_de_la_semana(self):
        from app.logica import DIAS_SEMANA, DIAS_SEMANA_LARGOS

        self.assertEqual(len(DIAS_SEMANA_LARGOS), len(DIAS_SEMANA))


class TestCrearIaCiclo(unittest.TestCase):
    """Enlazar dos citas no puede cerrar un bucle."""

    def setUp(self):
        from app.logica import crearia_ciclo

        self.comprueba = crearia_ciclo
        # 1 -> 2 -> 3 (de la consulta 1 sale la prueba 2, y de ella la 3)
        self.padres = {1: None, 2: 1, 3: 2, 9: None}

    def test_una_cita_no_puede_salir_de_si_misma(self):
        self.assertTrue(self.comprueba(1, 1, self.padres))

    def test_no_puede_salir_de_su_propia_descendiente(self):
        self.assertTrue(self.comprueba(1, 3, self.padres))
        self.assertTrue(self.comprueba(2, 3, self.padres))

    def test_enlaces_validos(self):
        self.assertFalse(self.comprueba(9, 3, self.padres))
        self.assertFalse(self.comprueba(3, 9, self.padres))

    def test_aguanta_un_bucle_ya_existente_en_los_datos(self):
        # Si algo dejo un bucle, la comprobacion debe terminar igualmente.
        rotos = {1: 2, 2: 1}
        self.assertTrue(self.comprueba(1, 2, rotos))


class TestHilosDe(unittest.TestCase):
    """Agrupar las citas en hilos para la vista de historia."""

    def setUp(self):
        from app.logica import hilos_de

        self.hilos = hilos_de

    def test_una_consulta_con_sus_dos_pruebas(self):
        # 1 es la consulta; 2 y 3 salen de ella; 4 sale de 2.
        padres = {1: None, 2: 1, 3: 1, 4: 2}
        self.assertEqual(
            self.hilos(padres, [1, 2, 3, 4]),
            [[(1, 0), (2, 1), (4, 2), (3, 1)]],
        )

    def test_las_citas_sueltas_son_hilos_de_una_sola(self):
        padres = {7: None, 8: None}
        self.assertEqual(self.hilos(padres, [7, 8]), [[(7, 0)], [(8, 0)]])

    def test_el_orden_de_entrada_manda(self):
        padres = {1: None, 2: 1, 3: 1}
        self.assertEqual(
            self.hilos(padres, [1, 3, 2]), [[(1, 0), (3, 1), (2, 1)]]
        )

    def test_un_padre_que_no_esta_no_esconde_la_rama(self):
        # La cita 5 sale de una que ya no existe: debe verse igualmente.
        self.assertEqual(self.hilos({5: 99}, [5]), [[(5, 0)]])

    def test_un_bucle_en_los_datos_no_cuelga(self):
        padres = {1: 2, 2: 1, 3: None}
        hilos = self.hilos(padres, [1, 2, 3])
        # El bucle no tiene raiz, asi que solo sale el hilo suelto.
        self.assertEqual(hilos, [[(3, 0)]])

    def test_sin_citas(self):
        self.assertEqual(self.hilos({}, []), [])


if __name__ == "__main__":
    unittest.main()


class TestAntelacionAlMover(unittest.TestCase):
    """Al mover un preparativo, la fecha fija se vuelve antelacion."""

    def setUp(self):
        from app.logica import antelacion_al_mover

        self.antelacion = antelacion_al_mover

    def test_el_mismo_dia_de_la_cita(self):
        dia = date(2026, 10, 6)
        self.assertEqual(self.antelacion(dia, dia), 0)

    def test_quince_dias_antes(self):
        self.assertEqual(
            self.antelacion(date(2026, 9, 21), date(2026, 10, 6)), 15
        )

    def test_sin_fecha_fija_no_se_toca_nada(self):
        self.assertIsNone(self.antelacion(None, date(2026, 10, 6)))

    def test_una_cita_sin_fecha_no_permite_calcularlo(self):
        self.assertIsNone(self.antelacion(date(2026, 10, 6), None))

    def test_una_fecha_posterior_a_la_cita_no_es_antelacion(self):
        # No tiene sentido "hacerlo 3 dias despues de la cita": se deja igual.
        self.assertIsNone(
            self.antelacion(date(2026, 10, 9), date(2026, 10, 6))
        )


class TestTramoDe(unittest.TestCase):
    """Los tramos de la portada: hoy, manana, esta semana..."""

    def setUp(self):
        from app.logica import tramo_de

        self.tramo = tramo_de
        # Un miercoles, para que "esta semana" y "la que viene" se distingan.
        self.miercoles = date(2026, 9, 23)

    def tramo_en(self, dias):
        return self.tramo(self.miercoles + timedelta(days=dias), self.miercoles)

    def test_hoy_y_manana(self):
        self.assertEqual(self.tramo_en(0), "hoy")
        self.assertEqual(self.tramo_en(1), "manana")

    def test_esta_semana_acaba_el_domingo(self):
        for dias in (2, 3, 4):
            with self.subTest(dias=dias):
                self.assertEqual(self.tramo_en(dias), "esta_semana")
        # El lunes ya es la semana que viene, aunque sean solo cinco dias.
        self.assertEqual(self.tramo_en(5), "semana_siguiente")

    def test_las_semanas_siguientes(self):
        self.assertEqual(self.tramo_en(11), "semana_siguiente")
        self.assertEqual(self.tramo_en(12), "dos_semanas")
        self.assertEqual(self.tramo_en(18), "dos_semanas")
        self.assertEqual(self.tramo_en(19), "cuatro_semanas")
        self.assertEqual(self.tramo_en(32), "cuatro_semanas")

    def test_lo_pasado_y_lo_muy_lejano_quedan_fuera(self):
        self.assertIsNone(self.tramo_en(-1))
        self.assertIsNone(self.tramo_en(33))

    def test_un_domingo_no_tiene_esta_semana(self):
        domingo = date(2026, 9, 27)
        self.assertEqual(self.tramo(domingo + timedelta(days=1), domingo), "manana")
        self.assertEqual(
            self.tramo(domingo + timedelta(days=3), domingo), "semana_siguiente"
        )

    def test_el_horizonte_cubre_todos_los_tramos(self):
        from app.logica import fin_del_horizonte

        # Ninguna fecha dentro del horizonte puede quedarse sin tramo: si
        # pasara, la portada traeria citas que no se pintan en ningun sitio.
        for arranque in (date(2026, 9, 21), date(2026, 9, 27), date(2026, 2, 26)):
            fin = fin_del_horizonte(arranque)
            dia = arranque
            while dia <= fin:
                with self.subTest(arranque=arranque, dia=dia):
                    self.assertIsNotNone(self.tramo(dia, arranque))
                dia += timedelta(days=1)


class TestYaPaso(unittest.TestCase):
    """Cuando se da una cita por pasada."""

    def setUp(self):
        from app.logica import ya_paso
        from datetime import datetime

        self.paso = ya_paso
        self.dt = datetime

    def test_con_hora_se_espera_a_que_termine(self):
        cita = date(2026, 9, 25)
        from datetime import time as hora_t

        # Cita a las 10:30 que dura media hora.
        argumentos = (cita, hora_t(10, 30), 30)
        self.assertFalse(self.paso(*argumentos, self.dt(2026, 9, 25, 10, 31)))
        self.assertFalse(self.paso(*argumentos, self.dt(2026, 9, 25, 11, 0)))
        self.assertTrue(self.paso(*argumentos, self.dt(2026, 9, 25, 11, 1)))

    def test_sin_hora_cuenta_el_dia_entero(self):
        cita = date(2026, 9, 25)
        self.assertFalse(self.paso(cita, None, 30, self.dt(2026, 9, 25, 23, 59)))
        self.assertTrue(self.paso(cita, None, 30, self.dt(2026, 9, 26, 0, 1)))

    def test_una_cita_futura_no_ha_pasado(self):
        from datetime import time as hora_t

        self.assertFalse(
            self.paso(date(2026, 10, 6), hora_t(9, 59), 30, self.dt(2026, 9, 25, 12, 0))
        )

    def test_sin_fecha_nunca_pasa(self):
        self.assertFalse(self.paso(None, None, 30, self.dt(2026, 9, 25, 12, 0)))


class TestTelefonoAmbulancia(unittest.TestCase):
    """De la agenda, a cual se llama para pedir la ambulancia."""

    def setUp(self):
        from app.logica import elegir_telefono_ambulancia

        self.elegir = elegir_telefono_ambulancia
        # Como acaba una agenda de verdad: varios numeros apuntados como
        # transporte que no sirven para pedir la ambulancia.
        self.agenda = [
            ("Citas Hospital Costa Norte (fax)", "900 11 11 11"),
            ("Incidencias transporte sanitario", "900 22 22 22"),
            ("Admisión Centro de Especialidades", "900 33 33 33"),
            ("Ambulancias", "900 00 00 00"),
        ]

    def test_elige_el_de_pedir_la_ambulancia(self):
        self.assertEqual(self.elegir(self.agenda), "900 00 00 00")

    def test_nunca_un_fax_ni_una_linea_de_incidencias(self):
        solo_malos = self.agenda[:3]
        self.assertIsNone(self.elegir(solo_malos))

    def test_si_no_se_llama_ambulancia_vale_el_primero_util(self):
        self.assertEqual(
            self.elegir([("Transporte sanitario Villamar", "900 44 44 44")]),
            "900 44 44 44",
        )

    def test_sin_agenda(self):
        self.assertIsNone(self.elegir([]))
        self.assertIsNone(self.elegir([("Ambulancias", "")]))


class TestUrgeReclamarPrevia(unittest.TestCase):
    """Reclamar una prueba mirando el tiempo que queda, no los dias pedida."""

    def setUp(self):
        from app.logica import urge_reclamar_previa

        self.urge = urge_reclamar_previa
        self.hoy = date(2026, 9, 30)

    def test_todavia_hay_margen(self):
        # La cita es el 20/10: quedan 20 dias, mas que los 15 de aviso.
        self.assertFalse(self.urge(date(2026, 10, 20), self.hoy, 15))

    def test_cuando_se_acerca_salta(self):
        self.assertTrue(self.urge(date(2026, 10, 15), self.hoy, 15))
        self.assertTrue(self.urge(date(2026, 10, 2), self.hoy, 15))

    def test_sigue_urgiendo_aunque_la_cita_ya_haya_pasado(self):
        # Que se pasara la fecha no arregla nada.
        self.assertTrue(self.urge(date(2026, 9, 20), self.hoy, 15))

    def test_sin_cita_objetivo_no_urge_nada(self):
        self.assertFalse(self.urge(None, self.hoy, 15))
