# 分散式網路測試管理系統

這是一個功能完整的分散式網路測試系統，允許管理多個VM客戶端進行協調的網路連接測試。系統采用主從架構，支持TCP/UDP/ICMP三種協議的網路測試。

## 🚀 特色功能

- ✅ **VM客戶端自動註冊和心跳監控** - 實時追蹤客戶端狀態
- ✅ **現代化Web界面** - 直觀的任務管理和監控界面
- ✅ **多協議支持** - TCP/UDP/ICMP測試
- ✅ **即時狀態監控** - 實時查看任務執行狀態
- ✅ **測試結果統計** - 詳細的測試結果分析
- ✅ **RESTful API** - 完整的API接口
- ✅ **自動部署** - 一鍵部署腳本
- ✅ **服務化管理** - systemd服務支持

## 📋 系統要求

### 管理端
- **作業系統**: Linux (Ubuntu 18.04+, CentOS 7+)
- **Python**: 3.6+
- **資料庫**: MySQL 5.7+
- **內存**: 1GB+
- **磁盤**: 2GB+

### 客戶端
- **作業系統**: Linux
- **必要工具**: curl, jq, hping3, bc
- **網路**: 能夠訪問管理端

## 🏗️ 系統架構

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Web 界面      │────▶│   Flask API     │────▶│     MySQL       │
│                 │     │                 │     │   資料庫        │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                │
                                │ HTTP API
                                │
                        ┌───────┼───────┐
                        ▼       ▼       ▼
                   ┌─────────┐ ┌─────────┐ ┌─────────┐
                   │  VM 1   │ │  VM 2   │ │  VM N   │
                   │ Client  │ │ Client  │ │ Client  │
                   └─────────┘ └─────────┘ └─────────┘
```

## 🚀 快速開始

### 方法一：自動部署（推薦）

1. **下載項目**
```bash
git clone <repository-url>
cd ddos
```

2. **運行部署腳本**
```bash
sudo ./deploy.sh
```

腳本會自動：
- 檢查系統要求
- 安裝必要依賴
- 設置MySQL資料庫
- 創建Python虛擬環境
- 安裝Python依賴
- 配置systemd服務
- 設置Nginx反向代理（可選）
- 啟動所有服務

### 方法二：手動部署

#### 1. 管理端部署

```bash
# 安裝系統依賴
sudo apt-get update
sudo apt-get install python3-pip python3-venv mariadb-server

# 設置MySQL
sudo mysql -u root -p < database_setup.sql

# 創建Python環境
cd master
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 配置環境變數
cp .env.example .env
# 編輯 .env 文件，修改資料庫連接信息

# 啟動API服務
python api_server.py
```

#### 2. VM客戶端部署

```bash
# 在每個VM上安裝依賴
sudo apt-get install curl jq hping3 bc

# 複製客戶端腳本
scp slave/vm_slave.sh user@vm-ip:~/
ssh user@vm-ip
chmod +x vm_slave.sh

# 運行客戶端
./vm_slave.sh
```

## 📖 使用指南

### Web界面操作

1. **訪問Web界面**
   - 打開瀏覽器訪問 `http://your-server-ip`

2. **創建測試任務**
   - 填寫目標IP、端口、測試類型等參數
   - 選擇要使用的VM（留空使用所有在線VM）
   - 點擊"開始測試"

3. **監控測試進度**
   - 在"最近任務"區域查看任務狀態
   - 點擊"查看結果"查看詳細測試結果

### API使用

#### VM管理
```bash
# 註冊VM
curl -X POST http://server:5050/api/vm/connect \
  -H "Content-Type: application/json" \
  -d '{"vm_id":"vm-001","ip_address":"192.168.1.100","hostname":"test-vm"}'

# 發送心跳
curl -X POST http://server:5050/api/vm/heartbeat \
  -H "Content-Type: application/json" \
  -d '{"vm_id":"vm-001"}'

# 獲取在線VM
curl http://server:5050/api/vms
```

#### 任務管理
```bash
# 創建測試任務
curl -X POST http://server:5050/api/tasks/create \
  -H "Content-Type: application/json" \
  -d '{
    "target_ip": "8.8.8.8",
    "target_port": 80,
    "test_type": "TCP",
    "packet_size": 64,
    "connection_count": 100,
    "duration": 30
  }'

# 查看任務結果
curl http://server:5050/api/tasks/{task_id}/results
```

### 客戶端命令

```bash
# 查看幫助
./vm_slave.sh --help

# 重新配置
./vm_slave.sh --config

# 測試連接
./vm_slave.sh --test

# 以守護進程運行
./vm_slave.sh --daemon
```

## ⚙️ 配置說明

### 環境變數 (.env)
```bash
DB_HOST=localhost          # 資料庫主機
DB_USER=wolfheluo          # 資料庫用戶
DB_PASSWORD=nasa0411       # 資料庫密碼
DB_NAME=ddos_system        # 資料庫名
API_PORT=5050              # API服務端口
VM_HEARTBEAT_TIMEOUT=120   # VM心跳超時(秒)
```

### 測試參數

| 參數 | 說明 | 預設值 | 範圍 |
|------|------|--------|------|
| 目標IP | 測試目標的IP地址 | - | 有效IP地址 |
| 目標端口 | 測試目標端口 | 80 | 1-65535 |
| 測試類型 | 協議類型 | TCP | TCP/UDP/ICMP |
| 數據包大小 | 每個包的大小(bytes) | 64 | 1-65507 |
| 連接數 | 總連接/包數量 | 100 | 1-10000 |
| 持續時間 | 測試持續時間(秒) | 30 | 1-300 |

## 🔧 管理命令

### 服務管理
```bash
# 啟動服務
sudo systemctl start ddos-system-api

# 停止服務
sudo systemctl stop ddos-system-api

# 重啟服務
sudo systemctl restart ddos-system-api

# 查看狀態
sudo systemctl status ddos-system-api

# 查看日誌
sudo journalctl -u ddos-system-api -f
```

### 日誌查看
```bash
# API服務器日誌
sudo journalctl -u ddos-system-api

# VM客戶端日誌
tail -f /var/log/vm_client.log  # root用戶
tail -f ~/vm_client.log         # 普通用戶

# Nginx日誌
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log
```

## 🐛 故障排除

### 常見問題

1. **API服務無法啟動**
   ```bash
   # 檢查端口是否被占用
   sudo netstat -tlnp | grep 5050
   
   # 檢查MySQL連接
   mysql -u wolfheluo -p ddos_system
   
   # 查看詳細錯誤
   sudo journalctl -u ddos-system-api -n 50
   ```

2. **VM客戶端連接失敗**
   ```bash
   # 測試網路連通性
   curl http://server-ip:5050/api/vms
   
   # 檢查防火牆
   sudo ufw status
   sudo iptables -L
   
   # 重新配置客戶端
   ./vm_slave.sh --config
   ```

3. **測試執行失敗**
   ```bash
   # 檢查hping3是否安裝
   which hping3
   
   # 檢查權限（hping3需要root權限進行某些測試）
   sudo ./vm_slave.sh
   
   # 查看詳細錯誤
   tail -f ~/vm_client.log
   ```

### 性能調優

1. **增加並發處理能力**
   - 調整MySQL max_connections
   - 使用Nginx負載均衡
   - 增加API服務器實例

2. **優化測試性能**
   - 調整hping3參數
   - 分批執行大量測試
   - 合理設置心跳間隔

## 📊 監控和統計

### Web界面統計
- 在線VM數量
- 任務執行統計
- 實時狀態監控
- 歷史測試記錄

### API統計接口
```bash
curl http://server:5050/api/stats
```

## 🔒 安全考慮

1. **網路安全**
   - 使用防火牆限制訪問
   - 考慮使用HTTPS
   - API認證（可擴展）

2. **系統安全**
   - 定期更新系統
   - 使用非root用戶運行客戶端
   - 監控異常連接

## 📝 開發說明

### API接口文檔

完整的API文檔請參考：[API接口文檔](ddos.md#api接口文檔)

### 擴展功能

系統設計為模塊化，可以輕鬆添加：
- 新的測試類型
- 更多的統計功能
- 測試結果導出
- 郵件通知
- 定時任務

## 📄 許可證

[在此添加許可證信息]

## 🤝 貢獻

歡迎提交Issue和Pull Request來改進這個項目。

## 📞 支持

如有問題，請通過以下方式聯繫：
- 創建Issue
- 發送郵件至 [your-email]

---

**注意**: 本系統僅用於合法的網路測試目的，請遵守相關法律法規，不得用於非法攻擊。
