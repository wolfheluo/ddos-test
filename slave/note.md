### 給予 hping3 特權 （可讓非 root 使用者使用 raw socket)
```bash
sudo setcap cap_net_raw+ep /usr/sbin/hping3
```
---
## 開機啟動
### 使用 Systemd Service

假設你的腳本為 /home/youruser/myscript.sh，先確保它有執行權限：
```bash
chmod +x /home/youruser/myscript.sh
```
建立一個 systemd 服務檔：
```bash
sudo nano /etc/systemd/system/myscript.service
```

輸入以下內容（根據實際情況修改）：
```ini
[Unit]
Description=My Custom Script
After=network.target

[Service]
Type=simple
ExecStart=/home/youruser/myscript.sh
Restart=on-failure
User=youruser

[Install]
WantedBy=multi-user.target
```
📝 小提醒：
After=network.target 確保網路啟動後才執行（視腳本需求可加）。
若腳本內需要 root 權限，User=youruser 可以刪除或改成 root。

啟用並啟動服務：
```bash
sudo systemctl daemon-reexec
sudo systemctl daemon-reload
sudo systemctl enable myscript.service
sudo systemctl start myscript.service
```

查看狀態與 log：
```bash
systemctl status myscript.service
journalctl -u myscript.service
```