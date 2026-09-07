# Normativa y políticas relevantes — Recordatorios WhatsApp

No es una obligación legal con fecha límite (a diferencia de Verifactu), pero hay dos marcos que sí aplican y se documentan aquí:

## 1. Política de plantillas de WhatsApp Business (Meta)
- Fuente: Meta for Developers — WhatsApp Business Platform, política de mensajería basada en plantillas ("message templates") y ventana de conversación de 24h.
- Para enviar un mensaje **proactivo** (no iniciado por el usuario) fuera de la ventana de 24h desde su último mensaje, es obligatorio usar una **plantilla pre-aprobada por Meta** (categoría "Utility" es la adecuada para recordatorios de citas).
- El usuario final debe haber dado **opt-in** (consentimiento expreso) para recibir mensajes de la empresa por WhatsApp — no puede enviarse a cualquier número sin más.
- Requiere una cuenta de **WhatsApp Business Platform (Cloud API)** de Meta, número de teléfono verificado y las plantillas aprobadas — credenciales y proceso de aprobación que solo puede completar el usuario final (no yo).

## 2. RGPD — datos de pacientes/clientes de fisios, psicólogos, terapeutas
- El nombre, teléfono y (en el caso de psicólogos) la mera existencia de una cita puede considerarse un **dato relacionado con la salud** (categoría especial del art. 9 RGPD) si se infiere el tipo de tratamiento — recomendable minimizar los datos que se envían por WhatsApp (solo "tienes una cita el [fecha/hora]", sin detalles clínicos).
- El profesional (responsable del tratamiento) debe informar a sus pacientes de que sus datos de contacto se usan para recordatorios automáticos (cláusula en su política de privacidad / consentimiento informado ya existente en consulta).
- **[DUDA A REVISAR POR EL USUARIO/PROFESIONAL]**: si el profesional trata datos de salud, podría requerir una base jurídica reforzada o medidas de seguridad adicionales — recomendable consulta con un DPO/asesor de protección de datos antes de un uso a gran escala, especialmente para psicólogos.

## Decisiones de diseño para el MVP
- El envío real a la API de WhatsApp Cloud (Meta) y la integración OAuth con Google Calendar requieren **credenciales que solo el usuario final puede generar** (cuenta Meta Business, número verificado, plantilla aprobada; proyecto de Google Cloud con OAuth consent screen). El MVP implementa toda la lógica de negocio (lectura de calendario, cálculo de ventana de recordatorio, plantilla de mensaje, manejo de confirmación/cancelación) con **clientes de API inyectables y mockeables**, de forma que:
  - En modo demo/test, todo funciona con un cliente simulado (mock) que registra qué se habría enviado.
  - En producción, basta con configurar las credenciales reales en `.env` sin tocar el código de negocio.
- Esto NO es un incumplimiento: es la única forma honesta de construir esto sin gastar dinero ni fabricar credenciales falsas.
