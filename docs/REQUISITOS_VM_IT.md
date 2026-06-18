# Requisitos de Infraestructura — Dashboard Informe Regional de Salud

Documento de solicitud al equipo de TI de la Superintendencia de Salud para el aprovisionamiento de una máquina virtual que aloje el dashboard del Informe Regional de Salud.

**Solicitante:** Equipo Navinet Group
**Última actualización:** 2026-06-18

---

## 1. Resumen ejecutivo

Necesitamos **una máquina virtual Linux** para alojar:

1. Un **dashboard Streamlit** accesible a todos los empleados de la Superintendencia vía navegador.
2. Un **proceso automatizado mensual** que extrae datos de 8 fuentes oficiales (DANE, MinSalud, INS, SuperSalud) y refresca la base de datos del dashboard.

Solo 2 personas del equipo Navinet requieren acceso SSH a la VM. El dashboard será de lectura libre dentro de la red corporativa.

---

## 2. Especificaciones de la VM

### 2.1 Hardware

| Recurso | Solicitado | Justificación |
|---|---|---|
| **vCPU** | 2 cores | Streamlit + scraper Chrome headless |
| **RAM** | **8 GB** ✅ (ya autorizado) | Picos durante scraping de DANE (~3 GB) + dashboard activo |
| **Disco** | **30 GB SSD** ⚠️ (revisar — se mencionó 2 GB, es insuficiente) | OS + Docker + DB + crecimiento mensual ~50 MB |
| **Red** | 1 Gbps NIC | Estándar |

**Detalle del cálculo de disco:**

| Componente | Espacio |
|---|---|
| OS Ubuntu Server 24.04 LTS (instalación base) | 3 GB |
| Docker engine + imágenes (dashboard + Caddy + Python scrapers) | 2 GB |
| Base de datos DuckDB | 130 MB (crece ~50 MB/mes con histórico) |
| Parquets normalizados | 60 MB |
| Datos crudos descargados (raw/) | 300 MB inicial, crece |
| Chrome + chromedriver para scrapers | 500 MB |
| Logs rotados (90 días) | 500 MB |
| Buffer para actualizaciones del sistema + temp | 3 GB |
| Espacio libre recomendado | 20 GB |
| **Total** | **~30 GB** |

### 2.2 Sistema operativo

| Opción | Recomendación |
|---|---|
| **Ubuntu Server 24.04 LTS** | ✅ Preferido (LTS hasta 2029, mejor soporte Docker) |
| Ubuntu Server 22.04 LTS | OK |
| Debian 12 | OK |
| RHEL 9 / Rocky Linux 9 | OK |
| Windows Server | ❌ No recomendado (Docker funciona pero hay fricción) |

### 2.3 Software preinstalado (que IT debe instalar)

```
docker-ce >= 24.0
docker-compose-plugin >= 2.20
git
curl
chronyd (NTP)
```

Todo lo demás (Python, Chrome, Streamlit, etc.) viene dentro de contenedores Docker.

---

## 3. Red

### 3.1 Acceso entrante (inbound)

| Puerto | Protocolo | Origen | Servicio |
|---|---|---|---|
| **80** | TCP | Red corporativa Supersalud | Dashboard HTTP (redirige a HTTPS) |
| **443** | TCP | Red corporativa Supersalud | Dashboard HTTPS |
| **22** | TCP | Solo IPs de mantenimiento (2 personas) | SSH |

El dashboard NO requiere exposición a internet pública. Solo accesible desde la red corporativa interna.

### 3.2 Acceso saliente (outbound)

La VM necesita salida a internet para descargar datos durante el proceso mensual:

| Destino | Puerto | Uso |
|---|---|---|
| `*.dane.gov.co` | 443 | Proyecciones de población |
| `*.minsalud.gov.co` | 443 | REPS + afiliación |
| `prestadores.minsalud.gov.co` | 443 | REPS scrapers |
| `*.ins.gov.co` | 443 | PDFs epidemiológicos + IRCA |
| `*.supersalud.gov.co` | 443 | Excel IPS/EPS intervenidas |
| `docs.supersalud.gov.co` | 443 | SharePoint con archivos |
| `github.com` + `*.githubusercontent.com` | 443 | Descarga del DB + actualizaciones de código |
| `pypi.org` + `files.pythonhosted.org` | 443 | Dependencias Python |
| `auth.docker.io` + `registry-1.docker.io` | 443 | Imágenes Docker base |
| **NTP** (`pool.ntp.org` o servidor interno) | 123 UDP | Sincronización de hora (crítico para cron mensual) |

Si la política de TI requiere lista blanca explícita, los dominios anteriores son suficientes.

### 3.3 DNS interno

Solicitamos un registro **A** en el DNS interno de Supersalud:

```
informe-regional.supersalud.gov.co  →  <IP-de-la-VM>
```

(o el subdominio interno equivalente: `informe-regional.intra.supersalud.gov.co`)

---

## 4. Certificado TLS (HTTPS)

Aunque el acceso es solo interno, recomendamos HTTPS porque:

1. Política GEL/Mintic suele exigir TLS para tráfico de aplicaciones
2. Algunas funciones del navegador (clipboard, geolocalización) solo en contexto seguro
3. El costo en complejidad es mínimo

**Tres opciones**, IT decide:

| Opción | Cómo se obtiene el cert | Cuándo renovar |
|---|---|---|
| **A. Cert interno de Supersalud** (PKI corporativa) | IT emite cert para el hostname y nos lo entrega | Manual cada vencimiento (1-2 años) |
| **B. Let's Encrypt automático** | Caddy lo gestiona en el contenedor (requiere DNS público resolvible) | Automático cada 60 días |
| **C. Cert auto-firmado** | Generado por nosotros, IT lo agrega al trust store de los equipos corporativos | Manual |

**Nuestra recomendación: opción A** si Supersalud ya tiene una PKI interna; opción B si no.

---

## 5. Modelo de acceso

### 5.1 Usuarios del dashboard
- **Cualquier empleado de la Superintendencia** con conexión a la red corporativa puede acceder vía navegador a `https://informe-regional.supersalud.gov.co`
- **Sin login**: el filtrado lo hace el firewall (la VM no es accesible desde fuera de la red corporativa)
- Tráfico esperado: 10–50 usuarios concurrentes pico, 200–500 visitas mensuales

### 5.2 Administración de la VM (SSH)
Solo 2 cuentas necesitan acceso SSH:

| Cuenta | Rol | Acceso |
|---|---|---|
| `navinet-admin` | Despliegue + mantenimiento Navinet | `sudo` (sin password, con clave SSH) |
| `navinet-ops` | Monitoreo + actualizaciones mensuales | Login + sudo selectivo (`docker`, `git`, `systemctl restart`) |

Las claves públicas SSH las entregaremos al momento del aprovisionamiento.

### 5.3 Sin acceso de terceros
- Ningún empleado de Supersalud requiere acceso SSH directo
- IT mantiene acceso emergencia para troubleshooting de infraestructura
- Cualquier cambio en el código pasa por nuestro repositorio en GitHub

---

## 6. Pipeline automatizado mensual

### 6.1 Frecuencia
- **Día 5 de cada mes a las 06:00 (hora Bogotá)** — refresca fuentes mensuales (REPS, IRCA, afiliación, SuperSalud, INS PDFs)
- **15 de julio a las 06:00** — refresca proyecciones DANE (una vez al año)

### 6.2 Mecanismo
Cron job del usuario `navinet-ops` ejecuta:

```bash
cd /opt/informe-regional
./scripts/run_monthly_pipeline.sh
```

El script:
1. Activa el venv Python con los scrapers
2. Ejecuta `pipeline/runner.py --monthly` (~25 min)
3. Reinicia el contenedor del dashboard para que recargue el DB
4. Envía notificación de éxito/fallo a un email designado

### 6.3 Notificaciones
Necesitamos:
- Una cuenta SMTP corporativa de salida (puede ser un alias dedicado)
- O un webhook (Teams/Slack interno) para notificaciones de fallo

---

## 7. Backups y continuidad

### 7.1 Lo que se debe respaldar
- `/opt/informe-regional/data/informe_regional.duckdb` (130 MB) — el DB consolidado
- `/opt/informe-regional/data/parquet/` (60 MB) — parquets fuente

### 7.2 Estrategia recomendada
- Snapshot semanal del volumen Docker (ideal: domingos 02:00)
- Retención 30 días
- **El DB es reproducible** desde los parquets, así que pérdida total es recuperable corriendo el pipeline desde cero (~25 min)

### 7.3 Disaster recovery
- Si la VM se pierde, en una VM nueva basta:
  ```bash
  git clone https://github.com/NavinetGroup/dashboard-salud.git /opt/informe-regional
  cd /opt/informe-regional && docker compose up -d
  ```
  El DB se vuelve a descargar de GitHub Release (~10 s) y el dashboard está arriba.

---

## 8. Política de actualizaciones

| Componente | Frecuencia | Responsable |
|---|---|---|
| OS (Ubuntu unattended-upgrades) | Automático mensual | IT Supersalud |
| Docker engine | Manual trimestral | Equipo Navinet |
| Imágenes Docker del dashboard | Manual según releases (~bimestral) | Equipo Navinet |
| Código de scrapers / dashboard | Push a `main` en GitHub + reinicio del contenedor | Equipo Navinet |

---

## 9. Lo que entregamos vs lo que pedimos a IT

### ✅ Equipo Navinet entrega
- Código fuente (Python + Streamlit + Dockerfile + scripts)
- Documentación operativa ([MANTENIMIENTO.md](../MANTENIMIENTO.md))
- Claves SSH públicas de los 2 administradores
- Soporte post-despliegue

### 📥 Solicitamos a IT Supersalud
- [ ] VM con specs de la sección 2
- [ ] Reglas de firewall según sección 3
- [ ] Registro DNS interno (sección 3.3)
- [ ] Certificado TLS (opción A, B o C de sección 4)
- [ ] Cuenta SMTP de salida o webhook para notificaciones
- [ ] Configuración del backup según sección 7
- [ ] Acceso SSH para los 2 administradores Navinet

---

## 10. Plan de despliegue

| Día | Actividad | Responsable |
|---|---|---|
| **D-0** | IT entrega VM con OS + Docker + acceso SSH | IT Supersalud |
| **D+0** | Navinet despliega contenedor + ejecuta primer pipeline | Navinet |
| **D+1** | Validación interna del dashboard | Navinet |
| **D+2** | Walkthrough a stakeholders Supersalud | Ambos |
| **D+3** | Go-live oficial | — |

Tiempo total estimado: **3 días hábiles** desde la entrega de la VM.

---

## 11. Contacto

| Pregunta | Contacto |
|---|---|
| Técnica / despliegue | Equipo Navinet — `claude.ilam@outlook.com` |
| Aprobación / scope | Equipo Navinet |
