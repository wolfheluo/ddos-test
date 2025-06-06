#!/usr/bin/env python3
"""
分散式網路測試系統 - API 服務器
"""
import os
import json
import uuid
import logging
import socket
import struct
import select
import subprocess
import platform
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv
import threading
import time

# 載入環境變數
load_dotenv()

# 配置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# 資料庫配置
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'wolfheluo'),
    'password': os.getenv('DB_PASSWORD', 'nasa0411'),
    'database': os.getenv('DB_NAME', 'ddos_system'),
    'charset': 'utf8mb4',
    'autocommit': True
}

API_PORT = int(os.getenv('API_PORT', 5050))
VM_HEARTBEAT_TIMEOUT = int(os.getenv('VM_HEARTBEAT_TIMEOUT', 120))

class LatencyMonitor:
    """延遲監測類"""
    
    def __init__(self):
        self.monitoring_tasks = {}
        self.monitor_threads = {}
    
    def start_monitoring(self, task_id, target_ip, target_port, test_type, duration):
        """開始監測目標延遲"""
        if task_id in self.monitoring_tasks:
            return False
        
        self.monitoring_tasks[task_id] = {
            'target_ip': target_ip,
            'target_port': target_port,
            'test_type': test_type,
            'duration': duration,
            'start_time': time.time(),
            'active': True
        }
        
        # 啟動監測線程
        thread = threading.Thread(
            target=self._monitor_target, 
            args=(task_id, target_ip, target_port, test_type, duration),
            daemon=True
        )
        thread.start()
        self.monitor_threads[task_id] = thread
        
        logger.info(f"開始監測任務 {task_id} 的目標 {target_ip}:{target_port}")
        return True
    
    def stop_monitoring(self, task_id):
        """停止監測"""
        if task_id in self.monitoring_tasks:
            self.monitoring_tasks[task_id]['active'] = False
            logger.info(f"停止監測任務 {task_id}")
    
    def _monitor_target(self, task_id, target_ip, target_port, test_type, duration):
        """監測目標的延遲響應"""
        start_time = time.time()
        interval = 1  # 每秒監測一次
        
        while (time.time() - start_time) < duration and self.monitoring_tasks.get(task_id, {}).get('active', False):
            try:
                response_time = None
                packet_loss = False
                error_message = None
                
                if test_type == 'TCP':
                    response_time, packet_loss, error_message = self._test_tcp(target_ip, target_port)
                elif test_type == 'UDP':
                    response_time, packet_loss, error_message = self._test_udp(target_ip, target_port)
                elif test_type == 'ICMP':
                    response_time, packet_loss, error_message = self._test_icmp(target_ip)
                
                # 記錄結果到資料庫
                self._save_monitoring_result(task_id, target_ip, target_port, test_type, 
                                            response_time, packet_loss, error_message)
                
            except Exception as e:
                logger.error(f"監測錯誤 (任務 {task_id}): {e}")
                self._save_monitoring_result(task_id, target_ip, target_port, test_type, 
                                            None, True, str(e))
            
            time.sleep(interval)
        
        # 清理
        if task_id in self.monitoring_tasks:
            del self.monitoring_tasks[task_id]
        if task_id in self.monitor_threads:
            del self.monitor_threads[task_id]
    
    def _test_tcp(self, target_ip, target_port, timeout=3):
        """TCP連接測試"""
        try:
            start_time = time.time()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            
            result = sock.connect_ex((target_ip, target_port))
            end_time = time.time()
            
            sock.close()
            
            if result == 0:
                response_time = (end_time - start_time) * 1000  # 轉換為毫秒
                return response_time, False, None
            else:
                return None, True, f"TCP連接失敗，錯誤碼: {result}"
                
        except Exception as e:
            return None, True, str(e)
    
    def _test_udp(self, target_ip, target_port, timeout=3):
        """UDP測試"""
        try:
            start_time = time.time()
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            
            # 發送測試數據
            test_data = b"ping"
            sock.sendto(test_data, (target_ip, target_port))
            
            # 嘗試接收回應
            try:
                data, addr = sock.recvfrom(1024)
                end_time = time.time()
                response_time = (end_time - start_time) * 1000
                sock.close()
                return response_time, False, None
            except socket.timeout:
                sock.close()
                return None, True, "UDP超時，無回應"
                
        except Exception as e:
            return None, True, str(e)
    
    def _test_icmp(self, target_ip, timeout=3):
        """ICMP Ping測試"""
        try:
            if platform.system().lower() == "windows":
                cmd = f"ping -n 1 -w {timeout*1000} {target_ip}"
            else:
                cmd = f"ping -c 1 -W {timeout} {target_ip}"
            
            start_time = time.time()
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout+1)
            end_time = time.time()
            
            if result.returncode == 0:
                # 解析ping輸出獲取延遲時間
                output = result.stdout
                if platform.system().lower() == "windows":
                    # Windows: time=XXXms
                    import re
                    match = re.search(r'time[<=](\d+)ms', output)
                    if match:
                        response_time = float(match.group(1))
                        return response_time, False, None
                else:
                    # Linux: time=XXX ms
                    import re
                    match = re.search(r'time=(\d+\.?\d*)\s*ms', output)
                    if match:
                        response_time = float(match.group(1))
                        return response_time, False, None
                
                # 如果無法解析時間，使用總耗時
                response_time = (end_time - start_time) * 1000
                return response_time, False, None
            else:
                return None, True, f"Ping失敗: {result.stderr}"
                
        except subprocess.TimeoutExpired:
            return None, True, "Ping超時"
        except Exception as e:
            return None, True, str(e)
    
    def _save_monitoring_result(self, task_id, target_ip, target_port, test_type, 
                              response_time, packet_loss, error_message):
        """保存監測結果到資料庫"""
        try:
            conn = get_db_connection()
            if not conn:
                return
            
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO master_monitoring 
                   (task_id, target_ip, target_port, test_type, response_time, packet_loss, error_message)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (task_id, target_ip, target_port, test_type, response_time, packet_loss, error_message)
            )
            conn.close()
            
        except Exception as e:
            logger.error(f"保存監測結果失敗: {e}")

# 創建全局監測器實例
latency_monitor = LatencyMonitor()

def get_db_connection():
    """獲取資料庫連接"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Error as e:
        logger.error(f"資料庫連接錯誤: {e}")
        return None

def cleanup_offline_vms():
    """清理離線的VM"""
    while True:
        try:
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                timeout_time = datetime.now() - timedelta(seconds=VM_HEARTBEAT_TIMEOUT)
                cursor.execute(
                    "UPDATE vms SET status = 'offline' WHERE last_heartbeat < %s AND status = 'online'",
                    (timeout_time,)
                )
                conn.close()
        except Exception as e:
            logger.error(f"清理離線VM錯誤: {e}")
        time.sleep(30)  # 每30秒檢查一次

# 啟動背景清理任務
cleanup_thread = threading.Thread(target=cleanup_offline_vms, daemon=True)
cleanup_thread.start()

# VM 管理 API
@app.route('/api/vm/connect', methods=['POST'])
def vm_connect():
    """VM註冊"""
    try:
        data = request.get_json()
        vm_id = data.get('vm_id')
        ip_address = data.get('ip_address')
        hostname = data.get('hostname', '')
        
        if not vm_id or not ip_address:
            return jsonify({'success': False, 'message': '缺少必要參數'}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({'success': False, 'message': '資料庫連接失敗'}), 500
        
        cursor = conn.cursor()
        
        # 檢查VM是否已存在
        cursor.execute("SELECT id FROM vms WHERE vm_id = %s", (vm_id,))
        existing = cursor.fetchone()
        
        if existing:
            # 更新現有VM
            cursor.execute(
                "UPDATE vms SET ip_address = %s, hostname = %s, status = 'online', last_heartbeat = NOW() WHERE vm_id = %s",
                (ip_address, hostname, vm_id)
            )
        else:
            # 插入新VM
            cursor.execute(
                "INSERT INTO vms (vm_id, ip_address, hostname, status) VALUES (%s, %s, %s, 'online')",
                (vm_id, ip_address, hostname)
            )
        
        conn.close()
        logger.info(f"VM {vm_id} 已連接，IP: {ip_address}")
        return jsonify({'success': True, 'message': 'VM註冊成功'})
        
    except Exception as e:
        logger.error(f"VM連接錯誤: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/vm/heartbeat', methods=['POST'])
def vm_heartbeat():
    """更新VM心跳"""
    try:
        data = request.get_json()
        vm_id = data.get('vm_id')
        
        if not vm_id:
            return jsonify({'success': False, 'message': '缺少VM ID'}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({'success': False, 'message': '資料庫連接失敗'}), 500
        
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE vms SET last_heartbeat = NOW(), status = 'online' WHERE vm_id = %s",
            (vm_id,)
        )
        
        conn.close()
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"心跳更新錯誤: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/vm/disconnect', methods=['POST'])
def vm_disconnect():
    """VM下線"""
    try:
        data = request.get_json()
        vm_id = data.get('vm_id')
        
        if not vm_id:
            return jsonify({'success': False, 'message': '缺少VM ID'}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({'success': False, 'message': '資料庫連接失敗'}), 500
        
        cursor = conn.cursor()
        cursor.execute("UPDATE vms SET status = 'offline' WHERE vm_id = %s", (vm_id,))
        
        conn.close()
        logger.info(f"VM {vm_id} 已下線")
        return jsonify({'success': True, 'message': 'VM下線成功'})
        
    except Exception as e:
        logger.error(f"VM下線錯誤: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/vms', methods=['GET'])
def get_vms():
    """獲取在線VM列表"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'success': False, 'message': '資料庫連接失敗'}), 500
        
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT vm_id, ip_address, hostname, status, last_heartbeat FROM vms ORDER BY last_heartbeat DESC"
        )
        vms = cursor.fetchall()
        
        # 轉換datetime為字符串
        for vm in vms:
            if vm['last_heartbeat']:
                vm['last_heartbeat'] = vm['last_heartbeat'].isoformat()
        
        conn.close()
        return jsonify({'success': True, 'data': vms})
        
    except Exception as e:
        logger.error(f"獲取VM列表錯誤: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# 任務管理 API
@app.route('/api/tasks/create', methods=['POST'])
def create_task():
    """創建測試任務"""
    try:
        data = request.get_json()
        
        # 驗證必要參數
        required_fields = ['target_ip', 'target_port', 'test_type']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'message': f'缺少參數: {field}'}), 400
        
        task_id = str(uuid.uuid4())
        target_ip = data['target_ip']
        target_port = int(data['target_port'])
        test_type = data['test_type'].upper()
        packet_size = int(data.get('packet_size', 64))
        connection_count = int(data.get('connection_count', 100))
        duration = int(data.get('duration', 30))
        assigned_vms = data.get('assigned_vms', [])
        
        if test_type not in ['TCP', 'UDP', 'ICMP']:
            return jsonify({'success': False, 'message': '無效的測試類型'}), 400
        
        # 如果沒有指定VM，則使用所有在線VM
        if not assigned_vms:
            conn = get_db_connection()
            if not conn:
                return jsonify({'success': False, 'message': '資料庫連接失敗'}), 500
            
            cursor = conn.cursor()
            cursor.execute("SELECT vm_id FROM vms WHERE status = 'online'")
            assigned_vms = [row[0] for row in cursor.fetchall()]
            conn.close()
        
        if not assigned_vms:
            return jsonify({'success': False, 'message': '沒有可用的在線VM'}), 400
        
        # 創建任務
        conn = get_db_connection()
        if not conn:
            return jsonify({'success': False, 'message': '資料庫連接失敗'}), 500
        
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO tasks (task_id, target_ip, target_port, test_type, packet_size, 
               connection_count, duration, assigned_vms, status) 
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending')""",
            (task_id, target_ip, target_port, test_type, packet_size, 
             connection_count, duration, json.dumps(assigned_vms))
        )
        
        # 為每個VM創建任務分配記錄
        for vm_id in assigned_vms:
            cursor.execute(
                "INSERT INTO vm_tasks (vm_id, task_id, status) VALUES (%s, %s, 'pending')",
                (vm_id, task_id)
            )
            
            # 創建初始結果記錄
            cursor.execute(
                "INSERT INTO task_results (task_id, vm_id, status) VALUES (%s, %s, 'pending')",
                (task_id, vm_id)
            )
          conn.close()
        
        # 啟動master端延遲監測
        latency_monitor.start_monitoring(task_id, target_ip, target_port, test_type, duration)
        
        logger.info(f"任務 {task_id} 已創建，分配給 {len(assigned_vms)} 個VM，並啟動master端監測")
        return jsonify({
            'success': True, 
            'message': '任務創建成功，已啟動延遲監測',
            'task_id': task_id,
            'assigned_vms': assigned_vms
        })
        
    except Exception as e:
        logger.error(f"創建任務錯誤: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/tasks/pending/<vm_id>', methods=['GET'])
def get_pending_tasks(vm_id):
    """獲取VM的待執行任務"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'success': False, 'message': '資料庫連接失敗'}), 500
        
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT t.task_id, t.target_ip, t.target_port, t.test_type, 
               t.packet_size, t.connection_count, t.duration
               FROM tasks t 
               JOIN vm_tasks vt ON t.task_id = vt.task_id 
               WHERE vt.vm_id = %s AND vt.status = 'pending'
               ORDER BY t.created_at ASC""",
            (vm_id,)
        )
        tasks = cursor.fetchall()
        
        # 標記任務為已分配
        if tasks:
            task_ids = [task['task_id'] for task in tasks]
            placeholders = ','.join(['%s'] * len(task_ids))
            cursor.execute(
                f"UPDATE vm_tasks SET status = 'assigned' WHERE vm_id = %s AND task_id IN ({placeholders})",
                [vm_id] + task_ids
            )
        
        conn.close()
        return jsonify({'success': True, 'data': tasks})
        
    except Exception as e:
        logger.error(f"獲取待執行任務錯誤: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/tasks/result', methods=['POST'])
def submit_task_result():
    """提交任務結果"""
    try:
        data = request.get_json()
        task_id = data.get('task_id')
        vm_id = data.get('vm_id')
        
        if not task_id or not vm_id:
            return jsonify({'success': False, 'message': '缺少必要參數'}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({'success': False, 'message': '資料庫連接失敗'}), 500
        
        cursor = conn.cursor()
        
        # 更新任務結果
        update_fields = []
        update_values = []
        
        if 'status' in data:
            update_fields.append('status = %s')
            update_values.append(data['status'])
        
        if 'packets_sent' in data:
            update_fields.append('packets_sent = %s')
            update_values.append(int(data['packets_sent']))
        
        if 'packets_received' in data:
            update_fields.append('packets_received = %s')
            update_values.append(int(data['packets_received']))
        
        if 'packet_loss_rate' in data:
            update_fields.append('packet_loss_rate = %s')
            update_values.append(float(data['packet_loss_rate']))
        
        if 'avg_response_time' in data:
            update_fields.append('avg_response_time = %s')
            update_values.append(float(data['avg_response_time']))
        
        if 'min_response_time' in data:
            update_fields.append('min_response_time = %s')
            update_values.append(float(data['min_response_time']))
        
        if 'max_response_time' in data:
            update_fields.append('max_response_time = %s')
            update_values.append(float(data['max_response_time']))
        
        if 'error_message' in data:
            update_fields.append('error_message = %s')
            update_values.append(data['error_message'])
        
        if data.get('status') == 'running':
            update_fields.append('started_at = NOW()')
        elif data.get('status') in ['completed', 'failed']:
            update_fields.append('completed_at = NOW()')
        
        if update_fields:
            update_values.extend([task_id, vm_id])
            cursor.execute(
                f"UPDATE task_results SET {', '.join(update_fields)} WHERE task_id = %s AND vm_id = %s",
                update_values
            )
        
        # 更新VM任務狀態
        if 'status' in data:
            cursor.execute(
                "UPDATE vm_tasks SET status = %s WHERE task_id = %s AND vm_id = %s",
                (data['status'], task_id, vm_id)
            )
        
        # 檢查任務是否完成
        cursor.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN status IN ('completed', 'failed') THEN 1 ELSE 0 END) as finished FROM vm_tasks WHERE task_id = %s",
            (task_id,)
        )
        result = cursor.fetchone()
          if result and result[0] == result[1]:  # 所有VM都完成了
            cursor.execute("UPDATE tasks SET status = 'completed' WHERE task_id = %s", (task_id,))
            # 停止master端監測
            latency_monitor.stop_monitoring(task_id)
            logger.info(f"任務 {task_id} 已完成，停止master端監測")
        
        conn.close()
        return jsonify({'success': True, 'message': '結果提交成功'})
        
    except Exception as e:
        logger.error(f"提交任務結果錯誤: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/tasks/<task_id>/status', methods=['GET'])
def get_task_status(task_id):
    """查詢任務狀態"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'success': False, 'message': '資料庫連接失敗'}), 500
        
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM tasks WHERE task_id = %s",
            (task_id,)
        )
        task = cursor.fetchone()
        
        if not task:
            return jsonify({'success': False, 'message': '任務不存在'}), 404
        
        # 獲取VM狀態
        cursor.execute(
            "SELECT vm_id, status FROM vm_tasks WHERE task_id = %s",
            (task_id,)
        )
        vm_status = cursor.fetchall()
        
        # 轉換datetime為字符串
        if task['created_at']:
            task['created_at'] = task['created_at'].isoformat()
        if task['updated_at']:
            task['updated_at'] = task['updated_at'].isoformat()
        
        task['assigned_vms'] = json.loads(task['assigned_vms']) if task['assigned_vms'] else []
        task['vm_status'] = vm_status
        
        conn.close()
        return jsonify({'success': True, 'data': task})
        
    except Exception as e:
        logger.error(f"查詢任務狀態錯誤: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/tasks/<task_id>/results', methods=['GET'])
def get_task_results(task_id):
    """獲取任務結果"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'success': False, 'message': '資料庫連接失敗'}), 500
        
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM task_results WHERE task_id = %s ORDER BY vm_id",
            (task_id,)
        )
        results = cursor.fetchall()
        
        # 轉換datetime為字符串
        for result in results:
            for field in ['started_at', 'completed_at', 'created_at']:
                if result[field]:
                    result[field] = result[field].isoformat()
        
        conn.close()
        return jsonify({'success': True, 'data': results})
        
    except Exception as e:
        logger.error(f"獲取任務結果錯誤: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/tasks/<task_id>/master-monitoring', methods=['GET'])
def get_master_monitoring(task_id):
    """獲取master端監測數據"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'success': False, 'message': '資料庫連接失敗'}), 500
        
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT response_time, packet_loss, error_message, timestamp 
               FROM master_monitoring 
               WHERE task_id = %s 
               ORDER BY timestamp ASC""",
            (task_id,)
        )
        monitoring_data = cursor.fetchall()
        
        # 轉換datetime為字符串
        for data in monitoring_data:
            if data['timestamp']:
                data['timestamp'] = data['timestamp'].isoformat()
        
        # 計算統計數據
        stats = {}
        if monitoring_data:
            response_times = [d['response_time'] for d in monitoring_data if d['response_time'] is not None]
            packet_losses = [d['packet_loss'] for d in monitoring_data]
            
            if response_times:
                stats = {
                    'avg_response_time': sum(response_times) / len(response_times),
                    'min_response_time': min(response_times),
                    'max_response_time': max(response_times),
                    'packet_loss_rate': (sum(packet_losses) / len(packet_losses)) * 100,
                    'total_samples': len(monitoring_data),
                    'successful_samples': len(response_times)
                }
        
        conn.close()
        return jsonify({
            'success': True, 
            'data': {
                'monitoring_data': monitoring_data,
                'statistics': stats
            }
        })
        
    except Exception as e:
        logger.error(f"獲取master監測數據錯誤: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/monitoring/realtime/<task_id>', methods=['GET'])
def get_realtime_monitoring(task_id):
    """獲取實時監測數據（最近10條記錄）"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'success': False, 'message': '資料庫連接失敗'}), 500
        
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT response_time, packet_loss, error_message, timestamp 
               FROM master_monitoring 
               WHERE task_id = %s 
               ORDER BY timestamp DESC 
               LIMIT 10""",
            (task_id,)
        )
        recent_data = cursor.fetchall()
        
        # 轉換datetime為字符串
        for data in recent_data:
            if data['timestamp']:
                data['timestamp'] = data['timestamp'].isoformat()
        
        # 獲取監測狀態
        is_monitoring = task_id in latency_monitor.monitoring_tasks
        
        conn.close()
        return jsonify({
            'success': True, 
            'data': {
                'recent_data': recent_data,
                'is_monitoring': is_monitoring
            }
        })
        
    except Exception as e:
        logger.error(f"獲取實時監測數據錯誤: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    """獲取任務列表"""
    try:
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        
        conn = get_db_connection()
        if not conn:
            return jsonify({'success': False, 'message': '資料庫連接失敗'}), 500
        
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (limit, offset)
        )
        tasks = cursor.fetchall()
        
        # 轉換數據類型
        for task in tasks:
            if task['created_at']:
                task['created_at'] = task['created_at'].isoformat()
            if task['updated_at']:
                task['updated_at'] = task['updated_at'].isoformat()
            task['assigned_vms'] = json.loads(task['assigned_vms']) if task['assigned_vms'] else []
        
        conn.close()
        return jsonify({'success': True, 'data': tasks})
        
    except Exception as e:
        logger.error(f"獲取任務列表錯誤: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """獲取系統統計信息"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'success': False, 'message': '資料庫連接失敗'}), 500
        
        cursor = conn.cursor(dictionary=True)
        
        # VM統計
        cursor.execute("SELECT status, COUNT(*) as count FROM vms GROUP BY status")
        vm_stats = {row['status']: row['count'] for row in cursor.fetchall()}
        
        # 任務統計
        cursor.execute("SELECT status, COUNT(*) as count FROM tasks GROUP BY status")
        task_stats = {row['status']: row['count'] for row in cursor.fetchall()}
        
        # 今日任務數
        cursor.execute("SELECT COUNT(*) as count FROM tasks WHERE DATE(created_at) = CURDATE()")
        today_tasks = cursor.fetchone()['count']
        
        conn.close()
        
        stats = {
            'vms': vm_stats,
            'tasks': task_stats,
            'today_tasks': today_tasks,
            'total_vms': sum(vm_stats.values()),
            'total_tasks': sum(task_stats.values())
        }
        
        return jsonify({'success': True, 'data': stats})
        
    except Exception as e:
        logger.error(f"獲取統計信息錯誤: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# Web界面
@app.route('/')
def index():
    """主頁面"""
    return render_template_string('''
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>分散式網路測試系統</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .header { background: #2c3e50; color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
        .card { background: white; border-radius: 10px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .form-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; font-weight: bold; color: #333; }
        input, select, textarea { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 5px; font-size: 14px; }
        button { background: #3498db; color: white; padding: 12px 24px; border: none; border-radius: 5px; cursor: pointer; font-size: 14px; }
        button:hover { background: #2980b9; }
        button:disabled { background: #bdc3c7; cursor: not-allowed; }
        .btn-danger { background: #e74c3c; }
        .btn-danger:hover { background: #c0392b; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .status { padding: 5px 10px; border-radius: 15px; font-size: 12px; font-weight: bold; }
        .status.online { background: #27ae60; color: white; }
        .status.offline { background: #e74c3c; color: white; }
        .status.pending { background: #f39c12; color: white; }
        .status.running { background: #3498db; color: white; }
        .status.completed { background: #27ae60; color: white; }
        .status.failed { background: #e74c3c; color: white; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #eee; }
        th { background: #f8f9fa; font-weight: bold; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }
        .stat-card { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; text-align: center; }
        .stat-number { font-size: 2em; font-weight: bold; margin-bottom: 5px; }
        .refresh-btn { float: right; background: #95a5a6; }
        .refresh-btn:hover { background: #7f8c8d; }
        .loading { text-align: center; padding: 20px; color: #666; }
        .error { background: #e74c3c; color: white; padding: 10px; border-radius: 5px; margin: 10px 0; }
        .success { background: #27ae60; color: white; padding: 10px; border-radius: 5px; margin: 10px 0; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 分散式網路測試系統</h1>
            <p>管理和監控分散式網路測試任務</p>
        </div>

        <!-- 系統統計 -->
        <div class="card">
            <h2>📊 系統統計</h2>
            <div class="stats" id="stats">
                <div class="loading">載入統計數據中...</div>
            </div>
        </div>

        <div class="grid">
            <!-- 創建測試任務 -->
            <div class="card">
                <h2>⚡ 創建測試任務</h2>
                <form id="taskForm">
                    <div class="form-group">
                        <label for="targetIp">目標IP地址:</label>
                        <input type="text" id="targetIp" name="target_ip" placeholder="例: 8.8.8.8" required>
                    </div>
                    
                    <div class="form-group">
                        <label for="targetPort">目標端口:</label>
                        <input type="number" id="targetPort" name="target_port" value="80" min="1" max="65535" required>
                    </div>
                    
                    <div class="form-group">
                        <label for="testType">測試類型:</label>
                        <select id="testType" name="test_type" required>
                            <option value="TCP">TCP</option>
                            <option value="UDP">UDP</option>
                            <option value="ICMP">ICMP</option>
                        </select>
                    </div>
                    
                    <div class="form-group">
                        <label for="packetSize">數據包大小 (bytes):</label>
                        <input type="number" id="packetSize" name="packet_size" value="64" min="1" max="65507">
                        <small style="color: #666; font-size: 12px;">僅適用於UDP和ICMP測試</small>
                    </div>
                    
                    <div class="form-group">
                        <label for="connectionCount">並發連接數 (同時建立的session數):</label>
                        <input type="number" id="connectionCount" name="connection_count" value="100" min="1" max="10000">
                        <small style="color: #666; font-size: 12px;">測試目標服務器的連接承載能力，每個連接將保持活躍直到測試結束</small>
                    </div>
                    
                    <div class="form-group">
                        <label for="duration">持續時間 (秒):</label>
                        <input type="number" id="duration" name="duration" value="30" min="1" max="300">
                        <small style="color: #666; font-size: 12px;">連接保持活躍的時間</small>
                    </div>
                    
                    <div class="form-group">
                        <label for="assignedVms">指定VM (留空使用所有在線VM):</label>
                        <textarea id="assignedVms" name="assigned_vms" placeholder="一行一個VM ID，例:&#10;vm-001&#10;vm-002"></textarea>
                    </div>
                    
                    <button type="submit" id="startTestBtn">🎯 開始測試</button>
                </form>
            </div>

            <!-- 在線VM -->
            <div class="card">
                <h2>💻 在線VM 
                    <button class="refresh-btn" onclick="loadVms()">🔄 刷新</button>
                </h2>
                <div id="vmsList">
                    <div class="loading">載入VM列表中...</div>
                </div>
            </div>
        </div>

        <!-- 最近任務 -->
        <div class="card">
            <h2>📋 最近任務
                <button class="refresh-btn" onclick="loadTasks()">🔄 刷新</button>
            </h2>
            <div id="tasksList">
                <div class="loading">載入任務列表中...</div>
            </div>
        </div>
    </div>

    <script>
        // 全局變數
        let refreshIntervals = [];

        // 頁面載入時初始化
        document.addEventListener('DOMContentLoaded', function() {
            loadStats();
            loadVms();
            loadTasks();
            
            // 設置自動刷新
            refreshIntervals.push(setInterval(loadStats, 30000));
            refreshIntervals.push(setInterval(loadVms, 10000));
            refreshIntervals.push(setInterval(loadTasks, 15000));
            
            // 綁定表單提交事件
            document.getElementById('taskForm').addEventListener('submit', createTask);
        });

        // 載入統計數據
        async function loadStats() {
            try {
                const response = await fetch('/api/stats');
                const result = await response.json();
                
                if (result.success) {
                    const stats = result.data;
                    document.getElementById('stats').innerHTML = `
                        <div class="stat-card">
                            <div class="stat-number">${stats.vms.online || 0}</div>
                            <div>在線VM</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">${stats.total_vms || 0}</div>
                            <div>總VM數</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">${stats.tasks.running || 0}</div>
                            <div>運行中任務</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">${stats.today_tasks || 0}</div>
                            <div>今日任務</div>
                        </div>
                    `;
                } else {
                    document.getElementById('stats').innerHTML = '<div class="error">載入統計數據失敗</div>';
                }
            } catch (error) {
                document.getElementById('stats').innerHTML = '<div class="error">載入統計數據失敗</div>';
            }
        }

        // 載入VM列表
        async function loadVms() {
            try {
                const response = await fetch('/api/vms');
                const result = await response.json();
                
                if (result.success) {
                    const vms = result.data;
                    if (vms.length === 0) {
                        document.getElementById('vmsList').innerHTML = '<p>暫無在線VM</p>';
                        return;
                    }
                    
                    let html = '<table><thead><tr><th>VM ID</th><th>IP地址</th><th>主機名</th><th>狀態</th><th>最後心跳</th></tr></thead><tbody>';
                    vms.forEach(vm => {
                        const lastHeartbeat = vm.last_heartbeat ? new Date(vm.last_heartbeat).toLocaleString() : '無';
                        html += `
                            <tr>
                                <td>${vm.vm_id}</td>
                                <td>${vm.ip_address}</td>
                                <td>${vm.hostname || '未知'}</td>
                                <td><span class="status ${vm.status}">${vm.status === 'online' ? '在線' : '離線'}</span></td>
                                <td>${lastHeartbeat}</td>
                            </tr>
                        `;
                    });
                    html += '</tbody></table>';
                    document.getElementById('vmsList').innerHTML = html;
                } else {
                    document.getElementById('vmsList').innerHTML = '<div class="error">載入VM列表失敗</div>';
                }
            } catch (error) {
                document.getElementById('vmsList').innerHTML = '<div class="error">載入VM列表失敗</div>';
            }
        }

        // 載入任務列表
        async function loadTasks() {
            try {
                const response = await fetch('/api/tasks?limit=20');
                const result = await response.json();
                
                if (result.success) {
                    const tasks = result.data;
                    if (tasks.length === 0) {
                        document.getElementById('tasksList').innerHTML = '<p>暫無任務記錄</p>';
                        return;
                    }
                    
                    let html = '<table><thead><tr><th>任務ID</th><th>目標</th><th>類型</th><th>狀態</th><th>VM數量</th><th>創建時間</th><th>操作</th></tr></thead><tbody>';
                    tasks.forEach(task => {
                        const createdAt = new Date(task.created_at).toLocaleString();
                        const vmCount = task.assigned_vms.length;
                        const statusText = {
                            'pending': '等待中',
                            'running': '運行中',
                            'completed': '已完成',
                            'failed': '失敗'
                        }[task.status] || task.status;
                        
                        html += `
                            <tr>
                                <td>${task.task_id.substring(0, 8)}...</td>
                                <td>${task.target_ip}:${task.target_port}</td>
                                <td>${task.test_type}</td>
                                <td><span class="status ${task.status}">${statusText}</span></td>
                                <td>${vmCount}</td>
                                <td>${createdAt}</td>
                                <td>
                                    <button onclick="viewTaskResults('${task.task_id}')" style="background: #27ae60; color: white; border: none; padding: 5px 10px; border-radius: 3px; cursor: pointer;">查看結果</button>
                                </td>
                            </tr>
                        `;
                    });
                    html += '</tbody></table>';
                    document.getElementById('tasksList').innerHTML = html;
                } else {
                    document.getElementById('tasksList').innerHTML = '<div class="error">載入任務列表失敗</div>';
                }
            } catch (error) {
                document.getElementById('tasksList').innerHTML = '<div class="error">載入任務列表失敗</div>';
            }
        }

        // 創建任務
        async function createTask(event) {
            event.preventDefault();
            
            const startBtn = document.getElementById('startTestBtn');
            startBtn.disabled = true;
            startBtn.textContent = '創建中...';
            
            try {
                const formData = new FormData(event.target);
                const data = Object.fromEntries(formData.entries());
                
                // 處理VM列表
                if (data.assigned_vms.trim()) {
                    data.assigned_vms = data.assigned_vms.trim().split('\\n').filter(vm => vm.trim());
                } else {
                    delete data.assigned_vms;
                }
                
                // 轉換數值類型
                data.target_port = parseInt(data.target_port);
                data.packet_size = parseInt(data.packet_size);
                data.connection_count = parseInt(data.connection_count);
                data.duration = parseInt(data.duration);
                
                const response = await fetch('/api/tasks/create', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(data)
                });
                
                const result = await response.json();
                
                if (result.success) {
                    showMessage('任務創建成功！', 'success');
                    event.target.reset();
                    loadTasks();
                    loadStats();
                } else {
                    showMessage('任務創建失敗: ' + result.message, 'error');
                }
            } catch (error) {
                showMessage('任務創建失敗: ' + error.message, 'error');
            } finally {
                startBtn.disabled = false;
                startBtn.textContent = '🎯 開始測試';
            }
        }

        // 查看任務結果
        async function viewTaskResults(taskId) {
            try {
                const response = await fetch(`/api/tasks/${taskId}/results`);
                const result = await response.json();
                
                if (result.success) {
                    const results = result.data;
                    let html = `
                        <div style="position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; display: flex; align-items: center; justify-content: center;">
                            <div style="background: white; padding: 20px; border-radius: 10px; max-width: 800px; width: 90%; max-height: 80%; overflow-y: auto;">
                                <h3>任務結果 - ${taskId.substring(0, 8)}...</h3>
                                <button onclick="this.parentElement.parentElement.remove()" style="float: right; background: #e74c3c; color: white; border: none; padding: 5px 10px; border-radius: 3px; cursor: pointer;">關閉</button>
                                <table style="margin-top: 20px;">
                                    <thead>
                                        <tr>
                                            <th>VM ID</th>
                                            <th>狀態</th>
                                            <th>發送包</th>
                                            <th>接收包</th>
                                            <th>丟包率</th>
                                            <th>平均響應時間</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                    `;
                    
                    results.forEach(res => {
                        const statusText = {
                            'pending': '等待中',
                            'running': '運行中',
                            'completed': '已完成',
                            'failed': '失敗'
                        }[res.status] || res.status;
                        
                        html += `
                            <tr>
                                <td>${res.vm_id}</td>
                                <td><span class="status ${res.status}">${statusText}</span></td>
                                <td>${res.packets_sent || 0}</td>
                                <td>${res.packets_received || 0}</td>
                                <td>${res.packet_loss_rate || 0}%</td>
                                <td>${res.avg_response_time || 0}ms</td>
                            </tr>
                        `;
                    });
                    
                    html += '</tbody></table></div></div>';
                    document.body.insertAdjacentHTML('beforeend', html);
                } else {
                    showMessage('載入任務結果失敗: ' + result.message, 'error');
                }
            } catch (error) {
                showMessage('載入任務結果失敗: ' + error.message, 'error');
            }
        }

        // 顯示消息
        function showMessage(message, type) {
            const messageDiv = document.createElement('div');
            messageDiv.className = type;
            messageDiv.textContent = message;
            messageDiv.style.position = 'fixed';
            messageDiv.style.top = '20px';
            messageDiv.style.right = '20px';
            messageDiv.style.zIndex = '1001';
            messageDiv.style.minWidth = '300px';
            
            document.body.appendChild(messageDiv);
            
            setTimeout(() => {
                messageDiv.remove();
            }, 5000);
        }

        // 頁面卸載時清理定時器
        window.addEventListener('beforeunload', function() {
            refreshIntervals.forEach(interval => clearInterval(interval));
        });
    </script>
</body>
</html>
    ''')

if __name__ == '__main__':
    logger.info(f"啟動API服務器，端口: {API_PORT}")
    app.run(host='0.0.0.0', port=API_PORT, debug=False)
