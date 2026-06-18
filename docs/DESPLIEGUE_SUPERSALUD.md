# Guía de Despliegue — VM SuperSalud

Pasos para desplegar el dashboard Informe Regional de Salud en una VM de la Superintendencia de Salud después de que IT entregue la máquina aprovisionada según [REQUISITOS_VM_IT.md](REQUISITOS_VM_IT.md).

**Tiempo total estimado:** 30 minutos.

---

## 0. Pre-requisitos

Antes de empezar IT debe haber entregado:

- [ ] VM Ubuntu Server 24.04 LTS (o equivalente) con SSH habilitado
- [ ] 30 GB SSD, 8 GB RAM, 2 vCPU
- [ ] Credenciales SSH (cuenta `navinet-admin` con sudo, llaves SSH públicas registradas)
- [ ] Hostname `informe-regional.supersalud.gov.co` en DNS interno apuntando a la IP de la VM
- [ ] Reglas de firewall: 80/443 entrante desde red corporativa; salida HTTPS a internet (lista en sección 3.2 del documento de requisitos)
- [ ] Certificado TLS + clave (`.crt` y `.key`) — opción A (PKI Supersalud) o B (Let's Encrypt) o C (auto-firmado)

---

## 1. Conectarse e instalar dependencias del sistema

```bash
# Desde tu máquina local
ssh navinet-admin@informe-regional.supersalud.gov.co

# Una vez dentro, ejecutar el instalador (descarga repo, instala Docker, Chrome, cron)
sudo bash <(curl -fsSL https://raw.githubusercontent.com/NavinetGroup/dashboard-salud/main/scripts/install_vm.sh)
```

El script `install_vm.sh` hace todo automáticamente en ~5 min:

- Verifica que el OS sea Ubuntu/Debian
- Instala paquetes base (`python3.12-venv`, `git`, `cron`, `mailutils`)
- Instala Docker engine + lo habilita en boot
- Instala Google Chrome (para los scrapers Selenium)
- Crea el usuario `navinet-ops` y lo agrega al grupo `docker`
- Clona el repo en `/opt/informe-regional`
- Crea el venv Python con `requirements_full.txt`
- Configura los cron jobs:
  - Día **5 de cada mes a las 06:00** → pipeline mensual
  - **15 de julio a las 06:00** → pipeline anual (demografía DANE)

---

## 2. Configurar variables de entorno

```bash
cd /opt/informe-regional
sudo -u navinet-ops cp .env.example .env
sudo -u navinet-ops nano .env
```

Edita los valores:

```bash
HOSTNAME=informe-regional.supersalud.gov.co

# Si IT te entregó cert + key:
TLS_MODE=file
TLS_CERT_PATH=/etc/ssl/certs/informe-regional.crt
TLS_KEY_PATH=/etc/ssl/private/informe-regional.key

# Si no te entregan cert y solo es prueba interna:
TLS_MODE=internal      # Caddy auto-firma (los usuarios verán warning del navegador)

# Notificaciones — elige UNO:
NOTIFY_WEBHOOK_URL=https://supersalud.webhook.office.com/webhookb2/...   # Teams
# o
NOTIFY_EMAIL_TO=ops@navinetgroup.com
SMTP_HOST=smtp.supersalud.gov.co
SMTP_USER=...
SMTP_PASS=...
```

### 2.1 Copiar el certificado TLS (si TLS_MODE=file)

```bash
sudo cp /ruta/donde/IT/entregó/cert.crt /etc/ssl/certs/informe-regional.crt
sudo cp /ruta/donde/IT/entregó/cert.key /etc/ssl/private/informe-regional.key
sudo chmod 644 /etc/ssl/certs/informe-regional.crt
sudo chmod 600 /etc/ssl/private/informe-regional.key
```

---

## 3. Levantar los contenedores

```bash
cd /opt/informe-regional
sudo -u navinet-ops docker compose -f docker-compose.prod.yml up -d --build
```

Esto:
1. Construye la imagen del dashboard (~3 min primera vez)
2. Descarga la imagen de Caddy
3. Levanta ambos contenedores en background

Verifica:

```bash
sudo -u navinet-ops docker compose -f docker-compose.prod.yml ps
# Ambos deben estar "Up (healthy)" en 2 minutos
```

---

## 4. Validar el despliegue

### 4.1 Health check local

```bash
curl -k https://localhost/_stcore/health
# Debe devolver: ok
```

### 4.2 Desde otra máquina de la red Supersalud

Abre en el navegador:

```
https://informe-regional.supersalud.gov.co
```

Debe cargar el dashboard. Primera carga tarda ~10 s porque baja el DB de 129 MB del GitHub Release.

### 4.3 Logs

```bash
# Logs en vivo del dashboard
sudo -u navinet-ops docker logs -f informe-dashboard

# Logs en vivo de Caddy
sudo -u navinet-ops docker logs -f informe-caddy
```

---

## 5. Ejecutar el primer pipeline manualmente (recomendado)

Para no esperar al día 5 del mes y verificar que todo funcione:

```bash
cd /opt/informe-regional
sudo -u navinet-ops bash scripts/run_monthly_pipeline.sh
```

Toma ~25 min. Al final el dashboard se reinicia con los datos frescos.

---

## 6. Operación continua

Una vez completados los pasos 1-5, la VM opera sola:

| Cuándo | Qué pasa | Acción del operador |
|---|---|---|
| Día 5 06:00 | Cron ejecuta pipeline mensual | Ninguna; recibes notificación al final |
| 15 julio 06:00 | Cron ejecuta pipeline anual | Ninguna |
| Cada vez que Navinet actualiza el código | El pipeline mensual hace `git pull` antes de correr | Ninguna |
| Si el pipeline falla | Recibes notificación con el error | Ver sección 7 (troubleshooting) |

---

## 7. Troubleshooting

| Síntoma | Causa probable | Acción |
|---|---|---|
| `curl -k localhost/_stcore/health` no responde | Container no levantó | `docker logs informe-dashboard` |
| El dashboard se ve pero sin datos | Primera vez, descargando DB | Esperar 30 segundos y refrescar |
| Cert warning en el navegador | TLS_MODE=internal | Cambiar a TLS_MODE=file con cert real |
| `git pull` falla en el cron | Cambios locales sin commit en la VM | `cd /opt/informe-regional && git status`; resolver |
| IRCA no descargó datos nuevos | Scraper headless rechazado por reCAPTCHA | Ver [MANTENIMIENTO.md](../MANTENIMIENTO.md) sección IRCA |
| Pipeline tarda >40 min | Servidor INS lento o caído | Re-correr manualmente más tarde |

---

## 8. Actualizar el dashboard

Cuando Navinet publica una nueva versión del código:

```bash
cd /opt/informe-regional
sudo -u navinet-ops git pull
sudo -u navinet-ops docker compose -f docker-compose.prod.yml up -d --build dashboard
```

El siguiente `git pull` lo hace el cron automáticamente, así que en realidad no hay que correr nada — los cambios entran en producción en la próxima ejecución mensual.

Para forzar un deploy inmediato sin esperar al cron, usa el comando anterior.

---

## 9. Desinstalar / mover

Si en algún momento hay que migrar a otra VM:

```bash
# En la VM origen — backup el DB
sudo -u navinet-ops docker compose -f docker-compose.prod.yml down
sudo cp /var/lib/docker/volumes/informe-regional_informe_data/_data/informe_regional.duckdb /tmp/

# En la VM destino — instalar (paso 1 de esta guía)
# Luego copiar el DB en lugar de re-descargarlo:
sudo cp /tmp/informe_regional.duckdb /var/lib/docker/volumes/informe-regional_informe_data/_data/
sudo -u navinet-ops docker compose -f docker-compose.prod.yml up -d
```

---

## 10. Contactos

| Tema | Quién |
|---|---|
| Despliegue / código / errores del pipeline | Equipo Navinet — `claude.ilam@outlook.com` |
| Infraestructura / red / certificado TLS | IT Supersalud |
| Acceso de usuarios al dashboard | Equipo Navinet (sin auth — depende del firewall) |
