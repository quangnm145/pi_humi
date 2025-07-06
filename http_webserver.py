#!/usr/bin/env python3

import RPi.GPIO as GPIO
import serial
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs
from datetime import datetime
import pytz
import subprocess

# Lấy địa chỉ IP động từ lệnh hostname -I
def get_host_ip():
    try:
        result = subprocess.run(['hostname', '-I'], capture_output=True, text=True)
        ip_list = result.stdout.strip().split()
        return ip_list[0] if ip_list else '0.0.0.0'
    except Exception as e:
        print(f"Lỗi khi lấy địa chỉ IP: {e}")
        return '0.0.0.0'

# Cấu hình server
host_name = get_host_ip()
host_port = 8000

# Biến toàn cục
config = {
    'uart_port': '/dev/ttyACM0',
    'baud_rate': 9600,
    'humidity_threshold': 50.0
}
is_configured = False
relay_state = "Unknown"
DATA_FILE = "data_log.json"

def save_to_json(humidity, relay_status, threshold):
    """Lưu dữ liệu vào file JSON với cấu trúc mới"""
    try:
        try:
            with open(DATA_FILE, 'r') as f:
                json_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            json_data = {"config": {"port": config['uart_port'], "baud_rate": config['baud_rate']}, "data": []}

        json_data['config'] = {
            "port": config['uart_port'],
            "baud_rate": config['baud_rate']
        }

        timestamp = datetime.now(pytz.timezone('Asia/Ho_Chi_Minh')).strftime('%Y-%m-%dT%H:%M:%S')
        new_record = {
            'timestamp': timestamp,
            'humidity': humidity,
            'relay_status': relay_status,
            'threshold': threshold
        }

        json_data['data'].append(new_record)

        if len(json_data['data']) > 100:
            json_data['data'] = json_data['data'][-100:]

        with open(DATA_FILE, 'w') as f:
            json.dump(json_data, f, indent=2)
    except Exception as e:
        print(f"Lỗi khi lưu dữ liệu vào JSON: {e}")

def get_data_from_json():
    """Đọc dữ liệu từ file JSON"""
    try:
        with open(DATA_FILE, 'r') as f:
            json_data = json.load(f)
            return json_data.get("data", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def get_config_from_json():
    """Đọc config từ file JSON"""
    try:
        with open(DATA_FILE, 'r') as f:
            json_data = json.load(f)
            return json_data.get("config", {"port": "Unknown", "baud_rate": "Unknown"})
    except (FileNotFoundError, json.JSONDecodeError):
        return {"port": "Unknown", "baud_rate": "Unknown"}

def send_to_arduino(command):
    """Gửi lệnh đến Arduino qua UART"""
    try:
        with serial.Serial(config['uart_port'], baudrate=config['baud_rate'], timeout=1) as ser:
            ser.flush()
            time.sleep(0.1)
            ser.write((command + '\n').encode('utf-8'))
            print(f"Gửi lệnh đến Arduino: {command}")
    except serial.SerialException as e:
        print(f"Lỗi khi gửi lệnh đến Arduino: {e}")

def get_humidity():
    """Đọc độ ẩm từ Arduino qua UART và lưu vào JSON"""
    global relay_state
    try:
        with serial.Serial(config['uart_port'], baudrate=config['baud_rate'], timeout=1) as ser:
            ser.flush()
            time.sleep(0.1)
            line = ser.readline().decode('utf-8').strip()
            if line and "MOISTURE:" in line and "RELAY:" in line and "THRESHOLD:" in line:
                parts = line.split(',')
                humidity = float(parts[0].split(':')[1].strip('%'))
                relay_state = "ON" if parts[1].split(':')[1] == "1" else "OFF"
                threshold = float(parts[2].split(':')[1])
                
                save_to_json(humidity, relay_state, threshold)

                if humidity < config['humidity_threshold']:
                    send_to_arduino("RELAY_ON")
                else:
                    send_to_arduino("RELAY_OFF")
                return f"{humidity}%"
            return "0.0%"
    except (serial.SerialException, ValueError, IndexError) as e:
        print(f"Lỗi khi đọc UART: {e}")
        relay_state = "Unknown"
        save_to_json(0.0, relay_state, config['humidity_threshold'])
        return "0.0%"

class MyServer(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def _redirect(self, path):
        self.send_response(303)
        self.send_header('Content-type', 'text/html')
        self.send_header('Location', path)
        self.end_headers()

    def do_GET(self):
        global is_configured, relay_state
        if self.path == '/humidity' and is_configured:
            humidity = get_humidity()
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {'humidity': humidity, 'relay_status': relay_state}
            self.wfile.write(json.dumps(response).encode('utf-8'))
            return
        elif self.path == '/data' and is_configured:
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            data = get_data_from_json()
            self.wfile.write(json.dumps(data).encode('utf-8'))
            return

        html = '''
            <html>
            <head>
                <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
                <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js"></script>
            </head>
            <body style="width:960px; margin: 20px auto;">
            <h1>Welcome to my Raspberry Pi</h1>
            <p>Host: <span id="host">{8}</span></p>
            <p>Port: <span id="port">{9}</span></p>
            <p>Baud Rate: <span id="baud_rate">{10}</span></p>
            <p>Current Humidity: <span id="humidity">{0}</span></p>
            <p>Relay Status: <span id="relay_status">{1}</span></p>
            <p>Threshold: <span id="threshold">{11}</span></p>
            <h2>Relay Control</h2>
            <form action="/" method="POST" {2}>
                Relay:
                <input type="submit" name="submit" value="On" {12}>
                <input type="submit" name="submit" value="Off" {13}>
            </form>
            <h2>Configuration</h2>
            <form action="/" method="POST">
                Humidity Threshold (%): <input type="number" step="0.1" name="humidity_threshold" value="{3}" min="0" max="100"><br><br>
                <input type="submit" name="submit" value="Start" {5}>
                <input type="submit" name="submit" value="Stop" {6}>
                <input type="submit" name="submit" value="Update Threshold" {4}>
            </form>
            <h2>Humidity Chart (Last 20 Values)</h2>
            <canvas id="humidityChart" width="800" height="400"></canvas>
            <script>
                let humidityChart = null;
                function updateData() {{
                    fetch('/data')
                        .then(response => response.json())
                        .then(data => {{
                            if (data.length > 0) {{
                                let latest = data[data.length - 1];
                                document.getElementById('humidity').textContent = latest.humidity + '%';
                                document.getElementById('relay_status').textContent = latest.relay_status;
                                document.getElementById('threshold').textContent = latest.threshold + '%';
                                // Cập nhật biểu đồ
                                let last20 = data.slice(-20);
                                let labels = last20.map(d => d.timestamp);
                                let humidityData = last20.map(d => d.humidity);
                                let threshold = latest.threshold;
                                if (humidityChart) {{
                                    humidityChart.data.labels = labels;
                                    humidityChart.data.datasets[0].data = humidityData;
                                    humidityChart.options.plugins.annotation.annotations.threshold.value = threshold;
                                    humidityChart.update();
                                }} else {{
                                    humidityChart = new Chart(document.getElementById('humidityChart'), {{
                                        type: 'line',
                                        data: {{
                                            labels: labels,
                                            datasets: [{{
                                                label: 'Humidity (%)',
                                                data: humidityData,
                                                borderColor: 'blue',
                                                fill: false
                                            }}]
                                        }},
                                        options: {{
                                            responsive: true,
                                            scales: {{
                                                y: {{
                                                    beginAtZero: true,
                                                    max: 100
                                                }}
                                            }},
                                            plugins: {{
                                                annotation: {{
                                                    annotations: {{
                                                        threshold: {{
                                                            type: 'line',
                                                            yMin: threshold,
                                                            yMax: threshold,
                                                            borderColor: 'red',
                                                            borderWidth: 2,
                                                            label: {{
                                                                enabled: true,
                                                                content: 'Threshold: ' + threshold + '%',
                                                                position: 'end'
                                                            }}
                                                        }}
                                                    }}
                                                }}
                                            }}
                                        }}
                                    }});
                                }}
                            }}
                        }})
                        .catch(error => {{
                            console.error('Error:', error);
                            document.getElementById('humidity').textContent = 'Error reading data';
                            document.getElementById('relay_status').textContent = 'Unknown';
                            document.getElementById('threshold').textContent = 'Unknown';
                        }});
                }}
                if ({7}) {{
                    setInterval(updateData, 30000);
                    updateData();
                }}
            </script>
            </body>
            </html>
        '''
        humidity = "Unknown"
        relay_display = "Unknown"
        threshold = "Unknown"
        port = "Unknown"
        baud_rate = "Unknown"
        if is_configured:
            try:
                with open(DATA_FILE, 'r') as f:
                    json_data = json.load(f)
                    port = json_data.get("config", {}).get("port", "Unknown")
                    baud_rate = str(json_data.get("config", {}).get("baud_rate", "Unknown"))
                    if json_data.get("data", []):
                        latest = json_data["data"][-1]
                        humidity = str(latest.get("humidity", "Unknown")) + '%'
                        relay_display = latest.get("relay_status", "Unknown")
                        threshold = str(latest.get("threshold", "Unknown")) + '%'
            except (FileNotFoundError, json.JSONDecodeError):
                pass

        relay_form_disabled = "" if is_configured else 'disabled'
        input_disabled = ''  # Luôn cho phép nhập threshold
        start_disabled = 'disabled' if is_configured else ''
        stop_disabled = '' if is_configured else 'disabled'
        on_disabled = 'disabled' if relay_display == "ON" and is_configured else ''
        off_disabled = 'disabled' if relay_display == "OFF" and is_configured else ''
        update_script = 'true' if is_configured else 'false'

        self.do_HEAD()
        self.wfile.write(html.format(
            humidity, relay_display, relay_form_disabled,
            config['humidity_threshold'], input_disabled,
            start_disabled, stop_disabled, update_script,
            host_name, port, baud_rate, threshold,
            on_disabled, off_disabled
        ).encode("utf-8"))

    def do_POST(self):
        global is_configured, relay_state
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length).decode("utf-8")
        params = parse_qs(post_data)

        submit_value = params.get('submit', [''])[0]
        if submit_value == 'On':
            send_to_arduino("RELAY_ON")
            relay_state = "ON"
            try:
                with open(DATA_FILE, 'r') as f:
                    json_data = json.load(f)
                if json_data.get("data", []):
                    json_data["data"][-1]["relay_status"] = "ON"
                    with open(DATA_FILE, 'w') as f:
                        json.dump(json_data, f, indent=2)
            except (FileNotFoundError, json.JSONDecodeError):
                pass
        elif submit_value == 'Off':
            send_to_arduino("RELAY_OFF")
            relay_state = "OFF"
            try:
                with open(DATA_FILE, 'r') as f:
                    json_data = json.load(f)
                if json_data.get("data", []):
                    json_data["data"][-1]["relay_status"] = "OFF"
                    with open(DATA_FILE, 'w') as f:
                        json.dump(json_data, f, indent=2)
            except (FileNotFoundError, json.JSONDecodeError):
                pass
        elif submit_value == 'Start':
            try:
                humidity_threshold = float(params.get('humidity_threshold', [config['humidity_threshold']])[0])
                if 0 <= humidity_threshold <= 100:
                    config['humidity_threshold'] = humidity_threshold
                    send_to_arduino(f"SET_THRESHOLD:{humidity_threshold}")
                    try:
                        with open(DATA_FILE, 'r') as f:
                            json_data = json.load(f)
                        if json_data.get("data", []):
                            json_data["data"][-1]["threshold"] = humidity_threshold
                            with open(DATA_FILE, 'w') as f:
                                json.dump(json_data, f, indent=2)
                    except (FileNotFoundError, json.JSONDecodeError):
                        pass
                else:
                    print("Ngưỡng độ ẩm phải từ 0 đến 100")
            except ValueError:
                print("Ngưỡng độ ẩm phải là số thực")
            is_configured = True
        elif submit_value == 'Stop':
            is_configured = False
            relay_state = "Unknown"
        elif submit_value == 'Update Threshold':
            try:
                humidity_threshold = float(params.get('humidity_threshold', [config['humidity_threshold']])[0])
                if 0 <= humidity_threshold <= 100:
                    config['humidity_threshold'] = humidity_threshold
                    send_to_arduino(f"SET_THRESHOLD:{humidity_threshold}")
                    try:
                        with open(DATA_FILE, 'r') as f:
                            json_data = json.load(f)
                        if json_data.get("data", []):
                            json_data["data"][-1]["threshold"] = humidity_threshold
                            with open(DATA_FILE, 'w') as f:
                                json.dump(json_data, f, indent=2)
                    except (FileNotFoundError, json.JSONDecodeError):
                        pass
                else:
                    print("Ngưỡng độ ẩm phải từ 0 đến 100")
            except ValueError:
                print("Ngưỡng độ ẩm phải là số thực")

        self._redirect('/')

if __name__ == '__main__':
    try:
        http_server = HTTPServer((host_name, host_port), MyServer)
        print(f"Server Starts - {host_name}:{host_port}")
        http_server.serve_forever()
    except OSError as e:
        print(f"Không thể khởi động server: {e}")
    except KeyboardInterrupt:
        http_server.server_close()
        print("Server đã dừng.")