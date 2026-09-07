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
