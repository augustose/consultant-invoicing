#!/bin/zsh

# Colors and Styling
BLUE='\033[0;34m'
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Initial Setup
PROJECT_ROOT=$(pwd)
APP_DIR="$PROJECT_ROOT/app"
BACKUP_DIR="$PROJECT_ROOT/backups"
LOG_DIR="$PROJECT_ROOT/logs"
STDOUT_LOG="$LOG_DIR/app_stdout.log"
STDERR_LOG="$LOG_DIR/app_stderr.log"
SYSTEM_LOG="$LOG_DIR/system.log"

# Ensure directories exist
mkdir -p "$LOG_DIR"
mkdir -p "$BACKUP_DIR"

function log_message() {
    local level=$1
    local msg=$2
    local timestamp=$(date +"%Y-%m-%d %H:%M:%S")
    echo "[$timestamp] [$level] $msg" >> "$SYSTEM_LOG"
}

# Initial system log
log_message "INFO" "SISTEMA DE GESTION INICIADO"

function show_banner() {
    clear
    echo -e "${CYAN}${BOLD}"
    echo "  ╔══════════════════════════════════════════════════╗"
    echo "  ║                                                  ║"
    echo "  ║   🌊  ACCOUNTING AI - SISTEMA DE MANTENIMIENTO   ║"
    echo "  ║                                                  ║"
    echo "  ╚══════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

function show_menu() {
    echo -e "${BOLD}Seleccione una acción para continuar:${NC}"
    echo ""
    echo -e "  ${GREEN}[S]${NC} ${BOLD}Start${NC}      - Lanzar sistema (solo terminal)"
    echo -e "  ${BLUE}[W]${NC} ${BOLD}Web${NC}        - Lanzar sistema y abrir navegador"
    echo -e "  ${RED}[K]${NC} ${BOLD}Kill${NC}       - Detener la aplicación"
    echo -e "  ${YELLOW}[B]${NC} ${BOLD}Backup${NC}     - Crear copia de seguridad"
    echo -e "  ${YELLOW}[L]${NC} ${BOLD}Logs${NC}       - Ver logs del sistema"
    echo -e "  ${CYAN}[D]${NC} ${BOLD}Docs${NC}       - Abrir documentación"
    echo -e "  ${RED}[X]${NC} ${BOLD}Exit${NC}       - Detener procesos y salir"
    echo ""
    echo -en "${BOLD}Esperando tecla... ${NC}"
}

function create_backup() {
    log_message "INFO" "Iniciando proceso de backup..."
    echo -e "\n\n${YELLOW}📦 Generando backup...${NC}"
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    BACKUP_NAME="backup_accounting_ai_$TIMESTAMP.tar.gz"
    
    # Exclude node_modules for speed and space
    tar --exclude='node_modules' -czf "$BACKUP_DIR/$BACKUP_NAME" .
    
    log_message "SUCCESS" "Backup completado exitosamente: $BACKUP_NAME"
    echo -e "${GREEN}✅ Backup completado: $BACKUP_NAME${NC}"
    sleep 2
}

function open_docs() {
    log_message "INFO" "Usuario abrió documentación"
    echo -e "\n\n${CYAN}📄 Abriendo documentación...${NC}"
    open "$PROJECT_ROOT/docs"
    sleep 1
}

function view_logs() {
    log_message "INFO" "Usuario solicitó ver logs"
    echo -e "\n\n${YELLOW}📋 Mostrando últimos 50 líneas de logs (presione Ctrl+C para salir)...${NC}"
    tail -n 50 -f "$SYSTEM_LOG" "$STDERR_LOG" "$STDOUT_LOG"
}

function stop_existing() {
    # Kill any existing process on port 8081
    EXISTING_PID=$(lsof -ti :8081 2>/dev/null)
    if [[ -n "$EXISTING_PID" ]]; then
        echo -e "${YELLOW}⚠️  Proceso existente en puerto 8081 detectado (PID: $EXISTING_PID). Deteniendo...${NC}"
        log_message "WARN" "Deteniendo proceso existente en puerto 8081 (PID: $EXISTING_PID)"
        kill -9 $EXISTING_PID 2>/dev/null
        sleep 1
        echo -e "${GREEN}✅ Proceso anterior detenido.${NC}"
        log_message "INFO" "Proceso anterior detenido exitosamente"
    fi
}

function stop_app() {
    echo -e "\n\n${YELLOW}🛑 Deteniendo la aplicación...${NC}"
    log_message "INFO" "Usuario solicitó detener la aplicación"
    stop_existing
    echo -e "${GREEN}✅ Aplicación detenida.${NC}"
    sleep 1
}

function start_system() {
    SHOW_BROWSER=$1
    log_message "INFO" "Iniciando sistema (Browser: $SHOW_BROWSER)"
    echo -e "\n\n${GREEN}🚀 Starting Python application with UV...${NC}"
    echo -e "${YELLOW}📝 Logs are being recorded in: $LOG_DIR${NC}"
    
    # Kill any existing process on that port first
    stop_existing
    
    cd "$PROJECT_ROOT"
    if [[ "$SHOW_BROWSER" == "true" ]]; then
        echo -e "${BLUE}🌐 Opening browser...${NC}"
        export NICEGUI_SHOW_BROWSER=true
    else
        export NICEGUI_SHOW_BROWSER=false
    fi

    # Run and tee output to logs. We use 2>&1 to capture errors in stdout log too, 
    # but also separate them for easier debugging if needed.
    # Also capture exit code
    uv run app/main.py > >(tee -a "$STDOUT_LOG") 2> >(tee -a "$STDERR_LOG" >&2)
    EXIT_CODE=$?

    if [ $EXIT_CODE -ne 0 ]; then
        log_message "ERROR" "La aplicación se detuvo con código de error: $EXIT_CODE"
        echo -e "\n\n${RED}${BOLD}❌ ERROR: El sistema se cerró inesperadamente (Código: $EXIT_CODE).${NC}"
        echo -e "${YELLOW}Puede revisar los logs detallados en: $STDERR_LOG${NC}"
        echo -e "\nPresione cualquier tecla para volver al menú..."
        read -k 1
    else
        log_message "INFO" "Sistema detenido normalmente"
    fi
}

# Principal Loop
while true; do
    show_banner
    show_menu
    
    # Read one character
    read -k 1 REPLY
    
    case $REPLY in
        [Ss]) 
            start_system false
            ;;
        [Ww])
            start_system true
            ;;
        [Kk])
            stop_app
            ;;
        [Bb])
            create_backup
            ;;
        [Ll])
            view_logs
            ;;
        [Dd])
            open_docs
            ;;
        [Xx])
            log_message "INFO" "Cerrando sistema de gestión"
            echo -e "\n\n${RED}👋 Cerrando sistema. ¡Hasta pronto!${NC}"
            exit 0
            ;;
        *)
            log_message "WARN" "Opción no válida seleccionada: $REPLY"
            echo -e "\n\n${RED}❌ Opción no válida.${NC}"
            sleep 1
            ;;
    esac
done
