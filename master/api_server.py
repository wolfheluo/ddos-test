#!/usr/bin/env python3
"""
分散式網路測試系統 - API 服務器
"""
import os
import json
import uuid
import logging
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template
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

app = Flask(__name__, template_folder='templates')
CORS(app)

# 資料庫配置
DB_CONFIG = {
    'host': os.getenv('DB_HOST', '165.154.226.131'),
    'user': os.getenv('DB_USER', 'wolfheluo'),
    'password': os.getenv('DB_PASSWORD', 'nasa0411'),
    'database': os.getenv('DB_NAME', 'ddos_system'),
    'charset': 'utf8mb4',
    'autocommit': True
}

API_PORT = int(os.getenv('API_PORT', 5050))
VM_HEARTBEAT_TIMEOUT = int(os.getenv('VM_HEARTBEAT_TIMEOUT', 120))

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
        
        logger.info(f"任務 {task_id} 已創建，分配給 {len(assigned_vms)} 個VM")
        return jsonify({
            'success': True, 
            'message': '任務創建成功',
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
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    """儀表板頁面"""
    return render_template('dashboard.html')

@app.route('/api/tasks/<task_id>/stop', methods=['POST'])
def stop_task(task_id):
    """停止指定任務"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'status': 'error', 'error': '資料庫連接失敗'}), 500
        
        cursor = conn.cursor()
        
        # 檢查任務是否存在
        cursor.execute("SELECT status FROM tasks WHERE task_id = %s", (task_id,))
        task = cursor.fetchone()
        
        if not task:
            return jsonify({'status': 'error', 'error': '任務不存在'}), 404
        
        if task[0] not in ['pending', 'running']:
            return jsonify({'status': 'error', 'error': '任務無法停止'}), 400
        
        # 更新任務狀態為stopped
        cursor.execute("UPDATE tasks SET status = 'stopped' WHERE task_id = %s", (task_id,))
        cursor.execute("UPDATE vm_tasks SET status = 'stopped' WHERE task_id = %s", (task_id,))
        cursor.execute("UPDATE task_results SET status = 'stopped' WHERE task_id = %s", (task_id,))
        
        conn.close()
        
        logger.info(f"任務 {task_id} 已停止")
        return jsonify({'status': 'success', 'message': '任務已停止'})
        
    except Exception as e:
        logger.error(f"停止任務錯誤: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500

if __name__ == '__main__':
    logger.info(f"啟動API服務器，端口: {API_PORT}")
    app.run(host='0.0.0.0', port=API_PORT, debug=False)
