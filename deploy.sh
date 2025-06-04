#!/bin/bash

# 分散式網路測試系統部署腳本

set -e  # 遇到錯誤立即退出

# 顏色定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日誌函數
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_debug() {
    echo -e "${BLUE}[DEBUG]${NC} $1"
}

# 檢查系統要求
check_system_requirements() {
    log_info "檢查系統要求..."
    
    # 檢查是否為Linux系統
    if [[ "$OSTYPE" != "linux-gnu"* ]]; then
        log_error "此系統僅支持Linux"
        exit 1
    fi
    
    # 檢查Python版本
    if ! command -v python3 &> /dev/null; then
        log_error "需要Python 3.6或更高版本"
        exit 1
    fi
    
    python_version=$(python3 -c "import sys; print(sys.version_info.major * 10 + sys.version_info.minor)")
    if [ "$python_version" -lt 36 ]; then
        log_error "Python版本過低，需要3.6或更高版本"
        exit 1
    fi
    
    log_info "✅ 系統要求檢查通過"
}

# 安裝系統依賴
install_system_dependencies() {
    log_info "安裝系統依賴..."
    
    if command -v apt-get &> /dev/null; then
        # Ubuntu/Debian
        sudo apt-get update
        sudo apt-get install -y python3-pip python3-venv mariadb-server curl jq hping3 bc
    elif command -v yum &> /dev/null; then
        # CentOS/RHEL
        sudo yum install -y python3-pip mariadb-server curl jq hping3 bc
    elif command -v dnf &> /dev/null; then
        # Fedora
        sudo dnf install -y python3-pip mariadb-server curl jq hping3 bc
    else
        log_warn "未能自動安裝依賴，請手動安裝: python3-pip mariadb-server curl jq hping3 bc"
    fi
    
    log_info "✅ 系統依賴安裝完成"
}

# 設置MySQL
setup_mysql() {
    log_info "設置MySQL資料庫..."
    
    # 檢查MySQL是否已安裝
    if ! command -v mysql &> /dev/null; then
        log_error "MySQL未安裝，請先安裝MySQL"
        return 1
    fi
    
    # 啟動MySQL服務
    if command -v systemctl &> /dev/null; then
        sudo systemctl start mysql
        sudo systemctl enable mysql
    elif command -v service &> /dev/null; then
        sudo service mysql start
    fi
    
    # 檢查MySQL是否運行
    if ! mysqladmin ping &>/dev/null; then
        log_error "MySQL服務未運行"
        return 1
    fi
    
    # 創建資料庫
    log_info "創建資料庫..."
    read -s -p "請輸入MySQL root密碼: " mysql_root_password
    echo
    
    if mysql -u root -p"$mysql_root_password" < database_setup.sql; then
        log_info "✅ 資料庫創建成功"
    else
        log_error "資料庫創建失敗"
        return 1
    fi
    
    # 更新.env文件中的密碼
    if [ -f "master/.env" ]; then
        sed -i "s/^DB_PASSWORD=.*/DB_PASSWORD=$mysql_root_password/" master/.env
    fi
}

# 部署管理端
deploy_master() {
    log_info "部署管理端..."
    
    cd master
    
    # 創建Python虛擬環境
    if [ ! -d "venv" ]; then
        log_info "創建Python虛擬環境..."
        python3 -m venv venv
    fi
    
    # 激活虛擬環境並安裝依賴
    source venv/bin/activate
    log_info "安裝Python依賴..."
    pip install --upgrade pip
    pip install -r requirements.txt
    
    # 複製環境變數文件
    if [ ! -f ".env" ]; then
        cp .env.example .env
        log_info "環境變數文件已創建，請根據需要修改 master/.env"
    fi
    
    deactivate
    cd ..
    
    log_info "✅ 管理端部署完成"
}

# 創建systemd服務
create_systemd_service() {
    log_info "創建systemd服務..."
    
    local script_dir=$(pwd)
    
    # 創建服務文件
    sudo tee /etc/systemd/system/ddos-system-api.service > /dev/null << EOF
[Unit]
Description=DDoS System API Server
After=network.target mysql.service
Requires=mysql.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$script_dir/master
Environment=PATH=$script_dir/master/venv/bin
ExecStart=$script_dir/master/venv/bin/python api_server.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
    
    # 重新載入systemd並啟用服務
    sudo systemctl daemon-reload
    sudo systemctl enable ddos-system-api.service
    
    log_info "✅ systemd服務創建完成"
}

# 創建Nginx配置
setup_nginx() {
    log_info "設置Nginx反向代理..."
    
    if ! command -v nginx &> /dev/null; then
        log_warn "Nginx未安裝，跳過Nginx配置"
        return 0
    fi
    
    # 創建Nginx配置
    local api_port=$(grep "^API_PORT=" master/.env | cut -d'=' -f2 || echo "5050")
    
    sudo tee /etc/nginx/sites-available/ddos-system > /dev/null << EOF
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:$api_port;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
    
    # 啟用配置
    sudo ln -sf /etc/nginx/sites-available/ddos-system /etc/nginx/sites-enabled/
    sudo rm -f /etc/nginx/sites-enabled/default
    
    # 測試並重載Nginx配置
    sudo nginx -t && sudo systemctl reload nginx
    
    log_info "✅ Nginx配置完成"
}

# 啟動服務
start_services() {
    log_info "啟動服務..."
    
    # 啟動API服務
    sudo systemctl start ddos-system-api.service
    
    # 檢查服務狀態
    if sudo systemctl is-active --quiet ddos-system-api.service; then
        log_info "✅ API服務啟動成功"
    else
        log_error "API服務啟動失敗"
        sudo systemctl status ddos-system-api.service
        return 1
    fi
    
    # 如果安裝了Nginx，啟動Nginx
    if command -v nginx &> /dev/null; then
        sudo systemctl start nginx
        sudo systemctl enable nginx
        log_info "✅ Nginx服務啟動成功"
    fi
}

# 顯示部署信息
show_deployment_info() {
    local server_ip=$(curl -s ifconfig.me 2>/dev/null || curl -s ipinfo.io/ip 2>/dev/null || hostname -I | awk '{print $1}')
    local api_port=$(grep "^API_PORT=" master/.env | cut -d'=' -f2 || echo "5050")
    
    echo
    log_info "🎉 部署完成！"
    echo
    echo "=== 訪問信息 ==="
    if command -v nginx &> /dev/null && sudo systemctl is-active --quiet nginx; then
        echo "Web界面: http://$server_ip"
        echo "API地址: http://$server_ip/api"
    else
        echo "Web界面: http://$server_ip:$api_port"
        echo "API地址: http://$server_ip:$api_port/api"
    fi
    echo
    echo "=== 管理命令 ==="
    echo "啟動服務: sudo systemctl start ddos-system-api"
    echo "停止服務: sudo systemctl stop ddos-system-api"
    echo "查看狀態: sudo systemctl status ddos-system-api"
    echo "查看日誌: sudo journalctl -u ddos-system-api -f"
    echo
    echo "=== 客戶端部署 ==="
    echo "將 slave/vm_slave.sh 複製到各個VM上並執行:"
    echo "chmod +x vm_slave.sh"
    echo "./vm_slave.sh"
    echo
    echo "首次運行時會要求輸入管理服務器IP: $server_ip"
    echo
}

# 主函數
main() {
    local deploy_type="${1:-full}"
    
    echo "=== 分散式網路測試系統部署腳本 ==="
    echo
    
    case "$deploy_type" in
        "master"|"full")
            check_system_requirements
            install_system_dependencies
            setup_mysql
            deploy_master
            create_systemd_service
            setup_nginx
            start_services
            show_deployment_info
            ;;
        "slave")
            log_info "客戶端部署請使用 slave/vm_slave.sh 腳本"
            ;;
        *)
            echo "用法: $0 [master|slave|full]"
            echo "  master - 僅部署管理端"
            echo "  slave  - 僅部署客戶端"
            echo "  full   - 完整部署 (預設)"
            exit 1
            ;;
    esac
}

# 執行主函數
main "$@"
