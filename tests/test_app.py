import os
import sys
from datetime import datetime, timedelta, timezone
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["STRIPE_SECRET_KEY"] = "sk_test_NOTREAL_FAKE_KEY_FOR_UNIT_TESTS_ONLY"
os.environ["HORAS_ANTES_RECORDATORIO"] = "24"
# aseguramos que no existan credenciales reales en el entorno de test -> siempre mock
os.environ.pop("WHATSAPP_PHONE_NUMBER_ID", None)
os.environ.pop("WHATSAPP_ACCESS_TOKEN", None)
os.environ["GOOGLE_CREDENTIALS_FILE"] = "no_existe_credentials.json"

import app as backend_app  # noqa: E402


@pytest.fixture()
def client():
    backend_app.app.config["TESTING"] = True
    backend_app.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    with backend_app.app.app_context():
        backend_app.db.drop_all()
        backend_app.db.create_all()
    with backend_app.app.test_client() as c:
        yield c


def test_validar_telefono():
    assert backend_app.validar_telefono("+34600000000") is True
    assert backend_app.validar_telefono("no-es-un-telefono") is False
    assert backend_app.validar_telefono("") is False


def test_crear_cita(client):
    fecha = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    r = client.post("/api/citas", json={
        "nombre_paciente": "María López", "telefono": "+34600111222", "fecha_hora": fecha,
    })
    assert r.status_code == 201
    assert r.get_json()["nombre_paciente"] == "María López"


def test_crear_cita_falla_telefono_invalido(client):
    fecha = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    r = client.post("/api/citas", json={
        "nombre_paciente": "X", "telefono": "abc", "fecha_hora": fecha,
    })
    assert r.status_code == 400


def test_crear_cita_falla_sin_campos(client):
    r = client.post("/api/citas", json={"nombre_paciente": "X"})
    assert r.status_code == 400


def test_whatsapp_client_mock_por_defecto_sin_credenciales():
    cliente = backend_app.get_whatsapp_client()
    assert isinstance(cliente, backend_app.WhatsAppClientMock)
    resultado = cliente.enviar_recordatorio("+34600000000", "Juan", "10-09-2026 10:00", 1)
    assert resultado["estado"] == "simulado_ok"
    assert "Juan" in resultado["mensaje"]


def test_calendar_client_mock_por_defecto_sin_credenciales():
    cliente = backend_app.get_calendar_client()
    assert isinstance(cliente, backend_app.CalendarClientMock)


def test_sincronizar_calendario_con_mock_inyectado(client, monkeypatch):
    eventos_demo = [{
        "id": "evt1", "titulo": "Sesión terapia", "nombre_paciente": "Ana",
        "inicio": (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat(),
        "telefono": "+34611222333",
    }]
    monkeypatch.setattr(backend_app, "get_calendar_client",
                         lambda: backend_app.CalendarClientMock(eventos_demo))
    r = client.post("/api/citas/sincronizar")
    assert r.status_code == 200
    assert r.get_json()["citas_importadas"] == 1


def test_enviar_recordatorios_dentro_de_ventana(client):
    fecha = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    cita = client.post("/api/citas", json={
        "nombre_paciente": "Pedro", "telefono": "+34600333444", "fecha_hora": fecha,
    }).get_json()
    r = client.post("/api/citas/enviar_recordatorios")
    assert r.status_code == 200
    body = r.get_json()
    assert body["recordatorios_enviados"] == 1
    assert body["detalle"][0]["cita_id"] == cita["id"]
    # segunda llamada no debe reenviar (ya marcado recordatorio_enviado)
    r2 = client.post("/api/citas/enviar_recordatorios")
    assert r2.get_json()["recordatorios_enviados"] == 0


def test_enviar_recordatorios_fuera_de_ventana_no_envia(client):
    fecha = (datetime.now(timezone.utc) + timedelta(hours=100)).isoformat()  # muy lejos, fuera de ventana 24h
    client.post("/api/citas", json={
        "nombre_paciente": "Lejano", "telefono": "+34600555666", "fecha_hora": fecha,
    })
    r = client.post("/api/citas/enviar_recordatorios")
    assert r.get_json()["recordatorios_enviados"] == 0


def test_confirmar_cita(client):
    fecha = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    cita = client.post("/api/citas", json={
        "nombre_paciente": "Confirmar Test", "telefono": "+34600777888", "fecha_hora": fecha,
    }).get_json()
    r = client.post(f"/api/citas/{cita['id']}/confirmar")
    assert r.status_code == 200
    assert r.get_json()["estado"] == "confirmada"


def test_cancelar_cita(client):
    fecha = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    cita = client.post("/api/citas", json={
        "nombre_paciente": "Cancelar Test", "telefono": "+34600999000", "fecha_hora": fecha,
    }).get_json()
    r = client.post(f"/api/citas/{cita['id']}/cancelar")
    assert r.status_code == 200
    assert r.get_json()["estado"] == "cancelada"


def test_suscribir_stripe_test_mode(client):
    r = client.post("/api/suscribir")
    assert r.status_code in (200, 400)
    assert r.is_json


def test_cita_tiene_token_publico_no_adivinable(client):
    fecha = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    cita = client.post("/api/citas", json={
        "nombre_paciente": "Token Test", "telefono": "+34600111222", "fecha_hora": fecha,
    }).get_json()
    with backend_app.app.app_context():
        c = backend_app.db.session.get(backend_app.Cita, cita["id"])
        assert c.token_publico is not None
        assert len(c.token_publico) >= 32


def test_endpoint_publico_por_token_no_expone_id_secuencial_adivinable(client):
    """Regresión de seguridad (IDOR encontrado en pentest): el endpoint público
    al que llega el paciente por WhatsApp debe usar un token no adivinable,
    no el id numérico secuencial de la cita."""
    fecha = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    cita = client.post("/api/citas", json={
        "nombre_paciente": "Paciente Privado", "telefono": "+34600222333", "fecha_hora": fecha,
    }).get_json()
    with backend_app.app.app_context():
        c = backend_app.db.session.get(backend_app.Cita, cita["id"])
        token = c.token_publico

    # confirmar via id secuencial NO debe ser el camino público (solo admin)
    r_publico = client.post(f"/c/{token}/confirmar")
    assert r_publico.status_code == 200
    body = r_publico.get_json()
    # el endpoint público no debe filtrar teléfono/nombre del paciente
    assert "telefono" not in body
    assert "nombre_paciente" not in body

    # un token inventado (no existente) no debe encontrar ninguna cita
    r_falso = client.post("/c/token-inventado-que-no-existe/confirmar")
    assert r_falso.status_code == 404


def test_cancelar_cita_ajena_via_token_incorrecto_no_afecta_otra_cita(client):
    fecha = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    cita_a = client.post("/api/citas", json={
        "nombre_paciente": "Paciente A", "telefono": "+34600333444", "fecha_hora": fecha,
    }).get_json()
    cita_b = client.post("/api/citas", json={
        "nombre_paciente": "Paciente B", "telefono": "+34600444555", "fecha_hora": fecha,
    }).get_json()
    with backend_app.app.app_context():
        token_b = backend_app.db.session.get(backend_app.Cita, cita_b["id"]).token_publico

    client.post(f"/c/{token_b}/cancelar")

    with backend_app.app.app_context():
        a = backend_app.db.session.get(backend_app.Cita, cita_a["id"])
        b = backend_app.db.session.get(backend_app.Cita, cita_b["id"])
        assert a.estado == "pendiente"
        assert b.estado == "cancelada"


def test_admin_token_protege_endpoints_administrativos_cuando_configurado(client, monkeypatch):
    """Regresión de seguridad: si se configura ADMIN_TOKEN, los endpoints de
    listado/gestión masiva de citas (datos de pacientes) deben exigirlo."""
    monkeypatch.setattr(backend_app, "ADMIN_TOKEN", "super-secreto-test")
    r_sin_token = client.get("/api/citas")
    assert r_sin_token.status_code == 401
    r_con_token_malo = client.get("/api/citas", headers={"X-Admin-Token": "incorrecto"})
    assert r_con_token_malo.status_code == 401
    r_con_token_bueno = client.get("/api/citas", headers={"X-Admin-Token": "super-secreto-test"})
    assert r_con_token_bueno.status_code == 200
