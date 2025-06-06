-- 創建資料庫
CREATE DATABASE IF NOT EXISTS ddos_system;
USE ddos_system;

-- 創建VM客戶端表
CREATE TABLE IF NOT EXISTS vms (
    id INT AUTO_INCREMENT PRIMARY KEY,
    vm_id VARCHAR(50) UNIQUE NOT NULL,
    ip_address VARCHAR(45) NOT NULL,
    hostname VARCHAR(100),
    status ENUM('online', 'offline') DEFAULT 'online',
    last_heartbeat TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_vm_id (vm_id),
    INDEX idx_status (status),
    INDEX idx_last_heartbeat (last_heartbeat)
);

-- 創建測試任務表
CREATE TABLE IF NOT EXISTS tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(50) UNIQUE NOT NULL,
    target_ip VARCHAR(45) NOT NULL,
    target_port INT NOT NULL,
    test_type ENUM('TCP', 'UDP', 'ICMP') NOT NULL,
    packet_size INT DEFAULT 64,
    connection_count INT DEFAULT 100,
    duration INT DEFAULT 30,
    assigned_vms TEXT, -- JSON format array of VM IDs
    status ENUM('pending', 'running', 'completed', 'failed') DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_task_id (task_id),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at)
);

-- 創建任務結果表
CREATE TABLE IF NOT EXISTS task_results (
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(50) NOT NULL,
    vm_id VARCHAR(50) NOT NULL,
    status ENUM('pending', 'running', 'completed', 'failed') DEFAULT 'pending',
    packets_sent INT DEFAULT 0,
    packets_received INT DEFAULT 0,
    packet_loss_rate DECIMAL(5,2) DEFAULT 0.00,
    avg_response_time DECIMAL(10,3) DEFAULT 0.000,
    min_response_time DECIMAL(10,3) DEFAULT 0.000,
    max_response_time DECIMAL(10,3) DEFAULT 0.000,
    error_message TEXT,
    started_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE,
    FOREIGN KEY (vm_id) REFERENCES vms(vm_id) ON DELETE CASCADE,
    INDEX idx_task_id (task_id),
    INDEX idx_vm_id (vm_id),
    INDEX idx_status (status)
);

-- 創建VM任務分配表
CREATE TABLE IF NOT EXISTS vm_tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    vm_id VARCHAR(50) NOT NULL,
    task_id VARCHAR(50) NOT NULL,
    status ENUM('pending', 'assigned', 'running', 'completed', 'failed') DEFAULT 'pending',
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    FOREIGN KEY (vm_id) REFERENCES vms(vm_id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE,
    UNIQUE KEY unique_vm_task (vm_id, task_id),
    INDEX idx_vm_id (vm_id),
    INDEX idx_task_id (task_id),
    INDEX idx_status (status)
);

-- 創建master監測結果表
CREATE TABLE IF NOT EXISTS master_monitoring (
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(50) NOT NULL,
    target_ip VARCHAR(45) NOT NULL,
    target_port INT NOT NULL,
    test_type ENUM('TCP', 'UDP', 'ICMP') NOT NULL,
    response_time DECIMAL(10,3),
    packet_loss BOOLEAN DEFAULT FALSE,
    error_message TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE,
    INDEX idx_task_id (task_id),
    INDEX idx_timestamp (timestamp),
    INDEX idx_target (target_ip, target_port)
);

-- 插入示例數據（可選）
-- INSERT INTO vms (vm_id, ip_address, hostname) VALUES 
-- ('vm-001', '192.168.1.100', 'test-vm-001'),
-- ('vm-002', '192.168.1.101', 'test-vm-002');
