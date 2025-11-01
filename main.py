import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinterdnd2 import DND_FILES, TkinterDnD
import threading
import httpx
import random
import re
import time
from datetime import datetime, timedelta
import os
import json
import sys
from PIL import Image, ImageTk, ImageDraw
import pystray
from pystray import MenuItem as item
from concurrent.futures import ThreadPoolExecutor, as_completed


class Settings:
    """Settings manager with save/load functionality"""
    def __init__(self):
        self.config_file = "vexcel_settings.json"
        self.max_workers = 10
        self.proxy_workers = 20
        self.max_retries = 5
        self.connection_timeout = 10.0
        self.request_timeout = 30.0
        self.sound_enabled = True
        self.auto_detect_files = True
        self.load()
    
    def load(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    self.max_workers = data.get('max_workers', 10)
                    self.proxy_workers = data.get('proxy_workers', 20)
                    self.max_retries = data.get('max_retries', 5)
                    self.connection_timeout = data.get('connection_timeout', 10.0)
                    self.request_timeout = data.get('request_timeout', 30.0)
                    self.sound_enabled = data.get('sound_enabled', True)
                    self.auto_detect_files = data.get('auto_detect_files', True)
        except:
            pass
    
    def save(self):
        try:
            data = {
                'max_workers': self.max_workers,
                'proxy_workers': self.proxy_workers,
                'max_retries': self.max_retries,
                'connection_timeout': self.connection_timeout,
                'request_timeout': self.request_timeout,
                'sound_enabled': self.sound_enabled,
                'auto_detect_files': self.auto_detect_files
            }
            with open(self.config_file, 'w') as f:
                json.dump(data, f, indent=4)
        except:
            pass


class SessionHistory:
    """History manager for tracking sessions"""
    def __init__(self):
        self.history_file = "vexcel_history.json"
        self.sessions = []
        self.load()
    
    def load(self):
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r') as f:
                    self.sessions = json.load(f)
        except:
            self.sessions = []
    
    def add_session(self, total, successful, failed, duration, output_file):
        session = {
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'total': total,
            'successful': successful,
            'failed': failed,
            'duration': duration,
            'success_rate': round((successful / total * 100) if total > 0 else 0, 1),
            'output_file': output_file
        }
        self.sessions.insert(0, session)
        if len(self.sessions) > 50:
            self.sessions = self.sessions[:50]
        self.save()
    
    def save(self):
        try:
            with open(self.history_file, 'w') as f:
                json.dump(self.sessions, f, indent=4)
        except:
            pass


class ToolTip:
    """Create tooltip for widgets"""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip = None
        self.widget.bind("<Enter>", self.show_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)
    
    def show_tooltip(self, event=None):
        x = self.widget.winfo_rootx() + 25
        y = self.widget.winfo_rooty() + 25
        self.tooltip = tk.Toplevel(self.widget)
        self.tooltip.wm_overrideredirect(True)
        self.tooltip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tooltip, text=self.text, 
                        background="#1a1a1a", foreground="#ffffff",
                        relief=tk.SOLID, borderwidth=1, 
                        font=("Arial", 9), padx=8, pady=4)
        label.pack()
    
    def hide_tooltip(self, event=None):
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None


class CookieRefresher:
    def __init__(self, settings):
        self.settings = settings
        self.working_proxies = []
        self.results = []
        self.log_lock = threading.Lock()
        self.proxy_lock = threading.Lock()
        self.should_stop = False
        
    def stop(self):
        self.should_stop = True
    
    def load_file(self, filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    
    def validate_cookie(self, cookie):
        """Validate cookie format"""
        return len(cookie) > 50 and not cookie.startswith('#')
    
    def validate_proxy(self, proxy):
        """Validate proxy format"""
        pattern1 = r'^(?:http://)?[\w\.-]+:\d+(?::[\w]+:[\w]+)?$'
        pattern2 = r'^(?:http://)?[\w]+:[\w]+@[\w\.-]+:\d+$'
        return bool(re.match(pattern1, proxy) or re.match(pattern2, proxy))
    
    def format_proxy(self, proxy_string):
        """Format proxy string to http://user:pass@ip:port or http://ip:port"""
        proxy = proxy_string.replace("http://", "")
        
        if "@" in proxy:
            return f"http://{proxy}"
        
        parts = proxy.split(":")
        if len(parts) == 4:
            ip, port, user, password = parts
            return f"http://{user}:{password}@{ip}:{port}"
        
        return f"http://{proxy}"
    
    def check_proxy(self, proxy_string):
        if self.should_stop:
            return False
        try:
            proxy_formatted = self.format_proxy(proxy_string)
            timeout = httpx.Timeout(self.settings.connection_timeout, connect=5.0)
            try:
                response = httpx.get("https://www.roblox.com", proxy=proxy_formatted, timeout=timeout)
            except TypeError:
                proxy = {"http://": proxy_formatted, "https://": proxy_formatted}
                response = httpx.get("https://www.roblox.com", proxies=proxy, timeout=timeout)
            return response.status_code == 200
        except:
            return False
    
    def check_all_proxies(self, proxies, log_callback, progress_callback=None):
        log_callback("Checking proxies...\n")
        self.working_proxies = []
        checked = 0
        
        def check_single_proxy(proxy_data):
            nonlocal checked
            if self.should_stop:
                return None
            index, proxy = proxy_data
            result = self.check_proxy(proxy)
            with self.log_lock:
                checked += 1
                if progress_callback:
                    progress_callback(checked, len(proxies))
                log_callback(f"  [{index}/{len(proxies)}] Testing {proxy}... ")
                if result:
                    log_callback("✓ OK\n")
                else:
                    log_callback("✗ Failed\n")
            return proxy if result else None
        
        with ThreadPoolExecutor(max_workers=self.settings.proxy_workers) as executor:
            futures = {executor.submit(check_single_proxy, (i, proxy)): proxy 
                      for i, proxy in enumerate(proxies, 1)}
            
            for future in as_completed(futures):
                if self.should_stop:
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                result = future.result()
                if result:
                    with self.proxy_lock:
                        self.working_proxies.append(result)
        
        if not self.working_proxies and not self.should_stop:
            raise Exception("No working proxies found!")
        
        if not self.should_stop:
            log_callback(f"\n✓ Found {len(self.working_proxies)} working proxies out of {len(proxies)}\n\n")
    
    def get_random_proxy(self):
        if not self.working_proxies:
            raise Exception("No working proxies available!")
        proxy_string = self.format_proxy(random.choice(self.working_proxies))
        return {"http://": proxy_string, "https://": proxy_string}
    
    def generate_csrf_token(self, auth_cookie, proxy_dict):
        if self.should_stop:
            raise Exception("Stopped by user")
        proxy_str = list(proxy_dict.values())[0] if isinstance(proxy_dict, dict) else proxy_dict
        timeout = httpx.Timeout(self.settings.request_timeout, connect=self.settings.connection_timeout)
        try:
            csrf_req = httpx.get("https://www.roblox.com/home",
                                 cookies={".ROBLOSECURITY": auth_cookie},
                                 proxy=proxy_str,
                                 timeout=timeout,
                                 follow_redirects=True)
        except TypeError:
            csrf_req = httpx.get("https://www.roblox.com/home",
                                 cookies={".ROBLOSECURITY": auth_cookie},
                                 proxies=proxy_dict,
                                 timeout=timeout,
                                 follow_redirects=True)
        
        if csrf_req.status_code not in [200, 302]:
            raise Exception(f"Failed to fetch CSRF token. Status code: {csrf_req.status_code}")
        
        parts = csrf_req.text.split("<meta name=\"csrf-token\" data-token=\"")
        if len(parts) < 2:
            raise Exception("CSRF token not found in response.")
        
        token_parts = parts[1].split("\" />")
        if len(token_parts) < 1:
            raise Exception("Failed to parse CSRF token.")
        
        return token_parts[0]
    
    def refresh_cookie(self, auth_cookie, log_callback):
        if self.should_stop:
            return None
        used_proxies = []
        
        for attempt in range(self.settings.max_retries):
            if self.should_stop:
                return None
            try:
                available_proxies = [p for p in self.working_proxies if p not in used_proxies]
                if not available_proxies:
                    used_proxies = []
                    available_proxies = self.working_proxies
                
                proxy_str = self.format_proxy(random.choice(available_proxies))
                used_proxies.append(proxy_str)
                proxy = {"http://": proxy_str, "https://": proxy_str}
                
                log_callback(f"[Attempt {attempt + 1}/{self.settings.max_retries}] Using proxy: {proxy_str}\n")
                
                if attempt > 0:
                    delay = random.uniform(2, 5)
                    log_callback(f"⏱ Waiting {delay:.1f}s before retry...\n")
                    time.sleep(delay)
                
                csrf_token = self.generate_csrf_token(auth_cookie, proxy)
                log_callback(f"CSRF Token: {csrf_token}\n")
                
                time.sleep(random.uniform(1, 2))
                
                headers = {
                    "Content-Type": "application/json",
                    "user-agent": "Roblox/WinInet",
                    "origin": "https://www.roblox.com",
                    "referer": "https://www.roblox.com/my/account",
                    "x-csrf-token": csrf_token
                }
                cookies = {".ROBLOSECURITY": auth_cookie}
                
                proxy_str = list(proxy.values())[0]
                timeout = httpx.Timeout(self.settings.request_timeout, connect=self.settings.connection_timeout)
                try:
                    req = httpx.post("https://auth.roblox.com/v1/authentication-ticket",
                                    headers=headers, cookies=cookies, json={}, proxy=proxy_str,
                                    timeout=timeout)
                except TypeError:
                    req = httpx.post("https://auth.roblox.com/v1/authentication-ticket",
                                    headers=headers, cookies=cookies, json={}, proxies=proxy,
                                    timeout=timeout)
                
                if req.status_code == 401:
                    log_callback(f"✗ Unauthorized (401). Cookie is invalid.\n\n")
                    return None
                
                if req.status_code == 429:
                    log_callback(f"⚠ Rate limited (429). Switching proxy and retrying...\n")
                    time.sleep(random.uniform(3, 6))
                    continue
                
                if "rbx-authentication-ticket" not in req.headers:
                    error_msg = f"Failed to get authentication ticket. Status: {req.status_code}"
                    if req.text:
                        error_msg += f", Response: {req.text[:200]}"
                    raise Exception(error_msg)
                
                auth_ticket = req.headers["rbx-authentication-ticket"]
                log_callback(f"Authentication Ticket: {auth_ticket}\n")
                
                time.sleep(random.uniform(1, 2))
                
                headers.update({"RBXAuthenticationNegotiation": "1"})
                
                try:
                    req1 = httpx.post("https://auth.roblox.com/v1/authentication-ticket/redeem",
                                    headers=headers, json={"authenticationTicket": auth_ticket}, proxy=proxy_str,
                                    timeout=timeout)
                except TypeError:
                    req1 = httpx.post("https://auth.roblox.com/v1/authentication-ticket/redeem",
                                    headers=headers, json={"authenticationTicket": auth_ticket}, proxies=proxy,
                                    timeout=timeout)
                
                if req1.status_code == 401:
                    log_callback(f"✗ Unauthorized (401). Cookie is invalid.\n\n")
                    return None
                
                if req1.status_code == 429:
                    log_callback(f"⚠ Rate limited (429). Switching proxy and retrying...\n")
                    time.sleep(random.uniform(3, 6))
                    continue
                
                if "set-cookie" not in req1.headers:
                    error_msg = f"Failed to get new auth cookie. Status: {req1.status_code}"
                    if req1.text:
                        error_msg += f", Response: {req1.text[:200]}"
                    raise Exception(error_msg)
                
                match = re.search(r"\.ROBLOSECURITY=(.*?);", req1.headers["set-cookie"])
                if not match:
                    raise Exception("Failed to parse new auth cookie")
                
                new_cookie = match.group(1)
                log_callback(f"✓ SUCCESS - New Cookie Generated\n\n")
                
                time.sleep(random.uniform(2, 4))
                
                return new_cookie
                
            except (httpx.TimeoutException, httpx.ConnectError, httpx.ProxyError, ConnectionError) as e:
                error_type = type(e).__name__
                log_callback(f"✗ Proxy error ({error_type}): {str(e)[:100]}\n")
                
                if attempt < self.settings.max_retries - 1:
                    log_callback(f"→ Switching to another proxy...\n")
                    continue
                else:
                    log_callback(f"✗ Failed after {self.settings.max_retries} attempts\n\n")
                    return None
            
            except Exception as e:
                if self.should_stop:
                    return None
                log_callback(f"✗ ERROR: {str(e)[:200]}\n")
                
                if "401" in str(e) or "Unauthorized" in str(e):
                    log_callback(f"✗ Cookie is invalid (Unauthorized).\n\n")
                    return None
                
                if "429" in str(e) or "Too many requests" in str(e):
                    if attempt < self.settings.max_retries - 1:
                        log_callback(f"→ Rate limited, switching proxy...\n")
                        continue
                
                if attempt < self.settings.max_retries - 1:
                    log_callback(f"→ Retrying with another proxy...\n")
                    continue
                else:
                    log_callback(f"✗ Failed after {self.settings.max_retries} attempts\n\n")
                    return None
        
        return None


class CookieRefresherGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Vexcel Cookie Refresher - Enhanced Edition")
        self.root.geometry("1000x800")
        
        self.root.resizable(True, True)
        self.root.minsize(900, 700)
        self.is_running = False
        self.executor = None
        self.start_time = None
        self.update_timer_id = None
        
        self.bg_color = "#0a0a0a"
        self.fg_color = "#ffffff"
        self.accent_color = "#dc143c"
        self.accent_hover = "#ff1744"
        self.dark_gray = "#1a1a1a"
        self.light_gray = "#2a2a2a"
        self.success_color = "#00ff00"
        self.warning_color = "#ffaa00"
        
        self.root.configure(bg=self.bg_color)
        
        self.settings = Settings()
        self.history = SessionHistory()
        
        self.proxies_file = None
        self.cookies_file = None
        self.refresher = CookieRefresher(self.settings)
        
        self.total_cookies = 0
        self.successful_count = 0
        self.failed_count = 0
        self.remaining_count = 0
        
        self.icon_image = self.set_icon()
        self.tray_icon = None
        self.setup_tray_icon()
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.create_widgets()
        self.setup_hotkeys()
        
        if self.settings.auto_detect_files:
            self.auto_detect_files()
    
    def set_icon(self):
        icon_img = None
        try:
            if os.path.exists("ico.ico"):
                self.root.iconbitmap("ico.ico")
                icon_img = Image.open("ico.ico")
            elif os.path.exists("ico.png"):
                img = Image.open("ico.png")
                img = img.resize((256, 256), Image.Resampling.LANCZOS)
                img.save("ico.ico", format="ICO", sizes=[(256, 256)])
                self.root.iconbitmap("ico.ico")
                icon_img = img
            else:
                icon_img = self.create_default_icon()
        except Exception as e:
            print(f"Could not set icon: {e}")
            icon_img = self.create_default_icon()
        
        return icon_img
    
    def create_default_icon(self):
        img = Image.new('RGB', (256, 256), color='black')
        draw = ImageDraw.Draw(img)
        draw.polygon([(64, 64), (128, 192), (192, 64), (192, 96), (128, 224), (64, 96)], 
                     fill='#dc143c')
        return img
    
    def setup_tray_icon(self):
        try:
            if self.icon_image:
                tray_img = self.icon_image.resize((64, 64), Image.Resampling.LANCZOS)
                
                menu = pystray.Menu(
                    item('Show', self.show_window, default=True),
                    item('Hide to Tray', self.hide_window),
                    pystray.Menu.SEPARATOR,
                    item('Exit', self.quit_app)
                )
                
                self.tray_icon = pystray.Icon("vexcel", tray_img, "Vexcel Cookie Refresher", menu)
                
                threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception as e:
            print(f"Could not create tray icon: {e}")
    
    def show_window(self, icon=None, item=None):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
    
    def hide_window(self, icon=None, item=None):
        self.root.withdraw()
    
    def on_closing(self):
        if self.is_running:
            response = messagebox.askyesno("Confirm Exit", 
                                          "Refreshing is in progress. Are you sure you want to exit?")
            if not response:
                return
        self.quit_app()
    
    def quit_app(self, icon=None, item=None):
        if self.is_running and self.refresher:
            self.refresher.stop()
        
        try:
            if self.tray_icon:
                self.tray_icon.stop()
        except:
            pass
        
        try:
            self.root.quit()
        except:
            pass
        try:
            self.root.destroy()
        except:
            pass
        
        os._exit(0)
    
    def setup_hotkeys(self):
        """Setup keyboard shortcuts"""
        self.root.bind('<Control-s>', lambda e: self.start_refresh() if not self.is_running else None)
        self.root.bind('<Control-q>', lambda e: self.quit_app())
        self.root.bind('<Escape>', lambda e: self.stop_refresh() if self.is_running else None)
        self.root.bind('<F1>', lambda e: self.open_settings())
        self.root.bind('<F2>', lambda e: self.show_history())
    
    def create_widgets(self):
        title = tk.Label(self.root, text="VEXCEL COOKIE REFRESHER", 
                        font=("Arial Black", 22, "bold"), fg=self.accent_color, bg=self.bg_color)
        title.pack(pady=15)
        
        subtitle = tk.Label(self.root, text="v0.2 pow by @nightguru", 
                           fg=self.warning_color, bg=self.bg_color, font=("Arial", 10, "italic"))
        subtitle.pack()
        
        separator = tk.Label(self.root, text="━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", 
                           fg=self.accent_color, bg=self.bg_color, font=("Courier", 8))
        separator.pack(pady=5)
        
        top_buttons_frame = tk.Frame(self.root, bg=self.bg_color)
        top_buttons_frame.pack(pady=10, padx=20, fill=tk.X)
        
        settings_btn = tk.Button(top_buttons_frame, text="⚙ Settings (F1)", 
                                command=self.open_settings,
                                font=("Arial", 9, "bold"), 
                                bg=self.light_gray, fg=self.fg_color,
                                activebackground=self.accent_color, activeforeground="#ffffff",
                                relief=tk.FLAT, bd=0, padx=15, pady=5, cursor="hand2")
        settings_btn.pack(side=tk.LEFT, padx=5)
        ToolTip(settings_btn, "Configure threads, timeouts, and other settings")
        
        history_btn = tk.Button(top_buttons_frame, text="📊 History (F2)", 
                               command=self.show_history,
                               font=("Arial", 9, "bold"), 
                               bg=self.light_gray, fg=self.fg_color,
                               activebackground=self.accent_color, activeforeground="#ffffff",
                               relief=tk.FLAT, bd=0, padx=15, pady=5, cursor="hand2")
        history_btn.pack(side=tk.LEFT, padx=5)
        ToolTip(history_btn, "View previous session statistics")
        
        export_btn = tk.Button(top_buttons_frame, text="💾 Export Results", 
                              command=self.export_results,
                              font=("Arial", 9, "bold"), 
                              bg=self.light_gray, fg=self.fg_color,
                              activebackground=self.accent_color, activeforeground="#ffffff",
                              relief=tk.FLAT, bd=0, padx=15, pady=5, cursor="hand2")
        export_btn.pack(side=tk.LEFT, padx=5)
        ToolTip(export_btn, "Export results in different formats")
        
        stats_frame = tk.LabelFrame(self.root, text="◆ LIVE STATISTICS", 
                                   font=("Arial", 10, "bold"),
                                   fg=self.accent_color, bg=self.bg_color,
                                   relief=tk.GROOVE, bd=2)
        stats_frame.pack(pady=10, padx=20, fill=tk.X)
        
        stats_container = tk.Frame(stats_frame, bg=self.bg_color)
        stats_container.pack(fill=tk.X, padx=10, pady=10)
        
        success_frame = tk.Frame(stats_container, bg=self.dark_gray, relief=tk.RAISED, bd=2)
        success_frame.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=5)
        tk.Label(success_frame, text="✓ SUCCESSFUL", font=("Arial", 9, "bold"), 
                bg=self.dark_gray, fg=self.success_color).pack(pady=2)
        self.success_label = tk.Label(success_frame, text="0", font=("Arial Black", 20, "bold"), 
                                      bg=self.dark_gray, fg=self.success_color)
        self.success_label.pack(pady=5)
        
        failed_frame = tk.Frame(stats_container, bg=self.dark_gray, relief=tk.RAISED, bd=2)
        failed_frame.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=5)
        tk.Label(failed_frame, text="✗ FAILED", font=("Arial", 9, "bold"), 
                bg=self.dark_gray, fg=self.accent_color).pack(pady=2)
        self.failed_label = tk.Label(failed_frame, text="0", font=("Arial Black", 20, "bold"), 
                                     bg=self.dark_gray, fg=self.accent_color)
        self.failed_label.pack(pady=5)
        
        remaining_frame = tk.Frame(stats_container, bg=self.dark_gray, relief=tk.RAISED, bd=2)
        remaining_frame.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=5)
        tk.Label(remaining_frame, text="⏳ REMAINING", font=("Arial", 9, "bold"), 
                bg=self.dark_gray, fg=self.warning_color).pack(pady=2)
        self.remaining_label = tk.Label(remaining_frame, text="0", font=("Arial Black", 20, "bold"), 
                                       bg=self.dark_gray, fg=self.warning_color)
        self.remaining_label.pack(pady=5)
        
        speed_frame = tk.Frame(stats_container, bg=self.dark_gray, relief=tk.RAISED, bd=2)
        speed_frame.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=5)
        tk.Label(speed_frame, text="⚡ SPEED", font=("Arial", 9, "bold"), 
                bg=self.dark_gray, fg="#00aaff").pack(pady=2)
        self.speed_label = tk.Label(speed_frame, text="0/min", font=("Arial Black", 14, "bold"), 
                                    bg=self.dark_gray, fg="#00aaff")
        self.speed_label.pack(pady=2)
        self.time_label = tk.Label(speed_frame, text="00:00:00", font=("Arial", 10), 
                                   bg=self.dark_gray, fg="#aaaaaa")
        self.time_label.pack(pady=2)
        
        drop_frame = tk.Frame(self.root, bg=self.bg_color)
        drop_frame.pack(pady=10, padx=20, fill=tk.X)
        
        proxies_frame = tk.LabelFrame(drop_frame, text="◆ PROXIES FILE", 
                                     font=("Arial", 10, "bold"), 
                                     fg=self.accent_color, bg=self.bg_color,
                                     padx=10, pady=10, relief=tk.GROOVE, bd=2)
        proxies_frame.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=5)
        
        self.proxies_label = tk.Label(proxies_frame, text="⇓ DROP PROXIES HERE ⇓\n━━━━━━━━━━━━━━━━━\nproxies.txt",
                                      bg=self.dark_gray, fg="#666666", relief=tk.GROOVE, 
                                      height=4, width=28, font=("Arial", 10, "bold"), bd=3)
        self.proxies_label.pack(pady=5)
        self.proxies_label.drop_target_register(DND_FILES)
        self.proxies_label.dnd_bind('<<Drop>>', lambda e: self.drop_proxies(e))
        self.proxies_label.dnd_bind('<<DragEnter>>', lambda e: self.drag_enter(self.proxies_label))
        self.proxies_label.dnd_bind('<<DragLeave>>', lambda e: self.drag_leave(self.proxies_label))
        ToolTip(self.proxies_label, "Drop your proxies.txt file here\nFormat: ip:port, ip:port:user:pass or user:pass@ip:port")
        
        self.proxies_info = tk.Label(proxies_frame, text="", 
                                     bg=self.bg_color, fg="#888888", font=("Arial", 8))
        self.proxies_info.pack()
        
        cookies_frame = tk.LabelFrame(drop_frame, text="◆ COOKIES FILE", 
                                     font=("Arial", 10, "bold"),
                                     fg=self.accent_color, bg=self.bg_color,
                                     padx=10, pady=10, relief=tk.GROOVE, bd=2)
        cookies_frame.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=5)
        
        self.cookies_label = tk.Label(cookies_frame, text="⇓ DROP COOKIES HERE ⇓\n━━━━━━━━━━━━━━━━━\ncookies.txt",
                                     bg=self.dark_gray, fg="#666666", relief=tk.GROOVE, 
                                     height=4, width=28, font=("Arial", 10, "bold"), bd=3)
        self.cookies_label.pack(pady=5)
        self.cookies_label.drop_target_register(DND_FILES)
        self.cookies_label.dnd_bind('<<Drop>>', lambda e: self.drop_cookies(e))
        self.cookies_label.dnd_bind('<<DragEnter>>', lambda e: self.drag_enter(self.cookies_label))
        self.cookies_label.dnd_bind('<<DragLeave>>', lambda e: self.drag_leave(self.cookies_label))
        ToolTip(self.cookies_label, "Drop your cookies.txt file here\nOne cookie per line")
        
        self.cookies_info = tk.Label(cookies_frame, text="", 
                                     bg=self.bg_color, fg="#888888", font=("Arial", 8))
        self.cookies_info.pack()
        
        button_frame = tk.Frame(self.root, bg=self.bg_color)
        button_frame.pack(pady=15)
        
        self.start_button = tk.Button(button_frame, text="▶ START (Ctrl+S)", 
                                     command=self.start_refresh,
                                     font=("Arial Black", 12, "bold"), 
                                     bg=self.accent_color, fg="#ffffff",
                                     activebackground=self.accent_hover, activeforeground="#ffffff",
                                     disabledforeground="#ffffff",
                                     height=2, width=20, state=tk.DISABLED,
                                     relief=tk.RAISED, bd=3, cursor="hand2")
        self.start_button.pack(side=tk.LEFT, padx=10)
        ToolTip(self.start_button, "Start refreshing cookies (Ctrl+S)")
        
        self.stop_button = tk.Button(button_frame, text="■ STOP (Esc)", 
                                    command=self.stop_refresh,
                                    font=("Arial Black", 12, "bold"), 
                                    bg=self.dark_gray, fg="#ffffff",
                                    activebackground=self.accent_color, activeforeground="#ffffff",
                                    height=2, width=15, state=tk.DISABLED,
                                    relief=tk.RAISED, bd=3, cursor="hand2")
        self.stop_button.pack(side=tk.LEFT, padx=10)
        ToolTip(self.stop_button, "Stop refreshing process (Escape)")
        
        progress_frame = tk.Frame(self.root, bg=self.bg_color)
        progress_frame.pack(pady=5, padx=20, fill=tk.X)
        
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("red.Horizontal.TProgressbar", 
                       background=self.accent_color, 
                       troughcolor=self.dark_gray,
                       bordercolor=self.bg_color,
                       lightcolor=self.accent_color,
                       darkcolor=self.accent_color,
                       thickness=20)
        
        style.configure("Custom.Vertical.TScrollbar",
                       background=self.light_gray,
                       troughcolor=self.dark_gray,
                       bordercolor=self.dark_gray,
                       arrowcolor="#666666",
                       darkcolor=self.light_gray,
                       lightcolor=self.light_gray)
        style.map("Custom.Vertical.TScrollbar",
                 background=[('active', self.accent_color), ('!active', self.light_gray)])
        
        self.progress = ttk.Progressbar(progress_frame, mode='determinate', 
                                       style="red.Horizontal.TProgressbar")
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.progress_label = tk.Label(progress_frame, text="0%", 
                                      bg=self.bg_color, fg=self.fg_color,
                                      font=("Arial Black", 10), width=6)
        self.progress_label.pack(side=tk.LEFT, padx=10)
        
        self.eta_label = tk.Label(self.root, text="", 
                                 bg=self.bg_color, fg="#888888", font=("Arial", 9))
        self.eta_label.pack()
        
        log_frame = tk.LabelFrame(self.root, text="◆ SYSTEM LOG", 
                                 font=("Arial", 10, "bold"),
                                 fg=self.accent_color, bg=self.bg_color,
                                 relief=tk.GROOVE, bd=2)
        log_frame.pack(pady=10, padx=20, fill=tk.BOTH, expand=True)
        
        text_container = tk.Frame(log_frame, bg=self.dark_gray)
        text_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        scrollbar = ttk.Scrollbar(text_container, style="Custom.Vertical.TScrollbar")
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.log_text = tk.Text(text_container, height=12, 
                               font=("Consolas", 9), 
                               bg=self.dark_gray, 
                               fg="#00ff00",
                               insertbackground=self.accent_color,
                               selectbackground=self.accent_color,
                               relief=tk.FLAT,
                               yscrollcommand=scrollbar.set,
                               wrap=tk.WORD)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar.config(command=self.log_text.yview)
        
        self.log_text.tag_config("error", foreground=self.accent_color)
        self.log_text.tag_config("success", foreground="#00ff00")
        self.log_text.tag_config("info", foreground="#ffffff")
        self.log_text.tag_config("warning", foreground=self.warning_color)
        
        self.status_label = tk.Label(self.root, text="◆ Ready. Drop files to begin or they will be auto-detected.", 
                                    relief=tk.FLAT, anchor=tk.W,
                                    bg=self.light_gray, fg=self.fg_color,
                                    font=("Arial", 9), padx=10, pady=5)
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)
    
    def drag_enter(self, widget):
        """Highlight widget when drag enters"""
        widget.config(bg=self.accent_hover, fg="#ffffff", relief=tk.SOLID, bd=3)
    
    def drag_leave(self, widget):
        """Remove highlight when drag leaves"""
        if not hasattr(widget, 'file_loaded') or not widget.file_loaded:
            widget.config(bg=self.dark_gray, fg="#666666", relief=tk.GROOVE, bd=3)
        else:
            widget.config(relief=tk.GROOVE, bd=3)
    
    def auto_detect_files(self):
        """Auto-detect proxies.txt and cookies.txt in current directory"""
        current_dir = os.getcwd()
        proxies_file = os.path.join(current_dir, "proxies.txt")
        cookies_file = os.path.join(current_dir, "cookies.txt")
        
        if os.path.exists(proxies_file) and not self.proxies_file:
            self.load_proxies_file(proxies_file, auto=True)
        
        if os.path.exists(cookies_file) and not self.cookies_file:
            self.load_cookies_file(cookies_file, auto=True)
    
    def drop_proxies(self, event):
        file_path = event.data.strip('{}')
        self.load_proxies_file(file_path)
    
    def load_proxies_file(self, file_path, auto=False):
        try:
            lines = self.refresher.load_file(file_path)
            valid = sum(1 for line in lines if self.refresher.validate_proxy(line))
            
            self.proxies_file = file_path
            filename = os.path.basename(file_path)
            self.proxies_label.config(text=f"✓ LOADED ✓\n━━━━━━━━━━━━━━━━━\n{filename}", 
                                     bg=self.accent_color, fg="white")
            self.proxies_label.file_loaded = True
            self.proxies_info.config(text=f"{len(lines)} total ({valid} valid format)")
            
            prefix = "🔍 Auto-detected: " if auto else "✓ Loaded: "
            self.log(f"{prefix}proxies file: {file_path}\n", "success")
            self.log(f"   Total: {len(lines)}, Valid format: {valid}\n", "info")
            self.check_ready()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load proxies file:\n{str(e)}")
    
    def drop_cookies(self, event):
        file_path = event.data.strip('{}')
        self.load_cookies_file(file_path)
    
    def load_cookies_file(self, file_path, auto=False):
        try:
            lines = self.refresher.load_file(file_path)
            valid = sum(1 for line in lines if self.refresher.validate_cookie(line))
            
            self.cookies_file = file_path
            filename = os.path.basename(file_path)
            self.cookies_label.config(text=f"✓ LOADED ✓\n━━━━━━━━━━━━━━━━━\n{filename}", 
                                     bg=self.accent_color, fg="white")
            self.cookies_label.file_loaded = True
            self.cookies_info.config(text=f"{len(lines)} total ({valid} valid format)")
            
            prefix = "🔍 Auto-detected: " if auto else "✓ Loaded: "
            self.log(f"{prefix}cookies file: {file_path}\n", "success")
            self.log(f"   Total: {len(lines)}, Valid format: {valid}\n", "info")
            self.check_ready()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load cookies file:\n{str(e)}")
    
    def check_ready(self):
        if self.proxies_file and self.cookies_file and not self.is_running:
            self.start_button.config(state=tk.NORMAL, bg=self.accent_hover)
            self.status_label.config(text="◆ Ready to start! Press START or Ctrl+S")
    
    def log(self, message, tag="info"):
        self.log_text.insert(tk.END, message, tag)
        self.log_text.see(tk.END)
        self.root.update()
    
    def update_stats(self, success=None, failed=None, remaining=None):
        """Update live statistics"""
        if success is not None:
            self.successful_count = success
            self.success_label.config(text=str(success))
        
        if failed is not None:
            self.failed_count = failed
            self.failed_label.config(text=str(failed))
        
        if remaining is not None:
            self.remaining_count = remaining
            self.remaining_label.config(text=str(remaining))
        
        if self.total_cookies > 0:
            completed = self.successful_count + self.failed_count
            percentage = int((completed / self.total_cookies) * 100)
            self.progress['value'] = percentage
            self.progress_label.config(text=f"{percentage}%")
            
            if self.start_time and completed > 0:
                elapsed = time.time() - self.start_time
                avg_time = elapsed / completed
                remaining_time = avg_time * self.remaining_count
                
                eta_str = str(timedelta(seconds=int(remaining_time)))
                self.eta_label.config(text=f"ETA: {eta_str}")
                
                speed = (completed / elapsed) * 60
                self.speed_label.config(text=f"{speed:.1f}/min")
        
        self.root.update()
    
    def update_timer(self):
        """Update elapsed time display"""
        if self.is_running and self.start_time:
            elapsed = time.time() - self.start_time
            time_str = str(timedelta(seconds=int(elapsed)))
            self.time_label.config(text=time_str)
            self.update_timer_id = self.root.after(1000, self.update_timer)
    
    def play_sound(self, sound_type="complete"):
        """Play system sound"""
        if not self.settings.sound_enabled:
            return
        try:
            import winsound
            if sound_type == "complete":
                winsound.MessageBeep(winsound.MB_OK)
            elif sound_type == "error":
                winsound.MessageBeep(winsound.MB_ICONHAND)
        except:
            pass
    
    def notify_tray(self, message):
        """Show tray notification"""
        try:
            if self.tray_icon:
                self.tray_icon.notify(message, "Vexcel Cookie Refresher")
        except:
            pass
    
    def start_refresh(self):
        if self.is_running:
            return
        
        if not self.proxies_file or not self.cookies_file:
            messagebox.showwarning("Missing Files", "Please load both proxies and cookies files first!")
            return
        
        self.is_running = True
        self.refresher.should_stop = False
        self.start_button.config(state=tk.DISABLED, bg=self.dark_gray)
        self.stop_button.config(state=tk.NORMAL, bg=self.accent_color)
        self.progress['mode'] = 'determinate'
        self.progress['value'] = 0
        self.log_text.delete(1.0, tk.END)
        
        self.successful_count = 0
        self.failed_count = 0
        self.start_time = time.time()
        
        self.log("="*70 + "\n", "info")
        self.log("◆ VEXCEL COOKIE REFRESHER - ENHANCED EDITION\n", "info")
        self.log("="*70 + "\n\n", "info")
        
        self.update_timer()
        
        thread = threading.Thread(target=self.refresh_all, daemon=True)
        thread.start()
    
    def stop_refresh(self):
        if not self.is_running:
            return
        
        response = messagebox.askyesno("Confirm Stop", "Are you sure you want to stop the refresh process?")
        if response:
            self.log("\n⚠ STOPPING... Please wait...\n", "warning")
            self.refresher.stop()
            self.status_label.config(text="◆ Stopping process...", fg=self.warning_color)
    
    def refresh_all(self):
        output_file = None
        try:
            self.status_label.config(text="Loading files...", fg=self.fg_color)
            
            proxies = self.refresher.load_file(self.proxies_file)
            cookies = self.refresher.load_file(self.cookies_file)
            
            self.total_cookies = len(cookies)
            self.remaining_count = len(cookies)
            self.update_stats(success=0, failed=0, remaining=len(cookies))
            
            self.log(f"Loaded {len(proxies)} proxies\n")
            self.log(f"Loaded {len(cookies)} cookies\n\n")
            
            self.status_label.config(text="Checking proxies...")
            
            def proxy_progress(checked, total):
                pct = int((checked / total) * 100)
                self.status_label.config(text=f"Checking proxies... ({checked}/{total}) - {pct}%")
            
            self.refresher.check_all_proxies(proxies, self.log, proxy_progress)
            
            if self.refresher.should_stop:
                self.handle_stop()
                return
            
            results = [None] * len(cookies)
            successful = 0
            failed = 0
            completed = 0
            results_lock = threading.Lock()
            
            def refresh_single_cookie(cookie_data):
                nonlocal successful, failed, completed
                if self.refresher.should_stop:
                    return None
                
                index, cookie = cookie_data
                
                with self.refresher.log_lock:
                    self.log(f"{'='*70}\n")
                    self.log(f"Cookie #{index}/{len(cookies)}\n")
                    self.log(f"{'='*70}\n")
                
                new_cookie = self.refresher.refresh_cookie(cookie, self.log)
                
                with results_lock:
                    completed += 1
                    if new_cookie:
                        results[index - 1] = new_cookie
                        successful += 1
                    else:
                        results[index - 1] = f"FAILED: {cookie}"
                        failed += 1
                    
                    remaining = len(cookies) - completed
                    self.update_stats(success=successful, failed=failed, remaining=remaining)
                    self.status_label.config(text=f"Refreshing cookies... ({completed}/{len(cookies)})")
                
                return new_cookie
            
            max_workers = min(self.settings.max_workers, len(cookies))
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(refresh_single_cookie, (i, cookie)): cookie 
                          for i, cookie in enumerate(cookies, 1)}
                
                for future in as_completed(futures):
                    if self.refresher.should_stop:
                        executor.shutdown(wait=False, cancel_futures=True)
                        self.handle_stop()
                        return
                    try:
                        future.result()
                    except Exception as e:
                        with self.refresher.log_lock:
                            self.log(f"✗ Thread error: {str(e)}\n", "error")
            
            if self.refresher.should_stop:
                self.handle_stop()
                return
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"vexcel-{timestamp}.txt"
            failed_file = f"vexcel-failed-{timestamp}.txt"
            
            with open(output_file, "w", encoding="utf-8") as f:
                for result in results:
                    if not result.startswith("FAILED:"):
                        if result.startswith("_|WARNING:"):
                            f.write(f"{result}\n")
                        else:
                            f.write(f"_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-as-you-and-to-steal-your-ROBUX-and-items.|_{result}\n")
            

            failed_count_to_save = sum(1 for r in results if r and r.startswith("FAILED:"))
            if failed_count_to_save > 0:
                with open(failed_file, "w", encoding="utf-8") as f:
                    for result in results:
                        if result and result.startswith("FAILED:"):
                            cookie_part = result.replace("FAILED: ", "")
                            f.write(f"{cookie_part}\n")
            
            duration = int(time.time() - self.start_time)
            duration_str = str(timedelta(seconds=duration))
            
            self.history.add_session(len(cookies), successful, failed, duration_str, output_file)
            
            self.log(f"\n{'='*70}\n", "info")
            self.log(f"◆ COMPLETE!\n", "success")
            self.log(f"{'='*70}\n", "info")
            self.log(f"✓ Successful: {successful}/{len(cookies)} ({successful/len(cookies)*100:.1f}%)\n", "success")
            if failed > 0:
                self.log(f"✗ Failed: {failed}/{len(cookies)} ({failed/len(cookies)*100:.1f}%)\n", "error")
            self.log(f"⏱ Total time: {duration_str}\n", "info")
            self.log(f"💾 Results saved to: {output_file}\n", "info")
            if failed_count_to_save > 0:
                self.log(f"💾 Failed cookies saved to: {failed_file}\n", "info")
            
            self.progress['value'] = 100
            self.progress_label.config(text="100%")
            self.status_label.config(text=f"◆ Complete! Results saved to {output_file}", fg=self.success_color)
            
            self.play_sound("complete")
            self.notify_tray(f"Refresh complete! Success: {successful}/{len(cookies)}")
            
            msg = (f"Cookie refresh complete!\n\n"
                   f"Successful: {successful} ({successful/len(cookies)*100:.1f}%)\n"
                   f"Failed: {failed} ({failed/len(cookies)*100:.1f}%)\n"
                   f"Time: {duration_str}\n\n"
                   f"Results saved to:\n{output_file}")
            if failed_count_to_save > 0:
                msg += f"\n\nFailed cookies saved to:\n{failed_file}"
            messagebox.showinfo("Complete!", msg)
            
        except Exception as e:
            self.log(f"\n\n✗ FATAL ERROR: {str(e)}\n", "error")
            self.status_label.config(text="◆ Error occurred!", fg=self.accent_color)
            self.play_sound("error")
            messagebox.showerror("Error", f"An error occurred:\n{str(e)}")
        
        finally:
            self.is_running = False
            self.start_button.config(state=tk.NORMAL, bg=self.accent_color)
            self.stop_button.config(state=tk.DISABLED, bg=self.dark_gray)
            if self.update_timer_id:
                self.root.after_cancel(self.update_timer_id)
                self.update_timer_id = None
    
    def handle_stop(self):
        """Handle stopped refresh"""
        self.log("\n⚠ Process stopped by user\n", "warning")
        self.status_label.config(text="◆ Stopped by user", fg=self.warning_color)
        self.is_running = False
        self.start_button.config(state=tk.NORMAL, bg=self.accent_color)
        self.stop_button.config(state=tk.DISABLED, bg=self.dark_gray)
        if self.update_timer_id:
            self.root.after_cancel(self.update_timer_id)
            self.update_timer_id = None
    
    def open_settings(self):
        """Open settings window"""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Vexcel Settings")
        settings_window.geometry("600x700")
        settings_window.configure(bg=self.bg_color)
        settings_window.resizable(False, False)
        settings_window.transient(self.root)
        settings_window.grab_set()
        
        try:
            if os.path.exists("ico.ico"):
                settings_window.iconbitmap("ico.ico")
        except:
            pass
        
        title_frame = tk.Frame(settings_window, bg=self.dark_gray, relief=tk.RAISED, bd=2)
        title_frame.pack(fill=tk.X, pady=(0, 20))
        
        tk.Label(title_frame, text="⚙", 
                font=("Arial", 28), 
                fg=self.accent_color, bg=self.dark_gray).pack(pady=(15, 5))
        
        tk.Label(title_frame, text="SETTINGS", 
                font=("Arial Black", 18, "bold"), 
                fg=self.accent_color, bg=self.dark_gray).pack()
        
        tk.Label(title_frame, text="Configure performance and behavior", 
                font=("Arial", 9, "italic"), 
                fg="#888888", bg=self.dark_gray).pack(pady=(0, 15))
        
        main_container = tk.Frame(settings_window, bg=self.bg_color)
        main_container.pack(fill=tk.BOTH, expand=True, padx=20)
        
        perf_section = tk.LabelFrame(main_container, text="  ⚡ PERFORMANCE  ", 
                                    font=("Arial", 11, "bold"),
                                    fg=self.accent_color, bg=self.bg_color,
                                    relief=tk.GROOVE, bd=2)
        perf_section.pack(fill=tk.X, pady=(0, 15))
        
        perf_frame = tk.Frame(perf_section, bg=self.bg_color)
        perf_frame.pack(fill=tk.X, padx=15, pady=10)
        
        row_frame1 = tk.Frame(perf_frame, bg=self.dark_gray, relief=tk.FLAT)
        row_frame1.pack(fill=tk.X, pady=5)
        
        tk.Label(row_frame1, text="🍪 Cookie Refresh Threads:", 
                font=("Arial", 10, "bold"), 
                fg=self.fg_color, bg=self.dark_gray, anchor=tk.W).pack(side=tk.LEFT, padx=10, pady=8, fill=tk.X, expand=True)
        
        workers_var = tk.IntVar(value=self.settings.max_workers)
        workers_spin = tk.Spinbox(row_frame1, from_=1, to=20, textvariable=workers_var,
                                 font=("Arial", 11, "bold"), width=8, bg=self.light_gray,
                                 fg=self.fg_color, buttonbackground=self.accent_color,
                                 relief=tk.FLAT, bd=0)
        workers_spin.pack(side=tk.RIGHT, padx=10, pady=5)
        ToolTip(workers_spin, "Number of cookies to refresh simultaneously\n1-20: Higher = faster but may trigger rate limits\nRecommended: 5-10")
        
        row_frame2 = tk.Frame(perf_frame, bg=self.dark_gray, relief=tk.FLAT)
        row_frame2.pack(fill=tk.X, pady=5)
        
        tk.Label(row_frame2, text="🔍 Proxy Check Threads:", 
                font=("Arial", 10, "bold"), 
                fg=self.fg_color, bg=self.dark_gray, anchor=tk.W).pack(side=tk.LEFT, padx=10, pady=8, fill=tk.X, expand=True)
        
        proxy_workers_var = tk.IntVar(value=self.settings.proxy_workers)
        proxy_workers_spin = tk.Spinbox(row_frame2, from_=5, to=50, textvariable=proxy_workers_var,
                                       font=("Arial", 11, "bold"), width=8, bg=self.light_gray,
                                       fg=self.fg_color, buttonbackground=self.accent_color,
                                       relief=tk.FLAT, bd=0)
        proxy_workers_spin.pack(side=tk.RIGHT, padx=10, pady=5)
        ToolTip(proxy_workers_spin, "Number of proxies to check simultaneously\n5-50: Higher = faster proxy validation\nRecommended: 20-30")
        
        row_frame3 = tk.Frame(perf_frame, bg=self.dark_gray, relief=tk.FLAT)
        row_frame3.pack(fill=tk.X, pady=5)
        
        tk.Label(row_frame3, text="🔄 Max Retries per Cookie:", 
                font=("Arial", 10, "bold"), 
                fg=self.fg_color, bg=self.dark_gray, anchor=tk.W).pack(side=tk.LEFT, padx=10, pady=8, fill=tk.X, expand=True)
        
        retries_var = tk.IntVar(value=self.settings.max_retries)
        retries_spin = tk.Spinbox(row_frame3, from_=1, to=10, textvariable=retries_var,
                                 font=("Arial", 11, "bold"), width=8, bg=self.light_gray,
                                 fg=self.fg_color, buttonbackground=self.accent_color,
                                 relief=tk.FLAT, bd=0)
        retries_spin.pack(side=tk.RIGHT, padx=10, pady=5)
        ToolTip(retries_spin, "How many times to retry a failed cookie\n1-10: Higher = more attempts but slower\nRecommended: 3-5")
        
        timeout_section = tk.LabelFrame(main_container, text="  ⏱ TIMEOUTS  ", 
                                       font=("Arial", 11, "bold"),
                                       fg=self.accent_color, bg=self.bg_color,
                                       relief=tk.GROOVE, bd=2)
        timeout_section.pack(fill=tk.X, pady=(0, 15))
        
        timeout_frame = tk.Frame(timeout_section, bg=self.bg_color)
        timeout_frame.pack(fill=tk.X, padx=15, pady=10)
        
        row_frame4 = tk.Frame(timeout_frame, bg=self.dark_gray, relief=tk.FLAT)
        row_frame4.pack(fill=tk.X, pady=5)
        
        tk.Label(row_frame4, text="🔌 Connection Timeout:", 
                font=("Arial", 10, "bold"), 
                fg=self.fg_color, bg=self.dark_gray, anchor=tk.W).pack(side=tk.LEFT, padx=10, pady=8, fill=tk.X, expand=True)
        
        conn_timeout_var = tk.DoubleVar(value=self.settings.connection_timeout)
        conn_timeout_spin = tk.Spinbox(row_frame4, from_=5.0, to=30.0, increment=1.0,
                                      textvariable=conn_timeout_var,
                                      font=("Arial", 11, "bold"), width=8, bg=self.light_gray,
                                      fg=self.fg_color, buttonbackground=self.accent_color,
                                      relief=tk.FLAT, bd=0)
        conn_timeout_spin.pack(side=tk.RIGHT, padx=10, pady=5)
        
        tk.Label(row_frame4, text="sec", 
                font=("Arial", 9), 
                fg="#888888", bg=self.dark_gray).pack(side=tk.RIGHT, padx=(0, 5))
        ToolTip(conn_timeout_spin, "Time to wait for proxy connection\n5-30 seconds\nRecommended: 10")
        
        row_frame5 = tk.Frame(timeout_frame, bg=self.dark_gray, relief=tk.FLAT)
        row_frame5.pack(fill=tk.X, pady=5)
        
        tk.Label(row_frame5, text="📡 Request Timeout:", 
                font=("Arial", 10, "bold"), 
                fg=self.fg_color, bg=self.dark_gray, anchor=tk.W).pack(side=tk.LEFT, padx=10, pady=8, fill=tk.X, expand=True)
        
        req_timeout_var = tk.DoubleVar(value=self.settings.request_timeout)
        req_timeout_spin = tk.Spinbox(row_frame5, from_=10.0, to=60.0, increment=5.0,
                                     textvariable=req_timeout_var,
                                     font=("Arial", 11, "bold"), width=8, bg=self.light_gray,
                                     fg=self.fg_color, buttonbackground=self.accent_color,
                                     relief=tk.FLAT, bd=0)
        req_timeout_spin.pack(side=tk.RIGHT, padx=10, pady=5)
        
        tk.Label(row_frame5, text="sec", 
                font=("Arial", 9), 
                fg="#888888", bg=self.dark_gray).pack(side=tk.RIGHT, padx=(0, 5))
        ToolTip(req_timeout_spin, "Time to wait for API response\n10-60 seconds\nRecommended: 30")
        
        options_section = tk.LabelFrame(main_container, text="  🎛 OPTIONS  ", 
                                       font=("Arial", 11, "bold"),
                                       fg=self.accent_color, bg=self.bg_color,
                                       relief=tk.GROOVE, bd=2)
        options_section.pack(fill=tk.X, pady=(0, 15))
        
        options_frame = tk.Frame(options_section, bg=self.bg_color)
        options_frame.pack(fill=tk.X, padx=15, pady=10)
        
        sound_frame = tk.Frame(options_frame, bg=self.dark_gray, relief=tk.FLAT)
        sound_frame.pack(fill=tk.X, pady=5)
        
        sound_var = tk.BooleanVar(value=self.settings.sound_enabled)
        sound_check = tk.Checkbutton(sound_frame, text="🔊 Enable Sound Notifications", 
                                    variable=sound_var,
                                    font=("Arial", 10, "bold"), 
                                    fg=self.fg_color, bg=self.dark_gray,
                                    selectcolor=self.light_gray,
                                    activebackground=self.dark_gray,
                                    activeforeground=self.accent_color,
                                    relief=tk.FLAT, bd=0, padx=10, pady=10)
        sound_check.pack(fill=tk.X)
        ToolTip(sound_check, "Play sound when refresh completes or errors occur")
        
        autodetect_frame = tk.Frame(options_frame, bg=self.dark_gray, relief=tk.FLAT)
        autodetect_frame.pack(fill=tk.X, pady=5)
        
        auto_detect_var = tk.BooleanVar(value=self.settings.auto_detect_files)
        auto_detect_check = tk.Checkbutton(autodetect_frame, text="📁 Auto-detect files on startup", 
                                          variable=auto_detect_var,
                                          font=("Arial", 10, "bold"), 
                                          fg=self.fg_color, bg=self.dark_gray,
                                          selectcolor=self.light_gray,
                                          activebackground=self.dark_gray,
                                          activeforeground=self.accent_color,
                                          relief=tk.FLAT, bd=0, padx=10, pady=10)
        auto_detect_check.pack(fill=tk.X)
        ToolTip(auto_detect_check, "Automatically load proxies.txt and cookies.txt from current directory")
        
        btn_frame = tk.Frame(settings_window, bg=self.bg_color)
        btn_frame.pack(pady=20)
        
        def save_settings():
            self.settings.max_workers = workers_var.get()
            self.settings.proxy_workers = proxy_workers_var.get()
            self.settings.max_retries = retries_var.get()
            self.settings.connection_timeout = conn_timeout_var.get()
            self.settings.request_timeout = req_timeout_var.get()
            self.settings.sound_enabled = sound_var.get()
            self.settings.auto_detect_files = auto_detect_var.get()
            self.settings.save()
            
            self.refresher.settings = self.settings
            
            messagebox.showinfo("Saved", "✓ Settings saved successfully!", parent=settings_window)
            settings_window.destroy()
        
        save_btn = tk.Button(btn_frame, text="💾 Save", command=save_settings,
                 font=("Arial Black", 12, "bold"), 
                 bg=self.accent_color, fg="#ffffff",
                 activebackground=self.accent_hover,
                 activeforeground="#ffffff",
                 width=15, height=2, cursor="hand2",
                 relief=tk.RAISED, bd=3)
        save_btn.pack(side=tk.LEFT, padx=10)
        
        cancel_btn = tk.Button(btn_frame, text="✖ Cancel", command=settings_window.destroy,
                 font=("Arial Black", 12, "bold"), 
                 bg=self.light_gray, fg="#ffffff",
                 activebackground=self.dark_gray,
                 activeforeground="#ffffff",
                 width=15, height=2, cursor="hand2",
                 relief=tk.RAISED, bd=3)
        cancel_btn.pack(side=tk.LEFT, padx=10)
        
        def on_enter_save(e):
            save_btn.config(bg=self.accent_hover)
        def on_leave_save(e):
            save_btn.config(bg=self.accent_color)
        def on_enter_cancel(e):
            cancel_btn.config(bg=self.dark_gray)
        def on_leave_cancel(e):
            cancel_btn.config(bg=self.light_gray)
            
        save_btn.bind("<Enter>", on_enter_save)
        save_btn.bind("<Leave>", on_leave_save)
        cancel_btn.bind("<Enter>", on_enter_cancel)
        cancel_btn.bind("<Leave>", on_leave_cancel)
    
    def show_history(self):
        """Show session history window"""
        history_window = tk.Toplevel(self.root)
        history_window.title("Vexcel Session History")
        history_window.geometry("800x600")
        history_window.configure(bg=self.bg_color)
        history_window.transient(self.root)
        
        try:
            if os.path.exists("ico.ico"):
                history_window.iconbitmap("ico.ico")
        except:
            pass
        
        title_frame = tk.Frame(history_window, bg=self.dark_gray, relief=tk.RAISED, bd=2)
        title_frame.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(title_frame, text="📊", 
                font=("Arial", 28), 
                fg=self.accent_color, bg=self.dark_gray).pack(pady=(15, 5))
        
        tk.Label(title_frame, text="SESSION HISTORY", 
                font=("Arial Black", 16, "bold"), 
                fg=self.accent_color, bg=self.dark_gray).pack()
        
        tk.Label(title_frame, text="View your previous refresh sessions", 
                font=("Arial", 9, "italic"), 
                fg="#888888", bg=self.dark_gray).pack(pady=(0, 15))
        
        if not self.history.sessions:
            tk.Label(history_window, text="No session history yet", 
                    font=("Arial", 12), 
                    fg="#888888", bg=self.bg_color).pack(pady=50)
            return
        
        canvas = tk.Canvas(history_window, bg=self.bg_color, highlightthickness=0)
        scrollbar = ttk.Scrollbar(history_window, orient="vertical", command=canvas.yview,
                                 style="Custom.Vertical.TScrollbar")
        scrollable_frame = tk.Frame(canvas, bg=self.bg_color)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        for i, session in enumerate(self.history.sessions):
            session_frame = tk.Frame(scrollable_frame, bg=self.dark_gray, 
                                    relief=tk.RAISED, bd=2)
            session_frame.pack(pady=5, padx=20, fill=tk.X)
            
            header = tk.Frame(session_frame, bg=self.light_gray)
            header.pack(fill=tk.X, padx=2, pady=2)
            
            tk.Label(header, text=f"#{i+1} - {session['timestamp']}", 
                    font=("Arial", 10, "bold"), 
                    fg=self.accent_color, bg=self.light_gray).pack(side=tk.LEFT, padx=10, pady=5)
            
            tk.Label(header, text=f"Duration: {session['duration']}", 
                    font=("Arial", 9), 
                    fg="#aaaaaa", bg=self.light_gray).pack(side=tk.RIGHT, padx=10, pady=5)
            
            stats = tk.Frame(session_frame, bg=self.dark_gray)
            stats.pack(fill=tk.X, padx=10, pady=5)
            
            tk.Label(stats, text=f"Total: {session['total']}", 
                    font=("Arial", 9), fg=self.fg_color, bg=self.dark_gray).pack(side=tk.LEFT, padx=10)
            
            tk.Label(stats, text=f"✓ Success: {session['successful']}", 
                    font=("Arial", 9), fg=self.success_color, bg=self.dark_gray).pack(side=tk.LEFT, padx=10)
            
            tk.Label(stats, text=f"✗ Failed: {session['failed']}", 
                    font=("Arial", 9), fg=self.accent_color, bg=self.dark_gray).pack(side=tk.LEFT, padx=10)
            
            tk.Label(stats, text=f"Rate: {session['success_rate']}%", 
                    font=("Arial", 9, "bold"), fg=self.warning_color, bg=self.dark_gray).pack(side=tk.LEFT, padx=10)
            
            tk.Label(session_frame, text=f"📄 {session['output_file']}", 
                    font=("Arial", 8), fg="#888888", bg=self.dark_gray).pack(padx=10, pady=5, anchor=tk.W)
        
        canvas.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        scrollbar.pack(side="right", fill="y")
        
        tk.Button(history_window, text="Close", command=history_window.destroy,
                 font=("Arial", 11, "bold"), 
                 bg=self.accent_color, fg="#ffffff",
                 activebackground=self.accent_hover,
                 width=15, height=2, cursor="hand2").pack(pady=20)
    
    def export_results(self):
        """Export results in different formats"""
        if not hasattr(self, 'last_results') or not self.last_results:
            messagebox.showinfo("No Results", "No results to export. Run a refresh session first.")
            return
        
        export_window = tk.Toplevel(self.root)
        export_window.title("Export Results")
        export_window.geometry("400x300")
        export_window.configure(bg=self.bg_color)
        export_window.transient(self.root)
        export_window.grab_set()
        
        tk.Label(export_window, text="💾 EXPORT RESULTS", 
                font=("Arial Black", 14, "bold"), 
                fg=self.accent_color, bg=self.bg_color).pack(pady=20)
        
        tk.Label(export_window, text="Select export format:", 
                font=("Arial", 10), 
                fg=self.fg_color, bg=self.bg_color).pack(pady=10)
        
        format_var = tk.StringVar(value="txt")
        
        formats = [
            ("Text File (.txt)", "txt"),
            ("JSON File (.json)", "json"),
            ("CSV File (.csv)", "csv"),
            ("Successful Only (.txt)", "success"),
            ("Failed Only (.txt)", "failed")
        ]
        
        for text, value in formats:
            tk.Radiobutton(export_window, text=text, variable=format_var, value=value,
                          font=("Arial", 10), fg=self.fg_color, bg=self.bg_color,
                          selectcolor=self.dark_gray,
                          activebackground=self.bg_color).pack(anchor=tk.W, padx=50, pady=5)
        
        def do_export():
            messagebox.showinfo("Export", f"Export to {format_var.get()} format", parent=export_window)
            export_window.destroy()
        
        tk.Button(export_window, text="Export", command=do_export,
                 font=("Arial", 11, "bold"), 
                 bg=self.accent_color, fg="#ffffff",
                 activebackground=self.accent_hover,
                 width=15, height=2, cursor="hand2").pack(pady=20)


if __name__ == "__main__":
    root = TkinterDnD.Tk()
    app = CookieRefresherGUI(root)
    root.mainloop()
