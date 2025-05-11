from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.layout import Layout
from datetime import datetime
import websocket
import json
import time
import threading
import sys
import statistics
import os
import logging
import requests
from pathlib import Path

console = Console()

class TeneoNode:
    def __init__(self):
        self.setup_logging()
        self.load_config()
        self.initialize_variables()
        self.ws_thread = None
        self.connection_lock = threading.Lock()

    def setup_logging(self):
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        # Hapus handler lama
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)
            
        # Setup format logging baru
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            handlers=[
                logging.FileHandler(log_dir / "teneo_node.log"),
            ]
        )

    def load_config(self):
        try:
            config_path = Path("config.json")
            if not config_path.exists():
                console.print("[red]config.json not found. Please create one.[/]")
                sys.exit(1)

            with config_path.open('r') as f:
                config = json.load(f)

            self.ACCESS_TOKEN = config['access_token']
            self.WS_URL = config.get('ws_url', 'wss://secure.ws.teneo.pro/websocket')
            self.VERSION = config.get('version', 'v0.2')
            
            self.headers = {
                'accept': 'application/json, text/plain, */*',
                'accept-encoding': 'gzip, deflate, br, zstd',
                'accept-language': 'id-ID',
                'cache-control': 'no-cache',
                'origin': 'https://dashboard.teneo.pro',
                'pragma': 'no-cache',
                'priority': 'u=1, i',
                'referer': 'https://dashboard.teneo.pro/',
                'sec-ch-ua': '"Chromium";v="127", "Not)A;Brand";v="99"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Linux"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-site',
                'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
            }

            self.api_headers = self.headers.copy()
            self.api_headers['authorization'] = f'Bearer {self.ACCESS_TOKEN}'

            # Constants
            self.points_per_heartbeat = 75
            self.heartbeat_interval = 900  # 15 minutes
            self.max_heartbeats_per_day = 96
            self.ping_interval = 10
            self.dashboard_check_interval = 60
            self.reconnect_delay = 5

        except Exception as e:
            logging.error(f"Error loading config: {e}")
            sys.exit(1)

    def initialize_variables(self):
        # Connection variables
        self.ws = None
        self.is_connected = False
        self.connection_attempts = 0
        self.max_connection_attempts = 5

        # Points and heartbeat tracking
        self.current_points = 0
        self.points_today = 0
        self.heartbeats = 0
        self.last_heartbeat_time = time.time()
        self.heartbeat_counter = 0
        self.heartbeats_percentage = 0

        # Timing and runtime
        self.script_start_time = datetime.now()
        self.start_time = None
        self.last_pulse = None
        self.uptime_hours = 0
        self.uptime_minutes = 0
        self.next_heartbeat_minutes = 0
        self.next_heartbeat_seconds = 0

        # Network metrics
        self.ping_count = 0
        self.ping_times = []
        self.last_ping_time = None
        self.current_latency = 0
        self.min_latency = float('inf')
        self.max_latency = 0
        self.avg_latency = 0

        # Dashboard sync
        self.dashboard_points_today = 0
        self.dashboard_heartbeats = 0
        self.last_dashboard_check = 0

        # Display
        self.display_thread = None
        self.stop_display = False

    def format_duration(self, seconds):
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        return f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"

    def format_latency(self, ms):
        if ms == float('inf'):
            return "N/A"
        return f"{ms:.1f}ms"

    def check_dashboard_stats(self):
        try:
            current_time = time.time()
            if current_time - self.last_dashboard_check < self.dashboard_check_interval:
                return

            response = requests.get(
                'https://api.teneo.pro/api/users/stats',
                headers=self.api_headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                self.dashboard_points_today = data['points_today']
                self.dashboard_heartbeats = data['heartbeats']
                self.last_dashboard_check = current_time
                logging.info(f"Dashboard stats updated - Today: {self.dashboard_points_today}")
            else:
                logging.error(f"Failed to fetch dashboard stats: {response.status_code}")

        except Exception as e:
            logging.error(f"Error checking dashboard stats: {e}")

    def calculate_node_metrics(self):
        # Calculate uptime and heartbeats based on points
        points_today = self.points_today
        total_heartbeats = points_today // self.points_per_heartbeat
        total_minutes = total_heartbeats * 15
        
        self.uptime_hours = total_minutes // 60
        self.uptime_minutes = total_minutes % 60
        self.heartbeats_percentage = total_heartbeats

        # Calculate next heartbeat timing
        if self.last_heartbeat_time:
            time_since_last = time.time() - self.last_heartbeat_time
            time_until_next = max(0, self.heartbeat_interval - time_since_last)
            self.next_heartbeat_minutes = int(time_until_next // 60)
            self.next_heartbeat_seconds = int(time_until_next % 60)
    def get_status_display(self):
        now = datetime.now()
        runtime = (now - self.script_start_time).total_seconds()
        self.calculate_node_metrics()
        self.check_dashboard_stats()

        # Calculate points difference
        points_difference = self.points_today - self.dashboard_points_today
        difference_color = "yellow" if points_difference > 0 else "green"

        # Calculate success rate
        success_rate = (self.heartbeats_percentage / self.max_heartbeats_per_day * 100) if self.max_heartbeats_per_day > 0 else 0

        status = [
            f"[bold green]STATUS: {'🟢 CONNECTED' if self.is_connected else '🔴 DISCONNECTED'}[/]",
            f"[yellow]Runtime: {self.format_duration(runtime)}[/]",
            f"[magenta]Node Uptime: {self.uptime_hours:02d}:{self.uptime_minutes:02d}[/]",
            f"[magenta]Heartbeats Today: {self.heartbeats_percentage}/{self.max_heartbeats_per_day} ({success_rate:.1f}%)[/]",
            f"[cyan]Next Heartbeat in: {self.next_heartbeat_minutes:02d}:{self.next_heartbeat_seconds:02d}[/]",
            "",
            "[bold white]Points Information[/]",
            f"[green]Points Today (Node): {self.points_today:,}[/]",
            f"[{difference_color}]Points Today (Dashboard): {self.dashboard_points_today:,} ({'+' if points_difference > 0 else ''}{points_difference:,})[/]",
            f"[cyan]Total Points: {self.current_points:,}[/]",
            "",
            "[bold white]Network Information[/]",
            f"[blue]Ping Count: {self.ping_count}[/]",
            f"[green]Current Latency: {self.format_latency(self.current_latency)}[/]",
            f"[blue]Average Latency: {self.format_latency(self.avg_latency)}[/]",
            f"[cyan]Min Latency: {self.format_latency(self.min_latency)}[/]",
            f"[red]Max Latency: {self.format_latency(self.max_latency)}[/]",
            f"[yellow]Connection Attempts: {self.connection_attempts}[/]"
        ]

        return "\n".join(status)

    def display_thread_function(self):
        with Live(auto_refresh=True) as live_display:
            while not self.stop_display:
                layout = Layout()
                layout.split_column(
                    Panel(
                        self.get_status_display(),
                        title="[bold white]TeneoNode Monitor[/]",
                        border_style="bright_blue",
                    )
                )
                live_display.update(layout)
                time.sleep(1)

    def update_latency(self, latency_ms):
        self.current_latency = latency_ms
        self.min_latency = min(self.min_latency, latency_ms)
        self.max_latency = max(self.max_latency, latency_ms)
        self.ping_times.append(latency_ms)
        if len(self.ping_times) > 50:
            self.ping_times.pop(0)
        self.avg_latency = statistics.mean(self.ping_times)

    def on_message(self, ws, message):
        try:
            if self.last_ping_time:
                latency = (time.time() - self.last_ping_time) * 1000
                self.update_latency(latency)
                self.last_ping_time = None

            data = json.loads(message)
            message_type = data.get("type", "")

            if message_type == "PONG":
                return

            if "Connected successfully" in str(data.get("message", "")):
                self.start_time = datetime.now()
                self.current_points = data.get("pointsTotal", 0)
                self.points_today = data.get("pointsToday", 0)
                self.heartbeats = self.points_today // self.points_per_heartbeat
                logging.info("Connection established successfully")

            elif "Pulse from server" in str(data.get("message", "")):
                self.last_pulse = datetime.now()
                self.current_points = data.get("pointsTotal", 0)
                self.points_today = data.get("pointsToday", 0)
                self.heartbeats = self.points_today // self.points_per_heartbeat

                current_time = time.time()
                if current_time - self.last_heartbeat_time >= self.heartbeat_interval:
                    self.heartbeat_counter += 1
                    self.last_heartbeat_time = current_time

        except json.JSONDecodeError as e:
            logging.error(f"Message parse error: {e}")

    def on_error(self, ws, error):
        logging.error(f"WebSocket Error: {error}")
        with self.connection_lock:
            self.is_connected = False

    def on_close(self, ws, close_status_code, close_msg):
        with self.connection_lock:
            self.is_connected = False
            logging.warning(f"Connection Closed (Code: {close_status_code})")

    def on_open(self, ws):
        self.start_ping_thread()

    def start_ping_thread(self):
        def ping_loop():
            while self.is_connected:
                try:
                    if self.ws and self.ws.sock:
                        self.last_ping_time = time.time()
                        self.ws.send(json.dumps({"type": "PING"}))
                        self.ping_count += 1
                        time.sleep(self.ping_interval)
                except Exception as e:
                    logging.error(f"Ping Error: {e}")
                    break

        threading.Thread(target=ping_loop, daemon=True).start()

    def create_new_connection(self):
        try:
            with self.connection_lock:
                if self.is_connected and self.ws and self.ws.sock:
                    return

                self.connection_attempts += 1
                self.is_connected = False
                
                full_url = f"{self.WS_URL}?accessToken={self.ACCESS_TOKEN}&version={self.VERSION}"
                self.ws = websocket.WebSocketApp(
                    full_url,
                    header=self.headers,
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close
                )

                self.ws_thread = threading.Thread(target=self.ws.run_forever, daemon=True)
                self.ws_thread.start()
                
                self.is_connected = True
                self.last_heartbeat_time = time.time()
                logging.info("New connection initiated")

        except Exception as e:
            logging.error(f"Error creating new connection: {e}")
            self.is_connected = False

    def reconnect(self):
        with self.connection_lock:
            if self.ws:
                try:
                    self.ws.close()
                    if self.ws_thread and self.ws_thread.is_alive():
                        self.ws_thread.join(timeout=1)
                except:
                    pass
                self.ws = None
                self.ws_thread = None
                self.is_connected = False
            
            time.sleep(self.reconnect_delay)
            if not self.is_connected:
                self.create_new_connection()

    def cleanup_and_exit(self):
        self.stop_display = True
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
        if self.ws_thread and self.ws_thread.is_alive():
            try:
                self.ws_thread.join(timeout=1)
            except:
                pass
        os._exit(1)

    def start(self):
        try:
            console.clear()
            console.print("[cyan]Initializing TeneoNode...[/]\n")

            self.display_thread = threading.Thread(target=self.display_thread_function, daemon=True)
            self.display_thread.start()

            while True:
                if not self.is_connected:
                    self.create_new_connection()
                time.sleep(5)

        except KeyboardInterrupt:
            console.print("\n[yellow]Graceful Shutdown Initiated[/]")
            self.cleanup_and_exit()
        except Exception as e:
            logging.error(f"Critical error: {e}")
            self.cleanup_and_exit()

if __name__ == "__main__":
    node = TeneoNode()
    node.start()
