#!/bin/bash

# 網絡監控服務器啟動腳本

echo "正在啟動網絡監控服務器..."

# 檢查是否提供了端口參數
PORT=${1:-80}

# 如果使用80端口，檢查是否為root用戶
if [ "$PORT" -eq 80 ] && [ "$EUID" -ne 0 ]; then
    echo "警告: 需要root權限來綁定80端口"
    echo "請使用: sudo ./start.sh 80"
    echo "或者使用非特權端口: ./start.sh 8080"
    echo "或者: sudo python3 app.py"
    exit 1
fi

# 檢查Python3是否安裝
if ! command -v python3 &> /dev/null; then
    echo "錯誤: 未找到Python3，請先安裝Python3"
    exit 1
fi

# 檢查pip是否安裝
if ! command -v pip3 &> /dev/null; then
    echo "錯誤: 未找到pip3，請先安裝pip3"
    exit 1
fi

# 安裝依賴
echo "正在安裝Python依賴..."
pip3 install -r requirements.txt

# 修改app.py中的端口設置
if [ "$PORT" -ne 80 ]; then
    echo "設置端口為 $PORT"
    sed -i "s/port=80/port=$PORT/g" app.py
    sed -i "s/port=8080/port=$PORT/g" app.py
fi

# 啟動Flask應用
echo "正在啟動Flask服務器於端口$PORT..."
if [ "$PORT" -eq 80 ]; then
    echo "請在瀏覽器中訪問: http://localhost 或 http://your-server-ip"
else
    echo "請在瀏覽器中訪問: http://localhost:$PORT 或 http://your-server-ip:$PORT"
fi
echo "按 Ctrl+C 停止服務器"
echo ""

python3 app.py
