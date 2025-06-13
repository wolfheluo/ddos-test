#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, render_template, jsonify
import psutil
import time
import threading
import os
import socket
import struct
from collections import defaultdict, Counter
from datetime import datetime

app = Flask(__name__)

# 全局變數來追蹤連接數和流量
connection_count = 0
traffic_data = {
    'bytes_sent': 0,
    'bytes_recv': 0,
    'start_time': time.time()
}

# 記錄程式啟動時的基準流量
baseline_traffic = None

# 全局IP流量追蹤器
ip_traffic_tracker = defaultdict(lambda: {
    'bytes_sent': 0,
    'bytes_recv': 0,
    'packets_sent': 0,
    'packets_recv': 0,
    'connection_count': 0,
    'first_seen': time.time(),
    'last_seen': time.time(),
    'tcp_connections': 0,
    'udp_connections': 0,
    'ports_used': set(),
    'connection_history': []
})

# 上次網絡統計數據，用於計算差值
last_net_io = None

def initialize_baseline():
    """初始化基準流量數據"""
    global baseline_traffic
    if baseline_traffic is None:
        try:
            net_io = psutil.net_io_counters()
            baseline_traffic = {
                'bytes_sent': net_io.bytes_sent,
                'bytes_recv': net_io.bytes_recv,
                'packets_sent': net_io.packets_sent,
                'packets_recv': net_io.packets_recv
            }
            print(f"已設定流量基準值 - 發送: {baseline_traffic['bytes_sent']} 字節, 接收: {baseline_traffic['bytes_recv']} 字節")
        except Exception as e:
            print(f"初始化基準流量失敗: {e}")
            baseline_traffic = {'bytes_sent': 0, 'bytes_recv': 0, 'packets_sent': 0, 'packets_recv': 0}

def update_ip_traffic_stats():
    """更新IP流量統計"""
    global last_net_io, ip_traffic_tracker
    
    try:
        current_net_io = psutil.net_io_counters()
        connections = psutil.net_connections(kind='inet')
        current_time = time.time()
        
        # 如果是第一次運行，初始化上次數據
        if last_net_io is None:
            last_net_io = current_net_io
            return
        
        # 計算流量差值
        bytes_sent_diff = current_net_io.bytes_sent - last_net_io.bytes_sent
        bytes_recv_diff = current_net_io.bytes_recv - last_net_io.bytes_recv
        packets_sent_diff = current_net_io.packets_sent - last_net_io.packets_sent
        packets_recv_diff = current_net_io.packets_recv - last_net_io.packets_recv
        
        # 獲取當前所有活躍的IP
        active_ips = set()
        ip_connection_counts = defaultdict(lambda: {'tcp': 0, 'udp': 0, 'ports': set()})
        
        for conn in connections:
            if conn.raddr and conn.raddr.ip:
                remote_ip = conn.raddr.ip
                active_ips.add(remote_ip)
                
                # 更新連接統計
                if conn.type == socket.SOCK_STREAM:
                    ip_connection_counts[remote_ip]['tcp'] += 1
                elif conn.type == socket.SOCK_DGRAM:
                    ip_connection_counts[remote_ip]['udp'] += 1
                
                ip_connection_counts[remote_ip]['ports'].add(conn.raddr.port)
                
                # 更新IP追蹤器
                ip_traffic_tracker[remote_ip]['last_seen'] = current_time
                ip_traffic_tracker[remote_ip]['tcp_connections'] = ip_connection_counts[remote_ip]['tcp']
                ip_traffic_tracker[remote_ip]['udp_connections'] = ip_connection_counts[remote_ip]['udp']
                ip_traffic_tracker[remote_ip]['ports_used'].update(ip_connection_counts[remote_ip]['ports'])
                
                # 如果是新IP，記錄首次見到的時間
                if remote_ip not in ip_traffic_tracker or ip_traffic_tracker[remote_ip]['first_seen'] == current_time:
                    ip_traffic_tracker[remote_ip]['first_seen'] = current_time
        
        # 根據活躍連接數分配流量（簡化估算）
        if active_ips and (bytes_sent_diff > 0 or bytes_recv_diff > 0):
            # 計算每個IP的權重（基於連接數）
            total_connections = sum(ip_connection_counts[ip]['tcp'] + ip_connection_counts[ip]['udp'] for ip in active_ips)
            
            if total_connections > 0:
                for ip in active_ips:
                    connection_weight = (ip_connection_counts[ip]['tcp'] + ip_connection_counts[ip]['udp']) / total_connections
                    
                    # 分配流量
                    estimated_sent = int(bytes_sent_diff * connection_weight)
                    estimated_recv = int(bytes_recv_diff * connection_weight)
                    estimated_packets_sent = int(packets_sent_diff * connection_weight)
                    estimated_packets_recv = int(packets_recv_diff * connection_weight)
                    
                    # 更新累計統計
                    ip_traffic_tracker[ip]['bytes_sent'] += estimated_sent
                    ip_traffic_tracker[ip]['bytes_recv'] += estimated_recv
                    ip_traffic_tracker[ip]['packets_sent'] += estimated_packets_sent
                    ip_traffic_tracker[ip]['packets_recv'] += estimated_packets_recv
                    
                    # 記錄歷史
                    if len(ip_traffic_tracker[ip]['connection_history']) > 100:  # 限制歷史記錄數量
                        ip_traffic_tracker[ip]['connection_history'].pop(0)
                    
                    ip_traffic_tracker[ip]['connection_history'].append({
                        'timestamp': current_time,
                        'bytes_sent': estimated_sent,
                        'bytes_recv': estimated_recv,
                        'tcp_connections': ip_connection_counts[ip]['tcp'],
                        'udp_connections': ip_connection_counts[ip]['udp']
                    })
        
        # 更新上次統計數據
        last_net_io = current_net_io
        
    except Exception as e:
        print(f"更新IP流量統計時發生錯誤: {e}")

def get_network_stats():
    """獲取詳細的網絡統計信息"""
    try:
        # 初始化基準流量（如果還沒有初始化）
        initialize_baseline()
        
        # 更新IP流量統計
        update_ip_traffic_stats()
        
        # 獲取網絡IO統計
        net_io = psutil.net_io_counters()
        
        # 計算相對於程式啟動時的增量流量
        current_bytes_sent = net_io.bytes_sent - baseline_traffic['bytes_sent']
        current_bytes_recv = net_io.bytes_recv - baseline_traffic['bytes_recv']
        current_packets_sent = net_io.packets_sent - baseline_traffic['packets_sent']
        current_packets_recv = net_io.packets_recv - baseline_traffic['packets_recv']
        
        # 確保不會出現負數（防止計數器重置）
        current_bytes_sent = max(0, current_bytes_sent)
        current_bytes_recv = max(0, current_bytes_recv)
        current_packets_sent = max(0, current_packets_sent)
        current_packets_recv = max(0, current_packets_recv)
        
        # 獲取所有網絡連接
        connections = psutil.net_connections(kind='inet')
        
        # 統計連接狀態
        tcp_connections = [conn for conn in connections if conn.type == socket.SOCK_STREAM]
        udp_connections = [conn for conn in connections if conn.type == socket.SOCK_DGRAM]
        
        # TCP 連接狀態統計
        tcp_status_counts = Counter(conn.status for conn in tcp_connections if conn.status)
        established_connections = tcp_status_counts.get('ESTABLISHED', 0)
        syn_sent_recv = tcp_status_counts.get('SYN_SENT', 0) + tcp_status_counts.get('SYN_RECV', 0)
        
        # 按來源IP統計（使用全局追蹤器）
        ip_stats = {}
        current_time = time.time()
        
        for ip, tracker_data in ip_traffic_tracker.items():
            # 計算連接持續時間
            duration = current_time - tracker_data['first_seen']
            
            # 計算平均速率
            avg_send_rate = tracker_data['bytes_sent'] / duration if duration > 0 else 0
            avg_recv_rate = tracker_data['bytes_recv'] / duration if duration > 0 else 0
            
            ip_stats[ip] = {
                'tcp_connections': tracker_data['tcp_connections'],
                'udp_connections': tracker_data['udp_connections'],
                'total_connections': tracker_data['tcp_connections'] + tracker_data['udp_connections'],
                'bytes_sent': tracker_data['bytes_sent'],
                'bytes_recv': tracker_data['bytes_recv'],
                'total_bytes': tracker_data['bytes_sent'] + tracker_data['bytes_recv'],
                'packets_sent': tracker_data['packets_sent'],
                'packets_recv': tracker_data['packets_recv'],
                'total_packets': tracker_data['packets_sent'] + tracker_data['packets_recv'],
                'ports_used': list(tracker_data['ports_used']),
                'first_seen': tracker_data['first_seen'],
                'last_seen': tracker_data['last_seen'],
                'duration': duration,
                'avg_send_rate': avg_send_rate,
                'avg_recv_rate': avg_recv_rate,
                'connection_history': tracker_data['connection_history'][-10:]  # 只返回最近10條記錄
            }
        
        # 計算運行時間
        uptime = time.time() - traffic_data['start_time']
          # 計算平均封包大小（估算）
        avg_tcp_packet_size = 0
        avg_udp_packet_size = 0
        
        if current_packets_sent > 0:
            avg_tcp_packet_size = int(current_bytes_sent * 0.7 / (current_packets_sent * 0.7)) if current_packets_sent > 0 else 0
            avg_udp_packet_size = int(current_bytes_sent * 0.3 / (current_packets_sent * 0.3)) if current_packets_sent > 0 else 0
        
        return {
            'active_connections': established_connections,
            'tcp_connections': len(tcp_connections),
            'udp_connections': len(udp_connections),
            'tcp_established': established_connections,
            'tcp_half_open': syn_sent_recv,
            'tcp_status_counts': dict(tcp_status_counts),
            'bytes_sent': current_bytes_sent,
            'bytes_recv': current_bytes_recv,
            'packets_sent': current_packets_sent,
            'packets_recv': current_packets_recv,
            'avg_tcp_packet_size': avg_tcp_packet_size,
            'avg_udp_packet_size': avg_udp_packet_size,
            'uptime': uptime,
            'uptime_formatted': str(int(uptime // 3600)) + "h " + str(int((uptime % 3600) // 60)) + "m " + str(int(uptime % 60)) + "s",
            'ip_stats': ip_stats,
            'total_tracked_ips': len(ip_stats),
            'baseline_info': {
                'baseline_bytes_sent': baseline_traffic['bytes_sent'],
                'baseline_bytes_recv': baseline_traffic['bytes_recv'],
                'system_total_sent': net_io.bytes_sent,
                'system_total_recv': net_io.bytes_recv
            }
        }
    except Exception as e:
        print(f"Error getting network stats: {e}")
        return {
            'active_connections': 0,
            'tcp_connections': 0,
            'udp_connections': 0,
            'tcp_established': 0,
            'tcp_half_open': 0,
            'tcp_status_counts': {},
            'bytes_sent': 0,
            'bytes_recv': 0,
            'packets_sent': 0,
            'packets_recv': 0,
            'avg_tcp_packet_size': 0,
            'avg_udp_packet_size': 0,
            'uptime': 0,
            'uptime_formatted': "0s",
            'ip_stats': {},
            'total_tracked_ips': 0
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
        'tcp_connections': stats['tcp_connections'],
        'udp_connections': stats['udp_connections'],
        'tcp_established': stats['tcp_established'],
        'tcp_half_open': stats['tcp_half_open'],
        'tcp_status_counts': stats['tcp_status_counts'],
        'bytes_sent': stats['bytes_sent'],
        'bytes_recv': stats['bytes_recv'],
        'bytes_sent_formatted': format_bytes(stats['bytes_sent']),
        'bytes_recv_formatted': format_bytes(stats['bytes_recv']),
        'total_traffic_formatted': format_bytes(stats['bytes_sent'] + stats['bytes_recv']),
        'packets_sent': stats['packets_sent'],
        'packets_recv': stats['packets_recv'],
        'avg_tcp_packet_size': stats['avg_tcp_packet_size'],
        'avg_udp_packet_size': stats['avg_udp_packet_size'],
        'avg_tcp_packet_size_formatted': format_bytes(stats['avg_tcp_packet_size']),
        'avg_udp_packet_size_formatted': format_bytes(stats['avg_udp_packet_size']),
        'uptime': stats['uptime'],        'uptime_formatted': stats['uptime_formatted'],
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'ip_stats': stats['ip_stats'],
        'baseline_info': stats.get('baseline_info', {})
    }
    
    return jsonify(formatted_stats)

@app.route('/api/ip-details')
def get_ip_details():
    """獲取詳細的IP連接和流量信息"""
    try:
        # 獲取最新的網絡統計
        stats = get_network_stats()
        ip_stats = stats['ip_stats']
        
        # 格式化IP詳細信息
        formatted_ip_details = {}
        
        for ip, details in ip_stats.items():
            formatted_ip_details[ip] = {
                'tcp_connections': details['tcp_connections'],
                'udp_connections': details['udp_connections'],
                'total_connections': details['total_connections'],
                'bytes_sent': details['bytes_sent'],
                'bytes_recv': details['bytes_recv'],
                'total_bytes': details['total_bytes'],
                'bytes_sent_formatted': format_bytes(details['bytes_sent']),
                'bytes_recv_formatted': format_bytes(details['bytes_recv']),
                'total_bytes_formatted': format_bytes(details['total_bytes']),
                'packets_sent': details['packets_sent'],
                'packets_recv': details['packets_recv'],
                'total_packets': details['total_packets'],
                'ports_used': details['ports_used'][:10],  # 限制顯示前10個端口
                'ports_count': len(details['ports_used']),
                'first_seen': datetime.fromtimestamp(details['first_seen']).strftime('%Y-%m-%d %H:%M:%S'),
                'last_seen': datetime.fromtimestamp(details['last_seen']).strftime('%Y-%m-%d %H:%M:%S'),
                'duration': details['duration'],
                'duration_formatted': f"{int(details['duration'] // 3600)}h {int((details['duration'] % 3600) // 60)}m {int(details['duration'] % 60)}s",
                'avg_send_rate': details['avg_send_rate'],
                'avg_recv_rate': details['avg_recv_rate'],
                'avg_send_rate_formatted': f"{format_bytes(details['avg_send_rate'])}/s",
                'avg_recv_rate_formatted': f"{format_bytes(details['avg_recv_rate'])}/s",
                'connection_history': details['connection_history']
            }
        
        # 按總流量排序
        sorted_ips = sorted(formatted_ip_details.items(), 
                          key=lambda x: x[1]['total_bytes'], 
                          reverse=True)
        
        return jsonify({
            'ip_details': dict(sorted_ips),
            'total_unique_ips': len(formatted_ip_details),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        
    except Exception as e:
        return jsonify({'error': str(e)})

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
