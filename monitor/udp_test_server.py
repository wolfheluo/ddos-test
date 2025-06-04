#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import socket
import threading
import time
import json
from datetime import datetime

class UDPTestServer:
    def __init__(self, host='0.0.0.0', port=9999):
        self.host = host
        self.port = port
        self.sock = None
        self.running = False
        self.stats = {
            'packets_received': 0,
            'bytes_received': 0,
            'clients': set(),
            'start_time': time.time()
        }
    
    def start(self):
        """啟動UDP測試服務器"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind((self.host, self.port))
            self.running = True
            
            print(f"UDP測試服務器已啟動在 {self.host}:{self.port}")
            print("這個服務器將接收UDP封包並回應統計信息")
            print("按 Ctrl+C 停止服務器")
            
            while self.running:
                try:
                    # 接收數據
                    data, addr = self.sock.recvfrom(8192)
                    
                    # 更新統計
                    self.stats['packets_received'] += 1
                    self.stats['bytes_received'] += len(data)
                    self.stats['clients'].add(f"{addr[0]}:{addr[1]}")
                    
                    # 準備回應數據
                    response_data = {
                        'timestamp': datetime.now().isoformat(),
                        'server_port': self.port,
                        'client_addr': f"{addr[0]}:{addr[1]}",
                        'packet_size': len(data),
                        'total_packets': self.stats['packets_received'],
                        'total_bytes': self.stats['bytes_received'],
                        'unique_clients': len(self.stats['clients']),
                        'uptime': time.time() - self.stats['start_time'],
                        'message': f"收到來自 {addr[0]}:{addr[1]} 的 {len(data)} 字節數據"
                    }
                    
                    # 發送回應
                    response = json.dumps(response_data, ensure_ascii=False).encode('utf-8')
                    self.sock.sendto(response, addr)
                    
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 收到來自 {addr[0]}:{addr[1]} 的 {len(data)} 字節數據")
                    
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        print(f"處理UDP封包時發生錯誤: {e}")
                        
        except Exception as e:
            print(f"啟動UDP服務器時發生錯誤: {e}")
        finally:
            self.stop()
    
    def stop(self):
        """停止UDP服務器"""
        self.running = False
        if self.sock:
            self.sock.close()
        print(f"\nUDP測試服務器已停止")
        print(f"統計信息:")
        print(f"  接收封包數: {self.stats['packets_received']}")
        print(f"  接收字節數: {self.stats['bytes_received']}")
        print(f"  獨特客戶端: {len(self.stats['clients'])}")
        print(f"  運行時間: {time.time() - self.stats['start_time']:.2f} 秒")

def create_udp_client_test(server_host='localhost', server_port=9999, num_packets=10):
    """創建UDP客戶端進行測試"""
    client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_sock.settimeout(5.0)
    
    print(f"\n開始UDP客戶端測試: 發送 {num_packets} 個封包到 {server_host}:{server_port}")
    
    for i in range(num_packets):
        try:
            # 發送測試數據
            test_data = f"UDP測試封包 #{i+1} - 時間: {datetime.now().isoformat()}".encode('utf-8')
            client_sock.sendto(test_data, (server_host, server_port))
            
            # 接收回應
            response, addr = client_sock.recvfrom(8192)
            response_data = json.loads(response.decode('utf-8'))
            
            print(f"封包 #{i+1}: 發送 {len(test_data)} 字節, 收到回應: {response_data['message']}")
            
            time.sleep(0.1)  # 短暫延遲
            
        except socket.timeout:
            print(f"封包 #{i+1}: 超時")
        except Exception as e:
            print(f"封包 #{i+1}: 錯誤 - {e}")
    
    client_sock.close()
    print("UDP客戶端測試完成")

if __name__ == '__main__':
    import sys
    import signal
    
    # 設置信號處理器來優雅地停止服務器
    server = None
    
    def signal_handler(signum, frame):
        if server:
            server.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 解析命令行參數
    port = 9999
    if len(sys.argv) > 1:
        if sys.argv[1] == 'client':
            # 運行客戶端測試
            server_host = sys.argv[2] if len(sys.argv) > 2 else 'localhost'
            server_port = int(sys.argv[3]) if len(sys.argv) > 3 else 9999
            num_packets = int(sys.argv[4]) if len(sys.argv) > 4 else 10
            create_udp_client_test(server_host, server_port, num_packets)
            sys.exit(0)
        else:
            try:
                port = int(sys.argv[1])
            except ValueError:
                print("錯誤: 端口號必須是數字")
                sys.exit(1)
    
    # 啟動UDP服務器
    server = UDPTestServer(port=port)
    
    print("UDP測試服務器選項:")
    print(f"  服務器模式: python3 udp_test_server.py [端口號] (默認: 9999)")
    print(f"  客戶端測試: python3 udp_test_server.py client [服務器IP] [端口] [封包數]")
    print()
    
    server.start()
