# RESUMEN — Proyecto 4: Recordatorios WhatsApp contra no-shows

## Qué se ha construido
MVP Flask + SQLite:
- Modelo de **Cita** (paciente, teléfono, fecha/hora, estado pendiente/confirmada/cancelada, si ya se envió recordatorio).
- **Integración con Google Calendar mediante interfaz abstracta**: `CalendarClientGoogle` (OAuth real, requiere `credentials.json` del usuario) y `CalendarClientMock` (usado automáticamente si no hay credenciales — permite probar todo el flujo sin coste).
- **Integración con WhatsApp Cloud API (Meta) mediante interfaz abstracta**: `WhatsAppClientReal` (requiere número verificado + plantilla aprobada por Meta) y `WhatsAppClientMock` (usado automáticamente si no hay credenciales).
- **Lógica de scheduling**: endpoint que recorre citas pendientes y envía el recordatorio solo si la cita cae dentro de la ventana configurada (`HORAS_ANTES_RECORDATORIO`, por defecto 24h), evitando reenvíos.
- Endpoints de **confirmar/cancelar** cita (pensados para ser el destino del enlace que se manda por WhatsApp, ya que el envío real de respuestas de botón interactivo de WhatsApp requiere webhook con la cuenta Meta real).
- Validación de formato de teléfono internacional.
- Stripe en modo TEST para la suscripción del SaaS.
- 12 tests automatizados, todos pasan: validación de teléfono, alta de cita, selección automática de cliente mock cuando no hay credenciales, sincronización desde calendario (mock inyectado), ventana de envío de recordatorios (dentro/fuera de ventana, no reenvío), confirmar/cancelar, suscripción Stripe test.

## Decisiones de negocio/normativas tomadas y por qué
1. **No se pudo ni se debía generar una cuenta real de Meta Business ni un proyecto Google Cloud con OAuth** — son credenciales que solo el usuario final (el profesional o tú) puede crear y verificar (número de teléfono, verificación de negocio, aprobación de plantilla por Meta). Por eso el diseño usa **interfaces inyectables**: toda la lógica de negocio (cuándo enviar, qué mensaje, cómo confirmar/cancelar) está terminada y testeada; conectar credenciales reales en producción no requiere tocar código, solo rellenar `.env`.
2. Se eligió la ventana de recordatorio configurable (`HORAS_ANTES_RECORDATORIO`, por defecto 24h) en vez de un valor fijo, porque el contexto ("X horas antes") lo pidió el propio brief sin especificar el número exacto — decisión razonable documentada aquí, no bloqueante.
3. El mensaje de recordatorio deliberadamente **no incluye información clínica** (solo fecha/hora + nombre) para minimizar el riesgo de tratar datos de salud especialmente protegidos por WhatsApp, según lo documentado en NORMATIVA.md.
4. La confirmación/cancelación se implementa como enlace a un endpoint propio (`/confirmar/<id>`) en vez de depender de "responder al mensaje de WhatsApp con un botón interactivo", porque procesar respuestas de usuario por WhatsApp requiere configurar un **webhook** en la cuenta Meta real — no se puede simular de forma realista sin esa cuenta. Queda documentado como el siguiente paso técnico.

## Qué debe hacer el usuario para pasar a producción
- Crear cuenta de **WhatsApp Business Platform (Cloud API)** en Meta for Developers, verificar el número de teléfono del profesional, y solicitar aprobación de una **plantilla de categoría "Utility"** para el recordatorio (proceso de Meta, puede tardar días).
- Crear un proyecto en **Google Cloud Console**, habilitar la Google Calendar API, configurar la pantalla de consentimiento OAuth y descargar `credentials.json` (colocarlo en la carpeta del backend, no subirlo a git — ya está en `.gitignore`).
- Configurar un **webhook** de WhatsApp para recibir respuestas de "confirmar/cancelar" directamente desde el chat (mejora sobre el enlace actual).
- Cuenta Stripe real para la suscripción.
- Revisión de protección de datos (RGPD) antes de operar con datos de pacientes de psicólogos/terapeutas — ver duda en NORMATIVA.md.
- Dominio y hosting con HTTPS (Meta exige HTTPS para el webhook en producción).

## Riesgos / dudas a revisar
- **[DUDA NORMATIVA]** Si el profesional es psicólogo/terapeuta, el simple hecho de tener una cita programada puede considerarse dato relacionado con la salud (categoría especial art. 9 RGPD). Recomiendo que el usuario consulte con un DPO/asesor de protección de datos antes de operar a más de un puñado de pacientes, y que añada una cláusula informativa clara sobre el uso de WhatsApp para recordatorios en el consentimiento informado que ya use en consulta.
- La aprobación de plantillas de Meta puede ser rechazada o tardar; es un paso fuera de mi control y del usuario totalmente hasta que se solicite.
- El extractor de teléfono desde la descripción del evento de Google Calendar (`_extraer_telefono`) es una heurística simple por regex — en producción sería más robusto añadir el teléfono como campo dedicado en el propio evento o en una base de datos de pacientes.

## Revisión de bugs post-entrega (07/09/2026)
Se hizo una pasada de QA sobre el código antes de publicarlo: pyflakes (sin avisos tras limpiar un import no usado), y pruebas de casos límite (cancelar cita antes de enviar recordatorio, doble sincronización sin duplicar citas, fechas naive vs con timezone). No se encontraron bugs funcionales adicionales. Se corrigió una vulnerabilidad de **HTML injection**: el nombre del paciente (que puede venir del título de un evento de Google Calendar, dato externo) se insertaba sin escapar en el panel de citas vía `innerHTML` — corregido con `escapeHtml()`.

## Auditoría de pentest (07/09/2026) — hallazgos y correcciones

| # | Hallazgo | Severidad | Corrección |
|---|----------|-----------|------------|
| 1 | **IDOR (Insecure Direct Object Reference) crítico**: el enlace enviado al paciente por WhatsApp era `/confirmar/<id_entero_secuencial>`. Cualquiera podía iterar IDs consecutivos y confirmar o **cancelar las citas de otros pacientes** — ataque de disponibilidad directo contra el negocio del profesional (podía vaciar la agenda cancelando todas las citas). | 🔴 Crítica | Cada cita recibe un `token_publico` no adivinable (`secrets.token_urlsafe(32)`, columna `UNIQUE`). El enlace público ahora es `/c/<token>/confirmar` y `/c/<token>/cancelar`; el `id` numérico interno ya no se expone en el mensaje de WhatsApp. La respuesta del endpoint público tampoco filtra teléfono ni nombre del paciente (`to_dict(incluir_datos_sensibles=False)`). |
| 2 | **Exposición sin autenticación de datos de pacientes**: `GET /api/citas` devolvía nombre, teléfono y hora de cita de **todos los pacientes** sin ningún control de acceso — dato especialmente sensible tratándose de pacientes de psicólogos/terapeutas. | 🔴 Crítica | Endpoints de administración (`/api/citas`, `/sincronizar`, `/enviar_recordatorios`, confirmar/cancelar por id interno) protegidos por un token compartido opcional `ADMIN_TOKEN` (cabecera `X-Admin-Token`, comparación con `secrets.compare_digest` para evitar timing attacks). Si no se configura (modo demo/local), quedan abiertos — **debe configurarse obligatoriamente en cualquier despliegue accesible desde internet**, documentado en `.env.example`. |
| 3 | **DoS / debug expuesto** (mismo patrón transversal). | 🟡 Media | `debug` controlado por `FLASK_DEBUG`; `MAX_CONTENT_LENGTH` 2MB; cabeceras de seguridad estándar. |

4 tests nuevos de regresión (token no adivinable, endpoint público no filtra datos sensibles, cancelar la cita de un token no afecta a otra cita, `ADMIN_TOKEN` bloquea/permite correctamente). Total: 16/16 tests pasan.

**Limitación no resuelta (documentada)**: `ADMIN_TOKEN` es un secreto compartido simple, no un sistema de login con usuarios — suficiente para un único profesional autónomo, pero no aísla a varios profesionales entre sí si se despliega multi-tenant sin más desarrollo.
