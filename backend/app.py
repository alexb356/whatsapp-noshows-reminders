"""
MVP: Recordatorios automáticos por WhatsApp contra no-shows para consultas individuales.

Arquitectura pensada para funcionar con 0€ de gasto real:
- WhatsAppClient: interfaz abstracta. WhatsAppClientMock (por defecto, sin credenciales)
  registra los mensajes que se "enviarían". WhatsAppClientReal usa la API real de
  WhatsApp Cloud (Meta) solo si hay credenciales configuradas en .env.
- CalendarClient: interfaz abstracta similar para Google Calendar (mock vs OAuth real).

Ver NORMATIVA.md para las políticas de Meta/WhatsApp y RGPD relevantes.
"""
import os
import json
from datetime import datetime, timedelta, timezone
from abc import ABC, abstractmethod

from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "dev-only-not-secure")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///reminders.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

HORAS_ANTES_RECORDATORIO = float(os.environ.get("HORAS_ANTES_RECORDATORIO", "24"))


# ---------------------------------------------------------------------------
# Clientes de integración (interfaz + mock + real)
# ---------------------------------------------------------------------------

class WhatsAppClient(ABC):
    @abstractmethod
    def enviar_recordatorio(self, telefono, nombre_paciente, fecha_hora_str, cita_id):
        ...


class WhatsAppClientMock(WhatsAppClient):
    """Cliente simulado: no requiere credenciales, registra en memoria/BD lo que se enviaría."""
    def enviar_recordatorio(self, telefono, nombre_paciente, fecha_hora_str, cita_id):
        return {
            "modo": "mock",
            "estado": "simulado_ok",
            "telefono": telefono,
            "mensaje": (
                f"Hola {nombre_paciente}, te recordamos tu cita el {fecha_hora_str}. "
                f"Responde CONFIRMAR o CANCELAR, o entra aquí: /confirmar/{cita_id}"
            ),
        }


class WhatsAppClientReal(WhatsAppClient):
    """Cliente real usando WhatsApp Cloud API (Meta). Requiere credenciales en .env."""
    def __init__(self):
        import requests
        self.requests = requests
        self.phone_number_id = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
        self.token = os.environ["WHATSAPP_ACCESS_TOKEN"]
        self.template_name = os.environ.get("WHATSAPP_TEMPLATE_NAME", "recordatorio_cita")
        self.api_version = os.environ.get("WHATSAPP_API_VERSION", "v20.0")

    def enviar_recordatorio(self, telefono, nombre_paciente, fecha_hora_str, cita_id):
        url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": telefono,
            "type": "template",
            "template": {
                "name": self.template_name,
                "language": {"code": "es"},
                "components": [{
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": nombre_paciente},
                        {"type": "text", "text": fecha_hora_str},
                    ],
                }],
            },
        }
        resp = self.requests.post(url, json=payload,
                                   headers={"Authorization": f"Bearer {self.token}"}, timeout=15)
        resp.raise_for_status()
        return {"modo": "real", "estado": "enviado", "respuesta_api": resp.json()}


def get_whatsapp_client():
    if os.environ.get("WHATSAPP_PHONE_NUMBER_ID") and os.environ.get("WHATSAPP_ACCESS_TOKEN"):
        return WhatsAppClientReal()
    return WhatsAppClientMock()


class CalendarClient(ABC):
    @abstractmethod
    def listar_proximos_eventos(self, horas_adelante=48):
        ...


class CalendarClientMock(CalendarClient):
    """Cliente simulado: devuelve eventos de ejemplo almacenados en memoria para pruebas/demo."""
    def __init__(self, eventos=None):
        self.eventos = eventos or []

    def listar_proximos_eventos(self, horas_adelante=48):
        return self.eventos


class CalendarClientGoogle(CalendarClient):
    """Cliente real usando Google Calendar API (OAuth). Requiere credentials.json/token.json."""
    def __init__(self):
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        creds_file = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")
        token_file = os.environ.get("GOOGLE_TOKEN_FILE", "token.json")
        scopes = ["https://www.googleapis.com/auth/calendar.readonly"]
        creds = None
        if os.path.exists(token_file):
            creds = Credentials.from_authorized_user_file(token_file, scopes)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(creds_file, scopes)
                creds = flow.run_local_server(port=0)
            with open(token_file, "w") as fh:
                fh.write(creds.to_json())
        self.service = build("calendar", "v3", credentials=creds)

    def listar_proximos_eventos(self, horas_adelante=48):
        ahora = datetime.now(timezone.utc)
        limite = ahora + timedelta(hours=horas_adelante)
        result = self.service.events().list(
            calendarId="primary", timeMin=ahora.isoformat(), timeMax=limite.isoformat(),
            singleEvents=True, orderBy="startTime",
        ).execute()
        eventos = []
        for e in result.get("items", []):
            start = e["start"].get("dateTime", e["start"].get("date"))
            eventos.append({
                "id": e["id"], "titulo": e.get("summary", "Cita"),
                "inicio": start,
                "telefono": _extraer_telefono(e.get("description", "")),
                "nombre_paciente": e.get("summary", "Paciente"),
            })
        return eventos


def _extraer_telefono(texto):
    import re
    m = re.search(r"\+?\d[\d\s\-]{7,15}\d", texto or "")
    return m.group(0).replace(" ", "").replace("-", "") if m else None


def get_calendar_client():
    if os.path.exists(os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")):
        return CalendarClientGoogle()
    return CalendarClientMock()


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------

class Cita(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    evento_calendar_id = db.Column(db.String(200))
    nombre_paciente = db.Column(db.String(200), nullable=False)
    telefono = db.Column(db.String(30), nullable=False)
    fecha_hora = db.Column(db.DateTime, nullable=False)
    estado = db.Column(db.String(20), default="pendiente")  # pendiente/confirmada/cancelada
    recordatorio_enviado = db.Column(db.Boolean, default=False)
    creado = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id, "evento_calendar_id": self.evento_calendar_id,
            "nombre_paciente": self.nombre_paciente, "telefono": self.telefono,
            "fecha_hora": self.fecha_hora.strftime("%d-%m-%Y %H:%M"),
            "estado": self.estado, "recordatorio_enviado": self.recordatorio_enviado,
        }


def validar_telefono(telefono):
    limpio = (telefono or "").replace(" ", "").replace("-", "")
    return bool(limpio) and limpio.lstrip("+").isdigit() and 8 <= len(limpio.lstrip("+")) <= 15


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/citas", methods=["GET", "POST"])
def citas():
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        nombre = (data.get("nombre_paciente") or "").strip()
        telefono = (data.get("telefono") or "").strip()
        fecha_hora_str = data.get("fecha_hora")
        if not nombre or not telefono or not fecha_hora_str:
            return jsonify({"error": "nombre_paciente, telefono y fecha_hora son obligatorios"}), 400
        if not validar_telefono(telefono):
            return jsonify({"error": "teléfono inválido (usa formato internacional, ej. +34600000000)"}), 400
        try:
            fecha_hora = datetime.fromisoformat(fecha_hora_str)
        except ValueError:
            return jsonify({"error": "fecha_hora debe ser ISO 8601, ej. 2026-09-10T10:00:00"}), 400
        cita = Cita(nombre_paciente=nombre[:200], telefono=telefono, fecha_hora=fecha_hora)
        db.session.add(cita)
        db.session.commit()
        return jsonify(cita.to_dict()), 201
    return jsonify([c.to_dict() for c in Cita.query.order_by(Cita.fecha_hora.asc()).all()])


@app.route("/api/citas/sincronizar", methods=["POST"])
def sincronizar_calendario():
    """Importa próximos eventos desde Google Calendar (o el mock) como citas."""
    cliente = get_calendar_client()
    eventos = cliente.listar_proximos_eventos(horas_adelante=72)
    creadas = []
    for ev in eventos:
        if not ev.get("telefono"):
            continue
        ya_existe = Cita.query.filter_by(evento_calendar_id=ev.get("id")).first()
        if ya_existe:
            continue
        try:
            fecha_hora = datetime.fromisoformat(ev["inicio"].replace("Z", "+00:00"))
        except (ValueError, KeyError):
            continue
        cita = Cita(
            evento_calendar_id=ev.get("id"),
            nombre_paciente=ev.get("nombre_paciente", "Paciente"),
            telefono=ev["telefono"], fecha_hora=fecha_hora,
        )
        db.session.add(cita)
        creadas.append(cita)
    db.session.commit()
    return jsonify({"citas_importadas": len(creadas), "citas": [c.to_dict() for c in creadas]})


@app.route("/api/citas/enviar_recordatorios", methods=["POST"])
def enviar_recordatorios():
    """Envía el recordatorio a todas las citas dentro de la ventana configurada que aún no lo recibieron."""
    ahora = datetime.now(timezone.utc)
    ventana_fin = ahora + timedelta(hours=HORAS_ANTES_RECORDATORIO)
    candidatas = Cita.query.filter(
        Cita.recordatorio_enviado.is_(False),
        Cita.estado == "pendiente",
    ).all()
    cliente_wa = get_whatsapp_client()
    enviados = []
    for cita in candidatas:
        fecha_hora = cita.fecha_hora
        if fecha_hora.tzinfo is None:
            fecha_hora = fecha_hora.replace(tzinfo=timezone.utc)
        if ahora <= fecha_hora <= ventana_fin:
            resultado = cliente_wa.enviar_recordatorio(
                cita.telefono, cita.nombre_paciente,
                cita.fecha_hora.strftime("%d-%m-%Y %H:%M"), cita.id,
            )
            cita.recordatorio_enviado = True
            enviados.append({"cita_id": cita.id, "resultado": resultado})
    db.session.commit()
    return jsonify({"recordatorios_enviados": len(enviados), "detalle": enviados})


@app.route("/api/citas/<int:cita_id>/confirmar", methods=["POST"])
def confirmar_cita(cita_id):
    cita = Cita.query.get_or_404(cita_id)
    cita.estado = "confirmada"
    db.session.commit()
    return jsonify(cita.to_dict())


@app.route("/api/citas/<int:cita_id>/cancelar", methods=["POST"])
def cancelar_cita(cita_id):
    cita = Cita.query.get_or_404(cita_id)
    cita.estado = "cancelada"
    db.session.commit()
    return jsonify(cita.to_dict())


@app.route("/api/suscribir", methods=["POST"])
def suscribir():
    import stripe
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not stripe.api_key or not stripe.api_key.startswith("sk_test_"):
        return jsonify({"error": "Stripe no configurado en modo TEST"}), 400
    try:
        intent = stripe.PaymentIntent.create(amount=1500, currency="eur",
                                              metadata={"producto": "recordatorios-whatsapp-noshows"})
    except stripe.error.StripeError as exc:
        return jsonify({"error": f"Stripe rechazó la petición: {exc.user_message or str(exc)}"}), 400
    return jsonify({"client_secret": intent.client_secret, "payment_intent_id": intent.id})


def crear_tablas():
    with app.app_context():
        db.create_all()


if __name__ == "__main__":
    crear_tablas()
    app.run(debug=True, port=5004)
