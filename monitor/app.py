#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, render_template, jsonify
import psutil
import time
import threading
import os
from datetime import datetime

app = Flask(__name__)

# 全局變數來追蹤連接數和流量
connection_count = 0
traffic_data = {
    'bytes_sent': 0,
    'bytes_recv': 0,
    'start_time': time.time()
}

def get_network_stats():
    """獲取網絡統計信息"""
    try:
        # 獲取網絡IO統計
        net_io = psutil.net_io_counters()
        
        # 獲取網絡連接數
        connections = psutil.net_connections()
        active_connections = len([conn for conn in connections if conn.status == 'ESTABLISHED'])
        
        # 計算運行時間
        uptime = time.time() - traffic_data['start_time']
        
        return {
            'active_connections': active_connections,
            'bytes_sent': net_io.bytes_sent,
            'bytes_recv': net_io.bytes_recv,
            'packets_sent': net_io.packets_sent,
            'packets_recv': net_io.packets_recv,
            'uptime': uptime,
            'uptime_formatted': str(int(uptime // 3600)) + "h " + str(int((uptime % 3600) // 60)) + "m " + str(int(uptime % 60)) + "s"
        }
    except Exception as e:
        print(f"Error getting network stats: {e}")
        return {
            'active_connections': 0,
            'bytes_sent': 0,
            'bytes_recv': 0,
            'packets_sent': 0,
            'packets_recv': 0,
            'uptime': 0,
            'uptime_formatted': "0s"
        }

def format_bytes(bytes_value):
    """格式化字節數為可讀格式"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024.0:
            return f"{bytes_value:.2f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.2f} PB"

@app.route('/')
def index():
    """主頁面"""
    return render_template('index.html')

@app.route('/api/stats')
def get_stats():
    """API端點，返回網絡統計JSON數據"""
    stats = get_network_stats()
    
    # 格式化流量數據
    formatted_stats = {
        'active_connections': stats['active_connections'],
        'bytes_sent': stats['bytes_sent'],
        'bytes_recv': stats['bytes_recv'],
        'bytes_sent_formatted': format_bytes(stats['bytes_sent']),
        'bytes_recv_formatted': format_bytes(stats['bytes_recv']),
        'total_traffic_formatted': format_bytes(stats['bytes_sent'] + stats['bytes_recv']),
        'packets_sent': stats['packets_sent'],
        'packets_recv': stats['packets_recv'],
        'uptime': stats['uptime'],
        'uptime_formatted': stats['uptime_formatted'],
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    return jsonify(formatted_stats)

@app.route('/api/system')
def get_system_info():
    """獲取系統信息"""
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        system_info = {
            'cpu_percent': cpu_percent,
            'memory_percent': memory.percent,
            'memory_used': format_bytes(memory.used),
            'memory_total': format_bytes(memory.total),
            'disk_percent': disk.percent,
            'disk_used': format_bytes(disk.used),
            'disk_total': format_bytes(disk.total)
        }
        
        return jsonify(system_info)
    except Exception as e:
        return jsonify({'error': str(e)})

if __name__ == '__main__':
    import sys
    
    # 從命令行參數或環境變數獲取端口號
    port = 8080  # 默認端口
    
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print("錯誤: 端口號必須是數字")
            sys.exit(1)
    elif 'PORT' in os.environ:
        try:
            port = int(os.environ['PORT'])
        except ValueError:
            print("錯誤: 環境變數PORT必須是數字")
            sys.exit(1)
    
    print(f"啟動Flask服务器在端口{port}...")
    if port == 80:
        print("請確保以root權限運行以綁定80端口")
        print("或者使用 sudo python3 app.py 80")
    
    # 設置Flask運行端口
    app.run(host='0.0.0.0', port=port, debug=False)
